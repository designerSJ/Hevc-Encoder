# HEVC 10-Bit Studio

A desktop video batch encoder for converting videos to HEVC (H.265), with a focus on smaller files and preserving image quality. It uses FFmpeg and can detect available hardware encoders, or use the CPU-based x265 encoder.

## Features

- Add video files or folders, including folders scanned recursively.
- Queue work by using the file picker, dragging files into the window, or pasting copied file paths with **Ctrl+V**. Drag and drop requires the optional `tkinterdnd2` package.
- Preview settings with a 30-second sample encode before starting a batch.
- Choose an available encoder and adjust quality, preset, 10-bit output, bitrate cap, and hardware decoding settings.
- Copy audio or convert it to AAC or Opus. Preserve subtitle tracks when using MKV output.
- Choose MKV or MP4 output, a destination folder, and an output filename suffix.
- See per-file progress and estimated space saved. Skip existing outputs and keep the original when an encode is larger.
- Settings are saved locally in `hevc_studio_config.json` beside the app.

## Requirements

- Python 3 with Tkinter
- FFmpeg and FFprobe, with an HEVC encoder available
- Optional: `tkinterdnd2` for native drag and drop (file buttons and Ctrl+V still work without it)

The launchers try to install missing dependencies where supported. This may download FFmpeg or use your system package manager; Linux package installation may ask for your password. Hardware encoding depends on your GPU, drivers, and FFmpeg build. CPU encoding with x265 is available as an alternative.

## Run

Download or clone this repository, then use the launcher for your platform from the app folder:

| Platform | Launcher |
| --- | --- |
| Windows | `run_windows.bat` |
| macOS | `run_mac.command` |
| Linux | `run_linux.sh` |

On Windows, `install.cmd` installs the optional drag-and-drop package and then starts the app. If macOS blocks the launcher, allow it to run or start it from Terminal:

```sh
./run_mac.command
```

On Linux, make the launcher executable if needed, then run:

```sh
chmod +x run_linux.sh
./run_linux.sh
```

You can also start the GUI directly with Python:

```sh
python hevc_encoder_gui.py
```

## Basic use

1. Add videos or folders to the queue.
2. Set the output location and filename format.
3. Choose an encoder and quality settings. Use **Auto** to select a detected hardware encoder when possible.
4. Optionally select a video and run **30s Sample Test** to review the result.
5. Start the batch. You can skip the current file or cancel processing from the progress controls.

The default output uses the `.mkv` container and appends `_hevc10` to the input filename. Review the output and settings before enabling **Shutdown PC when finished**.
