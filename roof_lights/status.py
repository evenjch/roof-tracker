"""What the service is doing, shared between the main loop and a small HTTP status page.

    /             human-readable status page (refreshes every 30 s)
    /status.json  the same data as JSON
    /health       200 "ok" when healthy, 503 with the problems otherwise
"""
import html
import json
import logging
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .timeline import utcnow

log = logging.getLogger(__name__)

UPCOMING_SHOWN = 5


class Status:
    def __init__(self, tracker_names, stale_after=config.STALE_AFTER, max_loop_age=config.MAX_LOOP_AGE, now=None):
        self._lock = threading.Lock()
        self._stale_after = stale_after
        self._max_loop_age = max_loop_age
        self._started_at = now or utcnow()
        self._state = None
        self._reason = "Starting up"
        self._last_loop = None
        self._windows = []
        self._trackers = {
            name: {"last_ok": None, "passes": 0, "last_error": None, "last_error_at": None}
            for name in tracker_names
        }

    def tracker_ok(self, name, now, n_passes):
        with self._lock:
            self._trackers[name].update(last_ok=now, passes=n_passes)

    def tracker_failed(self, name, now, error):
        with self._lock:
            self._trackers[name].update(last_error=error, last_error_at=now)

    def loop_done(self, now, state, reason, windows):
        with self._lock:
            self._last_loop = now
            self._state = state
            self._reason = reason
            self._windows = [w for w in windows if w.end > now][:UPCOMING_SHOWN]

    def snapshot(self, now):
        """Everything the status page shows, as plain data (datetimes are left as datetimes)."""
        with self._lock:
            trackers = []
            for name, t in self._trackers.items():
                fresh = t["last_ok"] is not None and now - t["last_ok"] <= self._stale_after
                trackers.append(dict(t, name=name, fresh=fresh))

            problems = []
            if self._last_loop is None or now - self._last_loop > self._max_loop_age:
                problems.append("Main loop has not run since {}".format(_iso(self._last_loop) or "startup"))
            if not any(t["fresh"] for t in trackers):
                problems.append("No fresh schedule from any tracker")

            return {
                "state": self._state.value if self._state else None,
                "reason": self._reason,
                "healthy": not problems,
                "problems": problems,
                "now": now,
                "started_at": self._started_at,
                "last_loop": self._last_loop,
                "trackers": trackers,
                "upcoming": [
                    {
                        "start": w.start,
                        "end": w.end,
                        "passes": [p._asdict() for p in w.passes],
                    }
                    for w in self._windows
                ],
            }


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def to_json(snapshot):
    return json.dumps(snapshot, default=_iso, indent=2)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        snapshot = self.server.status.snapshot(utcnow())
        if path == "/":
            self._send(200, "text/html; charset=utf-8", render_html(snapshot))
        elif path == "/status.json":
            self._send(200, "application/json", to_json(snapshot))
        elif path == "/health":
            if snapshot["healthy"]:
                self._send(200, "text/plain; charset=utf-8", "ok\n")
            else:
                self._send(503, "text/plain; charset=utf-8", "\n".join(snapshot["problems"]) + "\n")
        else:
            self._send(404, "text/plain; charset=utf-8", "not found\n")

    def _send(self, code, content_type, body):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        log.debug("%s - %s", self.address_string(), format % args)


def start_status_server(status, port=config.STATUS_PORT, host=""):
    """Serve the status page in a background thread. Returns the server (call .shutdown() to stop)."""
    server = ThreadingHTTPServer((host, port), _Handler)
    server.daemon_threads = True
    server.status = status
    threading.Thread(target=server.serve_forever, name="status-http", daemon=True).start()
    log.info("Status page on port %d", port)
    return server


# --- HTML -----------------------------------------------------------------------------------

def _local(dt, fmt="%a %d %b %H:%M:%S"):
    return dt.astimezone().strftime(fmt) if dt else "never"


def _ago(dt, now):
    if dt is None:
        return "never"
    seconds = int((now - dt).total_seconds())
    if seconds < 90:
        text = "{} s".format(seconds)
    elif seconds < 90 * 60:
        text = "{} min".format(seconds // 60)
    else:
        text = "{:.1f} h".format(seconds / 3600)
    return "{} ({} ago)".format(_local(dt, "%H:%M:%S"), text)


def render_html(s):
    e = html.escape
    now = s["now"]

    lamps = "".join(
        '<span class="lamp {}{}" title="{}"></span>'.format(c, " on" if s["state"] == c else "", c)
        for c in ("red", "yellow", "green")
    )
    health = (
        '<p class="health ok">Healthy</p>'
        if s["healthy"]
        else '<p class="health bad">{}</p>'.format("<br>".join(e(p) for p in s["problems"]))
    )

    tracker_rows = "".join(
        "<tr><td>{}</td><td class=\"{}\">{}</td><td>{}</td><td>{}</td></tr>".format(
            e(t["name"]),
            "" if t["fresh"] else "warn",
            e(_ago(t["last_ok"], now)),
            t["passes"],
            e("{}: {}".format(_local(t["last_error_at"], "%H:%M:%S"), t["last_error"])) if t["last_error"] else "",
        )
        for t in s["trackers"]
    )

    upcoming_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            e(_local(w["start"], "%a %H:%M")),
            e(_local(w["end"], "%H:%M")),
            e(", ".join(
                "{} ({}{})".format(p["satellite"], p["tracker"], "" if p["tracked"] != "none" else ", not tracked")
                for p in w["passes"]
            )),
        )
        for w in s["upcoming"]
    ) or '<tr><td colspan="3">None known</td></tr>'

    return _PAGE.format(
        lamps=lamps,
        reason=e(s["reason"]),
        health=health,
        tracker_rows=tracker_rows,
        upcoming_rows=upcoming_rows,
        started=e(_local(s["started_at"])),
        last_loop=e(_ago(s["last_loop"], now)),
        now=e(_local(now)),
    )


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Roof lights</title>
<style>
:root {{ --bg: #f6f7f8; --fg: #1d2125; --muted: #5f6b76; --card: #fff; --line: #dde1e5;
        --off: #c9ced3; --red: #e03131; --yellow: #f2b705; --green: #2f9e44; --warn: #b35c00; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #15181b; --fg: #e6e8ea; --muted: #9aa4ad; --card: #1e2226; --line: #30363c;
          --off: #3a4047; --warn: #ffa94d; }}
}}
body {{ margin: 0; padding: 24px 16px; background: var(--bg); color: var(--fg);
       font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 760px; margin: 0 auto; }}
h1 {{ font-size: 22px; margin: 0 0 16px; }}
h2 {{ font-size: 16px; margin: 28px 0 8px; }}
.card {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px; }}
.lamps {{ display: flex; gap: 14px; margin-bottom: 12px; }}
.lamp {{ width: 44px; height: 44px; border-radius: 50%; background: var(--off); }}
.lamp.red.on {{ background: var(--red); box-shadow: 0 0 16px var(--red); }}
.lamp.yellow.on {{ background: var(--yellow); box-shadow: 0 0 16px var(--yellow); }}
.lamp.green.on {{ background: var(--green); box-shadow: 0 0 16px var(--green); }}
.reason {{ font-size: 17px; margin: 0 0 6px; }}
.health {{ margin: 0; font-weight: 600; }}
.health.ok {{ color: var(--green); }}
.health.bad, .warn {{ color: var(--warn); }}
.scroll {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }}
th {{ color: var(--muted); font-weight: 600; font-size: 13px; }}
.meta {{ color: var(--muted); font-size: 13px; margin-top: 24px; }}
</style>
</head>
<body>
<main>
<h1>Roof lights</h1>
<div class="card">
  <div class="lamps">{lamps}</div>
  <p class="reason">{reason}</p>
  {health}
</div>
<h2>Trackers</h2>
<div class="card scroll"><table>
  <tr><th>Tracker</th><th>Last schedule</th><th>Passes</th><th>Last error</th></tr>
  {tracker_rows}
</table></div>
<h2>Upcoming red windows</h2>
<div class="card scroll"><table>
  <tr><th>Red from</th><th>Until</th><th>Passes</th></tr>
  {upcoming_rows}
</table></div>
<p class="meta">Running since {started} &middot; last check {last_loop} &middot; page generated {now}
&middot; <a href="/status.json">JSON</a> &middot; <a href="/health">health</a></p>
</main>
</body>
</html>
"""
