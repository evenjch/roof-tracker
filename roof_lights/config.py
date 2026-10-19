"""All settings in one place. Edit this file, then `sudo systemctl restart roof-lights`."""
import os
from datetime import timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

# Trackers to follow: display name -> base URL. Both run the Satlab tracker
# software, which serves the pass schedule as JSON (this is what the web page's
# pass table is built from).
TRACKERS = {
    "S-band": "http://sband-mcs.ies.ntnu.no:8000",
    "UHF": "http://uhf-track.ies.ntnu.no:8000",
}
SCHEDULE_PATH = "/api/v1/tracker/schedule?limit=20"
HTTP_TIMEOUT_S = 10

# How often to re-read the schedules.
POLL_INTERVAL = timedelta(seconds=60)
# Lights go red this long before AOS and stay red this long after LOS.
MARGIN = timedelta(seconds=60)
# If no tracker has answered for this long, show yellow (unless inside a known pass).
STALE_AFTER = timedelta(minutes=15)
# The schedule marks each pass "full", "partial" or "none" (not tracked, e.g. because
# another satellite has priority). Set to True to keep the lights green for "none" passes.
IGNORE_UNTRACKED = False

# I2C relay board.
I2C_BUS = 1
I2C_ADDRESS = 0x10
RELAY_CHANNELS = {"red": 0x02, "yellow": 0x03, "green": 0x04}
RELAY_ON = 0x01  # the value the old ledcontroller.py has been writing successfully
RELAY_OFF = 0x00

# Light state for the web visualisation.
STATE_FILE = Path(os.environ.get("ROOF_LIGHTS_STATE_FILE", str(PROJECT_DIR / "lightstate.json")))

# Status page: http://<pi>:8080
STATUS_PORT = int(os.environ.get("ROOF_LIGHTS_PORT", "8080"))
# /health reports a problem if the main loop hasn't run for this long.
MAX_LOOP_AGE = timedelta(minutes=3)
