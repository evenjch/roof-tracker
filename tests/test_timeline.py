import unittest
from datetime import timedelta

from roof_lights.lights import LightState
from roof_lights.timeline import desired_state, merge, next_change

from .helpers import p, t

MARGIN = timedelta(seconds=60)


class MergeTest(unittest.TestCase):
    def test_pass_inside_another_keeps_the_later_los(self):
        # Old bug: S-band 10:00-10:20 with UHF 10:05-10:12 inside it gave LOS 10:12.
        windows = merge([p("10:00", "10:20", tracker="S-band"), p("10:05", "10:12", tracker="UHF")], MARGIN)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].start, t("09:59"))
        self.assertEqual(windows[0].end, t("10:21"))

    def test_same_satellite_on_both_trackers_seconds_apart(self):
        # Old code required exactly equal AOS to treat these as one pass.
        windows = merge([
            p(t("10:00", 0), t("10:10", 0), tracker="S-band"),
            p(t("10:00", 3), t("10:10", 2), tracker="UHF"),
        ], MARGIN)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].end, t("10:11", 2))

    def test_partial_overlap(self):
        windows = merge([p("10:00", "10:10"), p("10:08", "10:20", satellite="HYPSO-2")], MARGIN)
        self.assertEqual([(w.start, w.end) for w in windows], [(t("09:59"), t("10:21"))])

    def test_passes_within_two_margins_merge(self):
        windows = merge([p("10:00", "10:10"), p("10:12", "10:20")], MARGIN)
        self.assertEqual(len(windows), 1)

    def test_separate_passes_stay_separate_and_sorted(self):
        windows = merge([p("12:00", "12:10"), p("10:00", "10:10")], MARGIN)
        self.assertEqual([w.start for w in windows], [t("09:59"), t("11:59")])

    def test_empty(self):
        self.assertEqual(merge([], MARGIN), [])


class DesiredStateTest(unittest.TestCase):
    def setUp(self):
        self.windows = merge([p("10:00", "10:10", satellite="HYPSO-1"), p("12:00", "12:10", satellite="HYPSO-2")], MARGIN)

    def test_red_inside_window_including_margin(self):
        self.assertEqual(desired_state(t("09:59"), self.windows, True)[0], LightState.RED)
        self.assertEqual(desired_state(t("10:10", 30), self.windows, True)[0], LightState.RED)

    def test_green_at_window_end(self):
        self.assertEqual(desired_state(t("10:11"), self.windows, True)[0], LightState.GREEN)

    def test_green_reason_names_next_pass(self):
        state, reason = desired_state(t("11:00"), self.windows, True)
        self.assertEqual(state, LightState.GREEN)
        self.assertIn("HYPSO-2", reason)

    def test_yellow_without_fresh_data(self):
        self.assertEqual(desired_state(t("11:00"), self.windows, False)[0], LightState.YELLOW)

    def test_known_pass_beats_missing_data(self):
        self.assertEqual(desired_state(t("10:05"), self.windows, False)[0], LightState.RED)

    def test_no_passes(self):
        self.assertEqual(desired_state(t("11:00"), [], True)[0], LightState.GREEN)
        self.assertEqual(desired_state(t("11:00"), [], False)[0], LightState.YELLOW)


class NextChangeTest(unittest.TestCase):
    def test_edges(self):
        windows = merge([p("10:00", "10:10")], MARGIN)
        self.assertEqual(next_change(t("09:00"), windows), t("09:59"))
        self.assertEqual(next_change(t("10:05"), windows), t("10:11"))
        self.assertIsNone(next_change(t("10:30"), windows))


if __name__ == "__main__":
    unittest.main()
