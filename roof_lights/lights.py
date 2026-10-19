"""Relay board control and the light-state file.

Also a small command line, used by systemd to show yellow when the service stops,
and handy for testing the relays by hand:

    python -m roof_lights.lights red|yellow|green|off [--reason TEXT] [--fake]
"""
import argparse
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from . import config

log = logging.getLogger(__name__)


class LightState(Enum):
    RED = "red"        # a pass is in progress (or about to start)
    YELLOW = "yellow"  # unknown: no fresh data from any tracker, or the service is stopped
    GREEN = "green"    # clear
    OFF = "off"        # all lights off (only used by hand)

    def lamps(self):
        """(red, yellow, green) on/off for this state."""
        return (self is LightState.RED, self is LightState.YELLOW, self is LightState.GREEN)


class Relay:
    """The I2C relay board driving the three lights."""

    def __init__(self, bus=config.I2C_BUS, address=config.I2C_ADDRESS, channels=None):
        import smbus2  # imported here so the rest of the package works without I2C

        self._bus = smbus2.SMBus(bus)
        self._address = address
        self._channels = channels or config.RELAY_CHANNELS

    def set(self, red, yellow, green):
        for name, on in (("red", red), ("yellow", yellow), ("green", green)):
            value = config.RELAY_ON if on else config.RELAY_OFF
            self._bus.write_byte_data(self._address, self._channels[name], value)

    def show(self, state):
        self.set(*state.lamps())


class FakeRelay:
    """Stand-in for Relay when running without the relay board."""

    def __init__(self):
        self.state = None  # type: Optional[LightState]

    def show(self, state):
        if state != self.state:
            log.info("[fake relay] %s", state.value)
        self.state = state


def write_state_file(path, state, reason, now=None):
    """Write the light state for the web visualisation.

    Written to a temporary file and renamed into place, so readers never see a half-written file.
    """
    red, yellow, green = state.lamps()
    data = {
        "red": "red" if red else "grey",
        "yellow": "yellow" if yellow else "grey",
        "green": "green" if green else "grey",
        "state": state.value,
        "reason": reason,
        "updated_at": (now or datetime.now(timezone.utc)).isoformat(),
    }
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".lightstate-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, str(path))
    except BaseException:
        os.unlink(tmp)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Set the roof lights by hand.")
    parser.add_argument("state", choices=[s.value for s in LightState])
    parser.add_argument("--reason", default="Set by hand")
    parser.add_argument("--fake", action="store_true", help="don't touch the relay board or state file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    state = LightState(args.state)
    if args.fake:
        FakeRelay().show(state)
        return
    Relay().show(state)
    write_state_file(config.STATE_FILE, state, args.reason)


if __name__ == "__main__":
    main()
