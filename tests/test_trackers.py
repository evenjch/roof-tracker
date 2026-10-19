import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from roof_lights.trackers import TrackerError, parse_schedule, parse_time

FIXTURES = Path(__file__).parent / "fixtures"


class ParseScheduleTest(unittest.TestCase):
    def test_real_uhf_response(self):
        payload = json.loads((FIXTURES / "uhf_schedule.json").read_text())
        passes = parse_schedule(payload, "UHF")
        self.assertEqual(len(passes), 4)
        first = passes[0]
        self.assertEqual(first.satellite, "FRAMSAT-1")
        self.assertEqual(first.tracker, "UHF")
        self.assertEqual(first.aos, datetime(2026, 10, 19, 9, 39, 8, 868591, tzinfo=timezone.utc))
        self.assertEqual(first.los, datetime(2026, 10, 19, 9, 50, 27, 497824, tzinfo=timezone.utc))
        self.assertEqual(passes[2].tracked, "partial")

    def test_empty_schedule_means_no_passes(self):
        self.assertEqual(parse_schedule({"success": True, "data": {"schedule": []}}, "UHF"), [])

    def test_failure_and_garbage_raise_tracker_error(self):
        bad = [
            {"success": False},
            {"success": True, "data": {}},
            {"success": True, "data": {"schedule": [{"name": "X", "aos": "nonsense", "los": "nonsense"}]}},
            {"success": True, "data": {"schedule": [{"name": "X", "aos": "2026-10-19T10:00:00Z",
                                                     "los": "2026-10-19T09:00:00Z"}]}},
            "not a dict",
        ]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(TrackerError):
                parse_schedule(payload, "UHF")


class ParseTimeTest(unittest.TestCase):
    def test_formats(self):
        expected = datetime(2026, 10, 19, 10, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(parse_time("2026-10-19T10:00:00Z"), expected)
        self.assertEqual(parse_time("2026-10-19T10:00:00+00:00"), expected)
        self.assertEqual(parse_time("2026-10-19T12:00:00+02:00"), expected)
        self.assertEqual(parse_time("2026-10-19T10:00:00"), expected)  # naive is taken as UTC
        self.assertEqual(parse_time("2026-10-19T10:00:00.5Z"), expected.replace(microsecond=500000))
        self.assertEqual(parse_time("2026-10-19T10:00:00.123456789Z"), expected.replace(microsecond=123456))


if __name__ == "__main__":
    unittest.main()
