#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1

# Auto-install python, tk, and ffmpeg if missing on CachyOS / Arch / Debian / Fedora
if ! command -v python3 >/dev/null 2>&1 || ! command -v ffmpeg >/dev/null 2>&1 || ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "[Setup] Installing required packages (python, tk, ffmpeg)..."
    if command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --needed --noconfirm python tk ffmpeg
    elif command -v apt >/dev/null 2>&1; then
        sudo apt update && sudo apt install -y python3 python3-tk ffmpeg
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-tkinter ffmpeg
    fi
fi

if ! python3 -c "import tkinterdnd2" >/dev/null 2>&1; then
    python3 -m pip install --upgrade --break-system-packages "tkinterdnd2>=0.4.2" 2>/dev/null || python3 -m pip install --upgrade "tkinterdnd2>=0.4.2" 2>/dev/null || true
fi

exec python3 "$(dirname "$0")/hevc_encoder_gui.py" "$@"
