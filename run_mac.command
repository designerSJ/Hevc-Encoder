#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1

if ! command -v ffmpeg >/dev/null 2>&1 || ! python3 -c "import tkinter" >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
        echo "[Setup] Installing ffmpeg and python-tk via Homebrew..."
        brew install ffmpeg python-tk
    fi
fi

if ! python3 -c "import tkinterdnd2" >/dev/null 2>&1; then
    python3 -m pip install --upgrade --break-system-packages "tkinterdnd2>=0.4.2" 2>/dev/null || python3 -m pip install --upgrade "tkinterdnd2>=0.4.2" 2>/dev/null || true
fi

exec python3 "$(dirname "$0")/hevc_encoder_gui.py" "$@"
