#!/usr/bin/env bash
# Build a standalone, zero-dependency dist/hwfetch-live with PyInstaller.
# Creates/uses an isolated .venv so the system Python is never touched.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
    echo "==> creating build venv (.venv)"
    python3 -m venv .venv
    .venv/bin/pip install --quiet -e '.[dev,build]'
fi

echo "==> running tests"
.venv/bin/pytest -q tests/

echo "==> building standalone binary"
.venv/bin/pyinstaller --noconfirm --clean packaging/hwfetch-live.spec

echo "==> done: $(pwd)/dist/hwfetch-live"
