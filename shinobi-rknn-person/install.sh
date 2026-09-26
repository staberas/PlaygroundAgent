#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${VENV:-$HERE/.venv}"

if ! dpkg -s python3-venv >/dev/null 2>&1; then
  echo "Install python3-venv first: sudo apt install -y python3-venv"
  exit 1
fi

python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/pip" install -r "$HERE/requirements.txt"

echo
echo "Checking system-provided RKNNLite and OpenCV..."
"$VENV/bin/python" - <<'PY'
import cv2
from rknnlite.api import RKNNLite
print("OpenCV:", cv2.__version__)
print("RKNNLite: OK")
PY

if [ ! -f "$HERE/config.json" ]; then
  cp "$HERE/config.example.json" "$HERE/config.json"
  echo
  echo "Created $HERE/config.json"
  echo "Edit host, key, and model_path before starting."
fi

echo
echo "Install complete."
echo "Self-test example:"
echo "  $VENV/bin/python $HERE/plugin.py --config $HERE/config.json --self-test /path/to/test.jpg"
echo
echo "Run plugin:"
echo "  $VENV/bin/python $HERE/plugin.py --config $HERE/config.json"
