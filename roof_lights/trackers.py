"""Reading pass schedules from the Satlab tracker JSON API.

The tracker web page builds its pass table from GET /api/v1/tracker/schedule, which returns:

    {"success": true, "data": {"schedule": [
        {"name": "HYPSO-1", "satid": 2, "aos": "2026-10-19T10:02:22.381709Z",
         "los": "2026-10-19T10:08:41.740684Z", "length": 379.0, "maxel": 6.93, "tracked": "full"},
        ...]}}
"""
import re
from datetime import datetime, timezone
from typing import List

import requests

from . import config
from .timeline import Pass


class TrackerError(Exception):
    """The tracker couldn't be reached, or answered with something we don't understand."""


def fetch_passes(name, base_url, timeout=config.HTTP_TIMEOUT_S):
    # type: (str, str, float) -> List[Pass]
    url = base_url.rstrip("/") + config.SCHEDULE_PATH
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as e:
        raise TrackerError("no answer within {} s from {}".format(timeout, base_url)) from e
    except requests.ConnectionError as e:
        raise TrackerError("could not connect to {}".format(base_url)) from e
    except requests.HTTPError as e:
        raise TrackerError("HTTP {} from {}".format(e.response.status_code, url)) from e
    except requests.RequestException as e:
        raise TrackerError("{}: {}".format(url, e)) from e
    except ValueError as e:
        raise TrackerError("{}: response is not JSON".format(url)) from e
    return parse_schedule(payload, name)


def parse_schedule(payload, tracker):
    # type: (object, str) -> List[Pass]
    """Turn the API response into passes. An empty schedule is valid and means no passes."""
    try:
        if not payload["success"]:
            raise TrackerError("tracker reported success=false")
        rows = payload["data"]["schedule"]
        passes = []
        for row in rows:
            p = Pass(
                satellite=row["name"],
                tracker=tracker,
                aos=parse_time(row["aos"]),
                los=parse_time(row["los"]),
                tracked=row.get("tracked", "full"),
            )
            if p.los <= p.aos:
                raise TrackerError("pass of {} ends before it starts".format(p.satellite))
            passes.append(p)
        return passes
    except (KeyError, TypeError, ValueError) as e:
        raise TrackerError("unexpected schedule format: {!r}".format(e)) from e


_FRACTION = re.compile(r"\.(\d+)")


def parse_time(value):
    # type: (str) -> datetime
    """Parse the tracker's ISO 8601 timestamps, e.g. "2026-10-19T09:39:08.868591Z", as aware UTC."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # datetime.fromisoformat before Python 3.11 only accepts exactly 3 or 6 fractional digits.
    text = _FRACTION.sub(lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
