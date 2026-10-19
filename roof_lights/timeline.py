"""Passes, merging them into red-light windows, and deciding which light to show.

Everything here except utcnow() is pure (no network, no hardware, no clock) so it is easy to test.
All datetimes are timezone-aware UTC.
"""
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple

from .lights import LightState


def utcnow():
    # type: () -> datetime
    return datetime.now(timezone.utc)

# satellite: e.g. "HYPSO-1"; tracker: e.g. "UHF"; tracked: "full", "partial" or "none"
Pass = namedtuple("Pass", "satellite tracker aos los tracked")

# A stretch of time when the lights should be red: one or more overlapping passes, padded by the margin.
Window = namedtuple("Window", "start end passes")


def merge(passes, margin):
    # type: (Iterable[Pass], timedelta) -> List[Window]
    """Pad every pass by `margin` and merge any that overlap, from all trackers together.

    This replaces the old S-band/UHF branching: the same satellite seen by both trackers,
    one pass inside another, and back-to-back passes all simply become one window.
    """
    windows = []  # type: List[Window]
    for p in sorted(passes, key=lambda p: p.aos):
        start, end = p.aos - margin, p.los + margin
        if windows and start <= windows[-1].end:
            last = windows[-1]
            windows[-1] = Window(last.start, max(last.end, end), last.passes + (p,))
        else:
            windows.append(Window(start, end, (p,)))
    return windows


def active_window(now, windows):
    # type: (datetime, List[Window]) -> Optional[Window]
    for w in windows:
        if w.start <= now < w.end:
            return w
    return None


def next_window(now, windows):
    # type: (datetime, List[Window]) -> Optional[Window]
    future = [w for w in windows if w.start > now]
    return min(future, key=lambda w: w.start) if future else None


def next_change(now, windows):
    # type: (datetime, List[Window]) -> Optional[datetime]
    """The next time the light could change colour: the next window start or end."""
    edges = [t for w in windows for t in (w.start, w.end) if t > now]
    return min(edges) if edges else None


def desired_state(now, windows, have_fresh_data):
    # type: (datetime, List[Window], bool) -> Tuple[LightState, str]
    """Which light to show, and a human-readable reason.

    A known pass wins over missing data: if we're inside a window from the last schedule we
    got, the lights stay red even if the trackers have since stopped answering.
    """
    current = active_window(now, windows)
    if current:
        return LightState.RED, "Pass: {} until {}".format(describe(current), local_time(current.end))
    if not have_fresh_data:
        return LightState.YELLOW, "No fresh schedule from any tracker"
    upcoming = next_window(now, windows)
    if upcoming:
        return LightState.GREEN, "Clear. Next: {} at {}".format(describe(upcoming), local_time(upcoming.start))
    return LightState.GREEN, "Clear. No passes scheduled"


def describe(window):
    # type: (Window) -> str
    """E.g. "HYPSO-1 (S-band, UHF), HYPSO-2 (UHF)"."""
    trackers_by_sat = {}
    for p in window.passes:
        trackers = trackers_by_sat.setdefault(p.satellite, [])
        if p.tracker not in trackers:
            trackers.append(p.tracker)
    return ", ".join("{} ({})".format(sat, ", ".join(t)) for sat, t in trackers_by_sat.items())


def local_time(dt):
    # type: (datetime) -> str
    return dt.astimezone().strftime("%H:%M")
