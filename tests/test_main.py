import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from roof_lights.lights import FakeRelay, LightState
from roof_lights.main import Controller
from roof_lights.status import Status, render_html, to_json
from roof_lights.trackers import TrackerError

from .helpers import p, t

TRACKERS = {"S-band": "http://sband", "UHF": "http://uhf"}


class FakeTrackers:
    """fetch() stand-in: per tracker, either a list of passes or an exception to raise."""

    def __init__(self, **responses):
        self.responses = responses

    def __call__(self, name, url):
        response = self.responses[name.replace("-", "")]
        if isinstance(response, Exception):
            raise response
        return response


class ControllerTest(unittest.TestCase):
    def make(self, fetch, state_file=None):
        self.relay = FakeRelay()
        self.status = Status(TRACKERS, now=t("09:00"))
        return Controller(self.relay, self.status, trackers=TRACKERS, fetch=fetch, state_file=state_file)

    def test_uhf_answers_sband_down(self):
        # Old bug: this combination crashed the scheduler.
        fetch = FakeTrackers(Sband=TrackerError("connection refused"), UHF=[p("10:00", "10:10")])
        c = self.make(fetch)
        c.step(t("09:30"))
        self.assertEqual(self.relay.state, LightState.GREEN)
        c.step(t("10:05"))
        self.assertEqual(self.relay.state, LightState.RED)
        tracker = {x["name"]: x for x in self.status.snapshot(t("10:05"))["trackers"]}
        self.assertIn("connection refused", tracker["S-band"]["last_error"])
        self.assertTrue(tracker["UHF"]["fresh"])

    def test_both_down_from_start_is_yellow(self):
        c = self.make(FakeTrackers(Sband=TrackerError("x"), UHF=TrackerError("y")))
        c.step(t("09:30"))
        self.assertEqual(self.relay.state, LightState.YELLOW)
        self.assertFalse(self.status.snapshot(t("09:30"))["healthy"])

    def test_cached_schedule_used_until_stale(self):
        fetch = FakeTrackers(Sband=TrackerError("x"), UHF=[p("10:00", "10:10")])
        c = self.make(fetch)
        c.step(t("09:30"))
        fetch.responses["UHF"] = TrackerError("network down")
        c.step(t("09:40"))
        self.assertEqual(self.relay.state, LightState.GREEN)   # 10 min old: still fresh
        c.step(t("10:05"))
        self.assertEqual(self.relay.state, LightState.RED)     # inside a known pass
        c.step(t("10:20"))
        self.assertEqual(self.relay.state, LightState.YELLOW)  # 50 min old and no pass

    def test_sleeps_until_window_edge_or_next_poll(self):
        c = self.make(FakeTrackers(Sband=[], UHF=[p("10:00", "10:10")]))
        self.assertEqual(c.step(t("09:30")), 60)               # next poll first
        self.assertEqual(c.step(t("09:58", 30)), 30)           # red starts at 09:59
        self.assertEqual(self.relay.state, LightState.GREEN)

    def test_state_file_written_on_change(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "lightstate.json"
            c = self.make(FakeTrackers(Sband=[], UHF=[p("10:00", "10:10")]), state_file=path)
            c.step(t("10:05"))
            data = json.loads(path.read_text())
            self.assertEqual((data["red"], data["yellow"], data["green"]), ("red", "grey", "grey"))
            c.shutdown()
            self.assertEqual(json.loads(path.read_text())["state"], "yellow")
            self.assertEqual(self.relay.state, LightState.YELLOW)


class StatusTest(unittest.TestCase):
    def test_health_requires_recent_loop(self):
        status = Status(TRACKERS, now=t("09:00"))
        status.tracker_ok("UHF", t("09:00"), 3)
        status.loop_done(t("09:00"), LightState.GREEN, "Clear", [])
        self.assertTrue(status.snapshot(t("09:01"))["healthy"])
        self.assertFalse(status.snapshot(t("09:00") + timedelta(minutes=4))["healthy"])

    def test_page_and_json_render(self):
        status = Status(TRACKERS, now=t("09:00"))
        status.tracker_failed("S-band", t("09:00"), "timeout <b>")
        c = Controller(FakeRelay(), status, trackers={"UHF": "x"}, fetch=lambda n, u: [p("10:00", "10:10")],
                       state_file=None)
        c.step(t("09:30"))
        snapshot = status.snapshot(t("09:30"))
        page = render_html(snapshot)
        self.assertIn("HYPSO-1", page)
        self.assertIn("timeout &lt;b&gt;", page)
        self.assertEqual(json.loads(to_json(snapshot))["state"], "green")


if __name__ == "__main__":
    unittest.main()
