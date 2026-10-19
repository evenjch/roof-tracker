from datetime import datetime, timezone

from roof_lights.timeline import Pass


def t(hhmm, second=0):
    """A UTC time on a fixed test day, e.g. t("10:05")."""
    hour, minute = map(int, hhmm.split(":"))
    return datetime(2026, 10, 19, hour, minute, second, tzinfo=timezone.utc)


def p(aos, los, satellite="HYPSO-1", tracker="UHF", tracked="full"):
    return Pass(satellite, tracker, t(aos) if isinstance(aos, str) else aos, t(los) if isinstance(los, str) else los, tracked)
