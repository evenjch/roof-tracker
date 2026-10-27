# Roof lights

Red/yellow/green lights on the roof that follow the ground station trackers:

- **Red**: a satellite pass is in progress on the S-band or UHF tracker (from 1 min before AOS to 1 min after LOS).
- **Green**: clear.
- **Yellow**: unknown. Either no tracker has answered for 15 minutes, or the service is stopped.

The service runs on the Raspberry Pi under systemd. It starts at boot, restarts itself if it
crashes or hangs, and doesn't depend on anyone's computer being on.

## Checking on it

- Status page: `http://<pi>:8080`. It shows the current light and why, each tracker's last
  successful read and last error, and the upcoming red windows.
- `http://<pi>:8080/?widget` is the same page stripped down for a small browser panel
  (e.g. a Vivaldi web panel): no heading, frames or sideways scrolling.
- `http://<pi>:8080/health` returns `ok` (HTTP 200), or the problems (HTTP 503).
- `http://<pi>:8080/status.json` returns the same data as JSON.
- Over SSH: `systemctl status roof-lights`, `journalctl -u roof-lights -f`.

## Install / update (on the Pi)

```sh
./install.sh
```

This creates `venv/`, installs `requirements.txt`, runs the tests, and installs and starts the
systemd service. It also opens port 8080 in ufw. Run it again after changing the code or `config.py`.
Stop any old copy of the scheduler first, so two programs aren't driving the relays.

## How it works

Every minute, `roof_lights.main` reads `/api/v1/tracker/schedule` from each tracker. This is the
same JSON the tracker web page's pass table is built from. It merges every pass, padded by the
margin, into red windows and sets the lights. It also wakes up exactly at window edges, so the
lights switch on time. If one tracker is down, the other's schedule is used. If both are down,
the last schedule received is still used for 15 minutes.

| File | What it does |
|---|---|
| `roof_lights/config.py` | All settings: tracker URLs, margin, poll interval, I2C addresses, port |
| `roof_lights/trackers.py` | Fetches and parses a tracker's schedule |
| `roof_lights/timeline.py` | Merges passes into windows and decides the light |
| `roof_lights/lights.py` | Relay board and `lightstate.json` |
| `roof_lights/status.py` | Status page |
| `roof_lights/main.py` | The main loop |

## Useful commands

```sh
venv/bin/python -m roof_lights.main --once      # one check against the live trackers, prints the windows
venv/bin/python -m roof_lights.main --dry-run   # run without touching the relays (stop the service first, or use --port)
venv/bin/python -m roof_lights.lights red       # set the lights by hand (red|yellow|green|off)
venv/bin/python -m unittest                     # tests; work on any computer with Python 3.7+ and requests
```
