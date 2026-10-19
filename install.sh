#!/usr/bin/env bash
# Install or update the roof lights service on the Raspberry Pi.
# Run from the project folder as your normal user (not root): ./install.sh
set -euo pipefail

cd "$(dirname "$0")"
DIR="$(pwd)"
RUN_AS="$(whoami)"
PORT=8080

echo "Installing roof-lights from $DIR, running as $RUN_AS"

python3 -m venv --clear venv
venv/bin/pip install --quiet --upgrade pip
venv/bin/pip install --quiet -r requirements.txt

echo "Running tests"
venv/bin/python -m unittest --quiet

sed -e "s|@DIR@|$DIR|g" -e "s|@USER@|$RUN_AS|g" roof-lights.service \
    | sudo tee /etc/systemd/system/roof-lights.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable roof-lights
sudo systemctl restart roof-lights

if command -v ufw > /dev/null; then
    sudo ufw allow "$PORT/tcp"
fi

sleep 3
systemctl --no-pager status roof-lights || true
echo
echo "Status page: http://$(hostname -I | awk '{print $1}'):$PORT"
echo "Logs:        journalctl -u roof-lights -f"
