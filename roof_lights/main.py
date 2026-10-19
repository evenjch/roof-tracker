"""The roof lights service.

Every POLL_INTERVAL it reads the pass schedule from every tracker, merges all passes into
red-light windows, and sets the lights: red inside a window, yellow if no tracker has answered
recently, green otherwise. It also wakes up exactly at window edges so the lights switch on time.

    python -m roof_lights.main             # run for real (this is what systemd runs)
    python -m roof_lights.main --dry-run   # no relay board, no state file; status page still runs
    python -m roof_lights.main --once      # one check, print the result and exit (implies --dry-run)
"""
import argparse
import logging
import os
import signal
import socket
import threading

from . import config
from .lights import FakeRelay, LightState, Relay, write_state_file
from .status import Status, start_status_server
from .timeline import desired_state, describe, local_time, merge, next_change, utcnow
from .trackers import TrackerError, fetch_passes

log = logging.getLogger("roof_lights")


class Controller:
    def __init__(self, relay, status, trackers=None, fetch=fetch_passes, state_file=config.STATE_FILE):
        self.relay = relay
        self.status = status
        self.trackers = trackers if trackers is not None else config.TRACKERS
        self.fetch = fetch
        self.state_file = state_file
        self.windows = []
        self._cache = {}  # tracker name -> (passes, fetched_at); kept when a later fetch fails
        self._last_poll = None
        self._shown = None  # (state, reason) last written to the state file

    def poll(self, now):
        for name, url in self.trackers.items():
            try:
                passes = self.fetch(name, url)
            except TrackerError as e:
                log.warning("%s: %s", name, e)
                self.status.tracker_failed(name, now, str(e))
                continue
            if config.IGNORE_UNTRACKED:
                passes = [p for p in passes if p.tracked != "none"]
            self._cache[name] = (passes, now)
            self.status.tracker_ok(name, now, len(passes))
        self._last_poll = now

    def step(self, now):
        """Poll if due, set the lights, and return how many seconds to sleep before the next step."""
        if self._last_poll is None or now - self._last_poll >= config.POLL_INTERVAL:
            self.poll(now)

        all_passes = [p for passes, _ in self._cache.values() for p in passes]
        self.windows = [w for w in merge(all_passes, config.MARGIN) if w.end > now]
        fresh = any(now - fetched_at <= config.STALE_AFTER for _, fetched_at in self._cache.values())
        state, reason = desired_state(now, self.windows, fresh)
        self._show(state, reason, now)
        self.status.loop_done(now, state, reason, self.windows)

        wake = self._last_poll + config.POLL_INTERVAL
        edge = next_change(now, self.windows)
        if edge is not None and edge < wake:
            wake = edge
        return max(1.0, (wake - now).total_seconds())

    def _show(self, state, reason, now):
        # Write the relays every step, not just on change: it's cheap, and it puts the lights
        # right again if the relay board has been power-cycled on its own.
        self.relay.show(state)
        if self._shown is None or self._shown[0] != state:
            log.info("Lights %s: %s", state.value.upper(), reason)
        if self._shown != (state, reason):
            if self.state_file:
                write_state_file(self.state_file, state, reason, now)
            self._shown = (state, reason)

    def shutdown(self):
        log.info("Stopping: lights YELLOW")
        try:
            self._show(LightState.YELLOW, "Service stopped", utcnow())
        except OSError:
            # systemd's ExecStopPost sets yellow as well, so this isn't the last chance.
            log.exception("Could not set the lights on shutdown")


def sd_notify(message):
    """Tell systemd we're ready / still alive. Does nothing when not run by systemd."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.sendto(message.encode(), address)


def setup_logging():
    # journald adds its own timestamps.
    fmt = "%(levelname)s %(name)s: %(message)s"
    if not os.environ.get("JOURNAL_STREAM"):
        fmt = "%(asctime)s " + fmt
    logging.basicConfig(level=logging.INFO, format=fmt)


def print_once(controller, now):
    snapshot = controller.status.snapshot(now)
    print("Lights: {} ({})".format(snapshot["state"].upper(), snapshot["reason"]))
    print("Red windows ahead:")
    for w in controller.windows:
        print("  {} - {}  {}".format(local_time(w.start), local_time(w.end), describe(w)))
    if not controller.windows:
        print("  none")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Roof lights that follow the trackers' pass schedules.")
    parser.add_argument("--dry-run", action="store_true", help="no relay board and no state file")
    parser.add_argument("--once", action="store_true", help="check once, print the result and exit")
    parser.add_argument("--port", type=int, default=config.STATUS_PORT, help="status page port")
    args = parser.parse_args(argv)
    setup_logging()

    dry_run = args.dry_run or args.once
    status = Status(config.TRACKERS)
    relay = FakeRelay() if dry_run else Relay()
    controller = Controller(relay, status, state_file=None if dry_run else config.STATE_FILE)

    if args.once:
        now = utcnow()
        controller.step(now)
        print_once(controller, now)
        return

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    server = start_status_server(status, args.port)
    sd_notify("READY=1")
    try:
        while not stop.is_set():
            delay = controller.step(utcnow())
            sd_notify("WATCHDOG=1")
            stop.wait(delay)
    finally:
        controller.shutdown()
        server.shutdown()


if __name__ == "__main__":
    main()
