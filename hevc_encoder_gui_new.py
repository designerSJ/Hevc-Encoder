#!/usr/bin/env python3
"""
HEVC 10-Bit Visually Lossless Studio (Fixed Drag & Drop + Ctrl+V Paste + Live Queue)
Self-contained cross-platform GUI for Windows, Linux (CachyOS/Arch/Ubuntu/Fedora), and macOS.
"""

import importlib
import json
import os
import platform
import queue
import shutil
import site
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# ==============================================================================
# 1. AUTOMATIC DEPENDENCY BOOTSTRAPPER (TKINTER + FFMPEG + TKINTERDND2)
# ==============================================================================

OS_SYSTEM = platform.system().lower()
SCRIPT_DIR = Path(__file__).resolve().parent
BIN_DIR = SCRIPT_DIR / "bin"
CONFIG_FILE = SCRIPT_DIR / "hevc_studio_config.json"

if BIN_DIR.exists():
    os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ.get("PATH", "")


def enable_hidpi():
    """Enables High-DPI scaling on Windows so UI stays crisp and proportional."""
    if OS_SYSTEM == "windows":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def get_screen_work_area():
    """Returns (usable_width, usable_height, work_x, work_y) excluding taskbar/dock where possible."""
    if OS_SYSTEM == "windows":
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            rect = RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                return w, h, rect.left, rect.top
        except Exception:
            pass
    return None


def is_cachy_or_arch() -> bool:
    if OS_SYSTEM != "linux":
        return False
    os_release = Path("/etc/os-release")
    if os_release.exists():
        content = os_release.read_text(errors="ignore").lower()
        return any(k in content for k in ("cachyos", "arch", "manjaro", "endeavouros"))
    return shutil.which("pacman") is not None


def download_windows_ffmpeg():
    """Downloads portable FFmpeg + FFprobe essentials build into ./bin on Windows if not installed."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = BIN_DIR / "ffmpeg.zip"
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    print(f"[Bootstrap] Downloading portable FFmpeg from {url} ...")
    try:
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                if member.endswith(("ffmpeg.exe", "ffprobe.exe")):
                    filename = Path(member).name
                    with zf.open(member) as source, open(BIN_DIR / filename, "wb") as target:
                        shutil.copyfileobj(source, target)
        zip_path.unlink(missing_ok=True)
        os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ.get("PATH", "")
        print("[Bootstrap] Portable FFmpeg installed successfully into ./bin!")
    except Exception as e:
        print(f"[Bootstrap] Failed to auto-download FFmpeg: {e}")


def get_python_cli_executable() -> str:
    """Returns python.exe instead of pythonw.exe on Windows so pip subprocesses work reliably."""
    exe = Path(sys.executable)
    if OS_SYSTEM == "windows" and exe.name.lower() == "pythonw.exe":
        alt = exe.with_name("python.exe")
        if alt.exists():
            return str(alt)
    return sys.executable


def refresh_site_packages():
    """Refreshes sys.path after dynamically installing packages via pip."""
    importlib.invalidate_caches()
    try:
        user_site = site.getusersitepackages()
        if user_site and user_site not in sys.path:
            sys.path.insert(0, user_site)
    except Exception:
        pass
    try:
        for sp in site.getsitepackages():
            if sp not in sys.path:
                sys.path.insert(0, sp)
    except Exception:
        pass


def _safe_import_tkinterdnd2() -> bool:
    """Safely imports tkinterdnd2, applying a compatibility shim for Python 3.13+."""
    # Python 3.13+ compatibility: Python 3.13 removed tkinter.tix (PEP 594).
    # Older tkinterdnd2 versions (<0.4.0) have 'from tkinter import tix', which crashes on 3.13+.
    # Shimming a dummy module into sys.modules prevents this crash even on legacy installations.
    if "tkinter.tix" not in sys.modules:
        try:
            import tkinter.tix  # noqa: F401
        except ImportError:
            import types
            sys.modules["tkinter.tix"] = types.ModuleType("tkinter.tix")

    refresh_site_packages()
    import tkinterdnd2  # noqa: F401
    return True


def ensure_tkinterdnd2() -> bool:
    """Ensures tkinterdnd2 is installed and importable for native Drag-and-Drop support."""
    try:
        if _safe_import_tkinterdnd2():
            return True
    except Exception:
        pass

    print("[Bootstrap] Installing / upgrading tkinterdnd2 for Drag-and-Drop support...")
    py_exe = get_python_cli_executable()
    cmds = [
        [py_exe, "-m", "pip", "install", "--upgrade", "tkinterdnd2>=0.4.2"],
        [py_exe, "-m", "pip", "install", "--upgrade", "tkinterdnd2"],
        [py_exe, "-m", "pip", "install", "--user", "--upgrade", "tkinterdnd2>=0.4.2"],
        [py_exe, "-m", "pip", "install", "--user", "--break-system-packages", "--upgrade", "tkinterdnd2"],
    ]
    for cmd in cmds:
        try:
            kwargs = {"timeout": 120}
            if OS_SYSTEM == "windows":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            res = subprocess.run(cmd, **kwargs)
            if res.returncode == 0:
                try:
                    if _safe_import_tkinterdnd2():
                        print("[Bootstrap] tkinterdnd2 installed and verified successfully!")
                        return True
                except Exception:
                    # Restart process once if site-packages cache requires a fresh process
                    if "--dnd-restarted" not in sys.argv:
                        clean_args = [a for a in sys.argv if a != "--dnd-restarted"]
                        subprocess.Popen([sys.executable] + clean_args + ["--dnd-restarted"])
                        sys.exit(0)
        except Exception:
            pass
    return False


def ensure_system_dependencies():
    """Ensures tkinter, ffmpeg, and ffprobe are available across Windows, macOS, and Linux."""
    missing_tk = False
    try:
        import tkinter  # noqa: F401
    except ImportError:
        missing_tk = True

    missing_ffmpeg = shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None

    if missing_tk or missing_ffmpeg:
        print("[Bootstrap] Checking and installing missing system dependencies...")

        if OS_SYSTEM == "linux":
            if is_cachy_or_arch():
                pkgs = ([] if not missing_tk else ["tk"]) + ([] if not missing_ffmpeg else ["ffmpeg"])
                if pkgs:
                    subprocess.run(["sudo", "pacman", "-S", "--needed", "--noconfirm", *pkgs], check=False)
            elif shutil.which("apt"):
                pkgs = ([] if not missing_tk else ["python3-tk"]) + ([] if not missing_ffmpeg else ["ffmpeg"])
                if pkgs:
                    subprocess.run(["sudo", "apt", "update"], check=False)
                    subprocess.run(["sudo", "apt", "install", "-y", *pkgs], check=False)
            elif shutil.which("dnf"):
                pkgs = ([] if not missing_tk else ["python3-tkinter"]) + ([] if not missing_ffmpeg else ["ffmpeg"])
                if pkgs:
                    subprocess.run(["sudo", "dnf", "install", "-y", *pkgs], check=False)

        elif OS_SYSTEM == "darwin":
            if shutil.which("brew"):
                if missing_tk:
                    subprocess.run(["brew", "install", "python-tk"], check=False)
                if missing_ffmpeg:
                    subprocess.run(["brew", "install", "ffmpeg"], check=False)

        elif OS_SYSTEM == "windows":
            if missing_ffmpeg:
                if shutil.which("winget"):
                    subprocess.run(
                        ["winget", "install", "--id=Gyan.FFmpeg", "-e", "--accept-source-agreements", "--accept-package-agreements"],
                        check=False,
                    )
                if shutil.which("ffmpeg") is None:
                    download_windows_ffmpeg()

        if missing_tk:
            os.execv(sys.executable, [sys.executable] + sys.argv)


enable_hidpi()
ensure_system_dependencies()
HAS_DND = ensure_tkinterdnd2()

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

if HAS_DND:
    try:
        _safe_import_tkinterdnd2()
        from tkinterdnd2 import DND_FILES, TkinterDnD
    except Exception:
        HAS_DND = False

# ==============================================================================
# 2. DEFAULT SETTINGS & PRESET DEFINITIONS
# ==============================================================================

PRESET_LABELS = {
    "p7": "p7 — Max Quality (NVENC Slowest, ~250+ FPS)",
    "p6": "p6 — Very High Quality (NVENC Slower, ~300+ FPS)",
    "p5": "p5 — Balanced Quality (NVENC Slow, ~380+ FPS)",
    "p4": "p4 — Fast / Streaming (NVENC Medium, ~450+ FPS)",
    "slow": "slow — CPU High Compression (x265 Slow)",
    "medium": "medium — CPU Standard (x265 Medium)",
    "fast": "fast — CPU Fast (x265 Fast)",
}
LABEL_TO_PRESET = {v: k for k, v in PRESET_LABELS.items()}

RESOLUTION_LABELS = {
    "original": "Original (Keep Source)",
    "2160p": "2160p — 4K UHD (3840x2160)",
    "1440p": "1440p — 2K QHD (2560x1440)",
    "1080p": "1080p — Full HD (1920x1080)",
    "720p": "720p — HD (1280x720)",
    "480p": "480p — SD (854x480)",
    "360p": "360p — Low (640x360)",
    "custom": "Custom (W × H)",
}
LABEL_TO_RESOLUTION = {v: k for k, v in RESOLUTION_LABELS.items()}
RESOLUTION_DIMS = {
    "2160p": (3840, 2160),
    "1440p": (2560, 1440),
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "480p": (854, 480),
    "360p": (640, 360),
}

DEFAULT_SETTINGS = {
    "encoder": "auto",               # auto, hevc_nvenc, hevc_videotoolbox, hevc_vaapi, hevc_amf, hevc_qsv, libx265
    "cq": 23,                        # Visually lossless sweet spot for 4.5 Mbps broadcast H.264
    "preset": "p7",                  # p7 (slowest/best quality for NVENC)
    "resolution": "original",        # original, 2160p, 1440p, 1080p, 720p, 480p, 360p, custom
    "custom_width": 0,               # Custom output width (0 = auto aspect ratio)
    "custom_height": 0,              # Custom output height (0 = auto aspect ratio)
    "ten_bit": True,                 # Main10 / p010le to prevent banding and save ~5% bitrate
    "gop": 250,                      # 10s GOP at 25fps (fixes wasteful N=25 1-sec broadcast GOP)
    "bframes": 4,                    # 4 B-frames (fixes M=1 broadcast stream)
    "b_ref_mode": "middle",          # B-frames as reference
    "lookahead": 32,                 # 32 frames lookahead
    "spatial_aq": True,              # Protects flat walls & subtle gradients
    "aq_strength": 10,               # Tuned for fine fabrics/checkered textures (1-15)
    "temporal_aq": True,             # Protects moving foreground details
    "multipass": "fullres",          # disabled, qres, fullres
    "maxrate_cap_enabled": True,     # Prevents already-low-bitrate (2.4 Mbps) files from growing
    "maxrate_kbps": 2800,            # 2800k cap + 5600k bufsize
    "audio_mode": "copy",            # copy (100% lossless + sync delay preserved), aac_192k, opus_128k
    "keep_subtitles": True,          # -c:s copy
    "output_mode": "same_dir",       # same_dir or custom_dir
    "custom_output_dir": "",
    "preserve_subfolders": True,     # Mirror subfolder tree when using custom_dir
    "suffix": "_hevc10",             # Appended to output filename
    "container": ".mkv",             # .mkv or .mp4
    "recursive_scan": True,          # Scan subfolders when adding/dropping a directory
    "skip_existing": True,           # Skip if output file already exists
    "size_guard": True,              # Discard encoded file if larger than source file
    "hw_decode": True,               # Use CUDA hardware decoding when on NVENC
    "shutdown_on_finish": False,     # Automatically shut down PC 5s after batch completes
    "extra_ffmpeg_args": "",         # Custom user flags
}

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".ts", ".m4v", ".mov", ".avi", ".webm", ".flv", ".m2ts"}


# ==============================================================================
# 3. GPU & HARDWARE ENCODER AUTO-DETECTION (RUNS ASYNC IN BACKGROUND)
# ==============================================================================

def test_encoder_works(encoder_name: str) -> bool:
    """Runs a 1-frame null encode to verify hardware encoder initialization."""
    if not shutil.which("ffmpeg"):
        return False
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if encoder_name == "hevc_vaapi":
        render_node = "/dev/dri/renderD128"
        if not Path(render_node).exists():
            return False
        cmd += [
            "-vaapi_device", render_node,
            "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.04",
            "-vf", "format=nv12,hwupload",
            "-c:v", "hevc_vaapi", "-f", "null", "-",
        ]
    else:
        cmd += [
            "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.04",
            "-frames:v", "1", "-c:v", encoder_name, "-f", "null", "-",
        ]
    try:
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "timeout": 4}
        if OS_SYSTEM == "windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        res = subprocess.run(cmd, **kwargs)
        return res.returncode == 0
    except Exception:
        return False


def detect_gpu_and_encoders():
    """Detects GPU model and tests hardware HEVC encoders."""
    gpu_name = "Generic GPU / CPU"
    if shutil.which("nvidia-smi"):
        try:
            kwargs = {"stderr": subprocess.DEVNULL, "text": True, "timeout": 3}
            if OS_SYSTEM == "windows":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                **kwargs,
            ).strip()
            if out:
                gpu_name = out.splitlines()[0].strip()
        except Exception:
            pass
    elif OS_SYSTEM == "darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True, timeout=2).strip()
            if out:
                gpu_name = f"{out} (VideoToolbox)"
        except Exception:
            gpu_name = "Apple Silicon / macOS GPU"
    elif OS_SYSTEM == "linux" and shutil.which("lspci"):
        try:
            out = subprocess.check_output(["lspci"], text=True, timeout=3)
            for line in out.splitlines():
                if "VGA" in line or "3D controller" in line:
                    gpu_name = line.split(":", 2)[-1].strip()
                    break
        except Exception:
            pass

    candidates = [
        ("hevc_nvenc", "NVIDIA NVENC HEVC"),
        ("hevc_videotoolbox", "Apple VideoToolbox HEVC"),
        ("hevc_qsv", "Intel QSV HEVC"),
        ("hevc_amf", "AMD AMF HEVC"),
        ("hevc_vaapi", "Linux VAAPI HEVC"),
        ("libx265", "CPU x265 (Software Fallback)"),
    ]

    available = []
    for enc, label in candidates:
        if test_encoder_works(enc):
            available.append((enc, label))

    if not available:
        available.append(("libx265", "CPU x265 (Software Fallback)"))

    best_encoder = available[0][0]
    return gpu_name, best_encoder, available


# ==============================================================================
# 4. CROSS-PLATFORM DRAG-AND-DROP & CLIPBOARD PATH PARSER
# ==============================================================================

def clean_single_dropped_token(token: str) -> Path | None:
    """Converts raw OS drop strings (file:// URIs, Tcl braces, escaped spaces) into a valid Path."""
    s = token.strip()
    if not s or s.startswith("#"):
        return None

    # Strip surrounding Tcl braces or quotes if present (repeated if nested)
    while len(s) >= 2 and (
        (s.startswith("{") and s.endswith("}"))
        or (s.startswith('"') and s.endswith('"'))
        or (s.startswith("'") and s.endswith("'"))
    ):
        s = s[1:-1].strip()

    # Handle file:// URIs from Linux (Dolphin/Nautilus), macOS, and Windows
    if s.startswith("file://"):
        parsed = urllib.parse.urlparse(s)
        path_str = urllib.parse.unquote(parsed.path)
        # On Windows, file:///D:/Videos produces /D:/Videos
        if OS_SYSTEM == "windows" and len(path_str) >= 3 and path_str[0] == "/" and path_str[2] == ":":
            path_str = path_str[1:]
        elif parsed.netloc and parsed.netloc != "localhost":
            path_str = f"//{parsed.netloc}{path_str}"
        p = Path(path_str)
        if p.exists():
            return p

    p = Path(s)
    if p.exists():
        return p

    # Try URL-unquoting directly in case %20 was passed without file://
    unquoted = Path(urllib.parse.unquote(s))
    if unquoted.exists():
        return unquoted

    # Try unescaping backslash-escaped spaces (\ ) from Linux X11 drag-and-drop
    unescaped = Path(s.replace("\\ ", " "))
    if unescaped.exists():
        return unescaped

    return None


def parse_dropped_data(tk_root: tk.Tk, raw_data: str) -> list[Path]:
    """Parses any multi-file drop payload across Windows Explorer, Linux Dolphin/Nautilus, and macOS Finder."""
    if not raw_data:
        return []

    results = []
    seen = set()

    def _add_if_valid(tok: str):
        if not tok:
            return
        p = clean_single_dropped_token(tok)
        if p and p not in seen:
            seen.add(p)
            results.append(p)

    # 1. First split by newlines if it's a URI list (common on Linux/macOS)
    lines = [line.strip() for line in raw_data.splitlines() if line.strip()]
    if len(lines) > 1 or raw_data.strip().startswith("file://"):
        for line in lines:
            _add_if_valid(line)
        if results:
            return results

    # 2. Use Tcl's native splitlist (handles {C:\path with spaces\file1.mkv} {C:\path\file2.mkv})
    try:
        tokens = tk_root.tk.splitlist(raw_data)
        for tok in tokens:
            _add_if_valid(tok)
    except Exception:
        pass

    # 3. If splitlist failed or didn't find all valid paths, use regex tokenization fallback
    if not results:
        import re
        tokens = [m[0] or m[1] or m[2] for m in re.findall(r'\{([^{}]+)\}|"([^"]+)"|(\S+)', raw_data)]
        for tok in tokens:
            _add_if_valid(tok)

    # 4. Fallback: check if the entire raw string is a single unbraced/unquoted path with spaces
    if not results:
        _add_if_valid(raw_data)

    return results


# ==============================================================================
# 5. SCROLLABLE FRAME WIDGET FOR RESPONSIVE SETTINGS PANEL
# ==============================================================================

class ScrollableFrame(ttk.Frame):
    """A responsive vertical scrollable container that adapts to window resizing."""

    def __init__(self, parent, bg_color="#1e1e2e", *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.canvas = tk.Canvas(self, bg=bg_color, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Global mousewheel binding: handles wheel events whenever pointer is over this container or any descendant
        self.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.bind_all("<Button-4>", self._on_mousewheel_linux, add="+")
        self.bind_all("<Button-5>", self._on_mousewheel_linux, add="+")

    def _on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.inner_id, width=event.width)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _is_pointer_over_self(self) -> bool:
        try:
            x, y = self.winfo_pointerxy()
            w = self.winfo_containing(x, y)
            return bool(w and (w == self or str(w).startswith(str(self))))
        except Exception:
            return False

    def _on_mousewheel(self, event):
        if not self._is_pointer_over_self():
            return
        if OS_SYSTEM == "darwin":
            self.canvas.yview_scroll(int(-1 * event.delta), "units")
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_linux(self, event):
        if not self._is_pointer_over_self():
            return
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")


# ==============================================================================
# 6. MAIN RESPONSIVE GUI APPLICATION
# ==============================================================================

class HEVCStudioApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("HEVC 10-Bit Visually Lossless Studio")

        # Responsive window sizing & placement respecting taskbar/work-area
        work_area = get_screen_work_area()
        if work_area:
            work_w, work_h, work_x, work_y = work_area
            w = min(1200, int(work_w * 0.94))
            h = min(780, int(work_h * 0.92))
            x = work_x + max(0, (work_w - w) // 2)
            y = work_y + max(0, (work_h - h - 35) // 2)
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            w = min(1200, int(sw * 0.88))
            h = min(760, int(sh * 0.82))
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h - 40) // 2)

        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(700, 480)

        self.settings = self.load_settings()

        self.gpu_name = "Detecting GPU..."
        self.best_encoder = "hevc_nvenc"
        self.available_encoders = [("hevc_nvenc", "NVIDIA NVENC HEVC"), ("libx265", "CPU x265")]

        # Thread-safe Queue & Dynamic Worker State
        self.queue_lock = threading.Lock()
        self.file_queue = []
        self.queued_paths = set()
        self.ingest_tasks_queue = queue.Queue()
        self.active_ingest_batches = 0

        self.is_encoding = False
        self.current_encoding_id = None
        self.cancel_requested = False
        self.skip_current_requested = False
        self.current_process = None
        self.ui_queue = queue.Queue()

        self._shutdown_timer_id = None
        self._shutdown_seconds_left = 0
        self._shutdown_total_saved = 0

        self.setup_dark_theme()
        self.init_variables()
        self.build_ui()
        self.setup_drag_and_drop_and_paste()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.poll_ui_queue()

        # Start persistent background ingest worker (handles files added/dropped anytime, even mid-encode)
        threading.Thread(target=self._background_ingest_loop, daemon=True).start()
        # Start non-blocking GPU detection
        threading.Thread(target=self._async_init_gpu, daemon=True).start()

    def _async_init_gpu(self):
        gpu_name, best_enc, avail = detect_gpu_and_encoders()
        self.ui_queue.put(("gpu_ready", gpu_name, best_enc, avail))

    # --------------------------------------------------------------------------
    # Drag-and-Drop + Clipboard Paste (Ctrl+V) Setup
    # --------------------------------------------------------------------------
    def _register_widget_dnd_recursive(self, widget):
        """Registers a widget and all its child widgets to accept file drops."""
        try:
            # DND_FILES is the only format we consume. Registering DND_ALL as
            # a second target can make tkdnd reject the registration on some
            # Tk builds, which silently left the entire UI unable to receive drops.
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<DropEnter>>", self.on_drag_enter)
            widget.dnd_bind("<<DropLeave>>", self.on_drag_leave)
            widget.dnd_bind("<<Drop>>", self.on_drop_files)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._register_widget_dnd_recursive(child)

    def setup_drag_and_drop_and_paste(self):
        # Bind Ctrl+V / Command+V globally so users can also copy & paste files from Explorer/Dolphin/Finder
        self.root.bind("<Control-v>", self.paste_files_from_clipboard)
        self.root.bind("<Control-V>", self.paste_files_from_clipboard)
        if OS_SYSTEM == "darwin":
            self.root.bind("<Command-v>", self.paste_files_from_clipboard)

        if HAS_DND:
            self._register_widget_dnd_recursive(self.root)

    def on_drag_enter(self, event):
        self.drop_banner.configure(
            bg="#1d4ed8",
            fg="#ffffff",
            text="⬇  Release Mouse to Drop Videos / Folders into Queue!  ⬇",
        )
        return getattr(event, "action", "copy")

    def on_drag_leave(self, _event=None):
        self._reset_drop_banner()

    def _reset_drop_banner(self):
        if HAS_DND:
            self.drop_banner.configure(
                bg="#26283e",
                fg="#89b4fa",
                text="📥  DRAG & DROP VIDEOS OR FOLDERS HERE ANYTIME  (Or Copy Files & Press Ctrl+V)",
            )
        else:
            self.drop_banner.configure(
                bg="#3b232e",
                fg="#f38ba8",
                text="⚠ Native Drag-and-Drop library missing — Click Here to Auto-Fix, or Press Ctrl+V to Paste Files",
            )

    def on_drop_files(self, event):
        """Handles files and folders dragged and dropped onto the window at any time."""
        self._reset_drop_banner()
        raw_data = getattr(event, "data", "")
        if not raw_data:
            return getattr(event, "action", "copy")
        dropped_paths = parse_dropped_data(self.root, raw_data)
        if dropped_paths:
            self.enqueue_raw_paths(dropped_paths, source_label=f"{len(dropped_paths)} dropped item(s)")
        else:
            self.lbl_status.configure(text=f"Could not read dropped path: {raw_data[:80]}")
        return getattr(event, "action", "copy")

    def paste_files_from_clipboard(self, event=None):
        """Allows pressing Ctrl+V (or clicking Paste Files) after copying files in Explorer/Dolphin/Finder."""
        # Don't intercept Ctrl+V if user is typing inside an Entry box
        if event is not None and isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Spinbox)):
            return

        paths = []
        # 1. Try standard clipboard text / URI list first
        try:
            clip_text = self.root.clipboard_get()
            if clip_text:
                paths = parse_dropped_data(self.root, clip_text)
        except Exception:
            pass

        # 2. On Windows, if files were copied via Explorer (CF_HDROP), query PowerShell FileDropList
        if not paths and OS_SYSTEM == "windows":
            try:
                kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL, "text": True, "timeout": 3}
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Format FileDropList | ForEach-Object { $_.FullName }"],
                    **kwargs,
                )
                for line in res.stdout.splitlines():
                    p = clean_single_dropped_token(line)
                    if p:
                        paths.append(p)
            except Exception:
                pass

        if paths:
            self.enqueue_raw_paths(paths, source_label=f"{len(paths)} pasted item(s)")
        else:
            self.lbl_status.configure(text="Clipboard does not contain valid video files or folders.")

    def repair_dnd_clicked(self, _event=None):
        if HAS_DND:
            self.add_files()
            return
        if messagebox.askyesno("Install Drag-and-Drop", "Install / upgrade 'tkinterdnd2' now and restart the app to enable Drag & Drop?"):
            if ensure_tkinterdnd2():
                clean_args = [arg for arg in sys.argv if arg != "--dnd-restarted"]
                subprocess.Popen([sys.executable] + clean_args)
                self.root.destroy()
                sys.exit(0)
            else:
                messagebox.showerror("Install Failed", "Could not auto-install tkinterdnd2. You can still use '+ Add Files', '+ Add Folder', or Ctrl+V Paste!")

    # --------------------------------------------------------------------------
    # Config Persistence
    # --------------------------------------------------------------------------
    def load_settings(self) -> dict:
        cfg = DEFAULT_SETTINGS.copy()
        if CONFIG_FILE.exists():
            try:
                saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                cfg.update(saved)
            except Exception as e:
                print(f"Could not read config: {e}")
        return cfg

    def save_settings(self, *_):
        preset_key = LABEL_TO_PRESET.get(self.var_preset_label.get(), self.var_preset_label.get())
        if preset_key not in PRESET_LABELS:
            preset_key = "p7"

        res_key = LABEL_TO_RESOLUTION.get(self.var_resolution_label.get(), self.var_resolution_label.get())
        if res_key not in RESOLUTION_LABELS:
            res_key = "original"

        def _parse_dim(val_str: str) -> int:
            s_val = str(val_str).strip()
            if not s_val:
                return 0
            try:
                return max(0, int(s_val))
            except ValueError:
                return 0

        try:
            gop_val = int(self.var_gop.get())
            bf_val = int(self.var_bframes.get())
            la_val = int(self.var_lookahead.get())
            aq_val = int(self.var_aq_strength.get())
            mr_val = int(self.var_maxrate_kbps.get())
        except ValueError:
            return

        data = {
            "encoder": self.var_encoder.get(),
            "cq": int(self.var_cq.get()),
            "preset": preset_key,
            "resolution": res_key,
            "custom_width": _parse_dim(self.var_custom_width.get()),
            "custom_height": _parse_dim(self.var_custom_height.get()),
            "ten_bit": bool(self.var_ten_bit.get()),
            "gop": gop_val,
            "bframes": bf_val,
            "b_ref_mode": self.var_b_ref.get(),
            "lookahead": la_val,
            "spatial_aq": bool(self.var_spatial_aq.get()),
            "aq_strength": aq_val,
            "temporal_aq": bool(self.var_temporal_aq.get()),
            "multipass": self.var_multipass.get(),
            "maxrate_cap_enabled": bool(self.var_maxrate_enabled.get()),
            "maxrate_kbps": mr_val,
            "audio_mode": self.var_audio_mode.get(),
            "keep_subtitles": bool(self.var_keep_subs.get()),
            "output_mode": self.var_output_mode.get(),
            "custom_output_dir": self.var_custom_dir.get().strip(),
            "preserve_subfolders": bool(self.var_preserve_subfolders.get()),
            "suffix": self.var_suffix.get().strip() or "_hevc10",
            "container": self.var_container.get(),
            "recursive_scan": bool(self.var_recursive.get()),
            "skip_existing": bool(self.var_skip_existing.get()),
            "size_guard": bool(self.var_size_guard.get()),
            "hw_decode": bool(self.var_hw_decode.get()),
            "shutdown_on_finish": bool(self.var_shutdown_on_finish.get()),
            "extra_ffmpeg_args": self.var_extra_args.get().strip(),
        }
        self.settings = data
        try:
            CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"Error saving settings: {e}")

    def reset_to_defaults(self):
        if not messagebox.askyesno("Reset Settings", "Reset all encoding settings to the recommended RTX 3060 Visually Lossless defaults?"):
            return
        self.settings = DEFAULT_SETTINGS.copy()
        self.apply_settings_to_vars()
        self._update_custom_res_visibility()
        self.on_cq_change(self.var_cq.get())
        self.save_settings()

    # --------------------------------------------------------------------------
    # Theme & Variables
    # --------------------------------------------------------------------------
    def setup_dark_theme(self):
        self.bg_dark = "#181825"
        self.bg_panel = "#1e1e2e"
        self.bg_input = "#313244"
        self.fg_main = "#cdd6f4"
        self.fg_sub = "#a6adc8"
        self.accent = "#89b4fa"
        self.accent_green = "#a6e3a1"
        self.accent_red = "#f38ba8"

        self.root.configure(bg=self.bg_dark)
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=self.bg_panel, foreground=self.fg_main, font=("Segoe UI", 10))
        style.configure("TFrame", background=self.bg_panel)
        style.configure("Dark.TFrame", background=self.bg_dark)
        style.configure("TPanedwindow", background=self.bg_dark, sashwidth=6, sashpad=2)
        style.configure("TLabelframe", background=self.bg_panel, foreground=self.accent, bordercolor="#45475a")
        style.configure("TLabelframe.Label", background=self.bg_panel, foreground=self.accent, font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=self.bg_panel, foreground=self.fg_main)
        style.configure("Sub.TLabel", background=self.bg_panel, foreground=self.fg_sub, font=("Segoe UI", 9))
        style.configure("Header.TLabel", background=self.bg_dark, foreground=self.accent, font=("Segoe UI", 13, "bold"))
        style.configure("GPU.TLabel", background=self.bg_dark, foreground=self.accent_green, font=("Segoe UI", 10, "bold"))
        style.configure("TCheckbutton", background=self.bg_panel, foreground=self.fg_main)
        style.map("TCheckbutton", background=[("active", self.bg_panel)])
        style.configure("TRadiobutton", background=self.bg_panel, foreground=self.fg_main)
        style.map("TRadiobutton", background=[("active", self.bg_panel)])

        style.configure("TButton", background=self.bg_input, foreground=self.fg_main, borderwidth=1, focusthickness=0, padding=(10, 5))
        style.map("TButton", background=[("active", "#45475a"), ("disabled", "#181825")], foreground=[("disabled", "#585b70")])

        style.configure("Accent.TButton", background="#2563eb", foreground="#ffffff", font=("Segoe UI", 10, "bold"), padding=(14, 6))
        style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("disabled", "#313244")])

        style.configure("Danger.TButton", background="#dc2626", foreground="#ffffff", font=("Segoe UI", 10, "bold"), padding=(12, 6))
        style.map("Danger.TButton", background=[("active", "#b91c1c"), ("disabled", "#313244")])

        style.configure("TEntry", fieldbackground=self.bg_input, foreground=self.fg_main, insertcolor=self.fg_main)
        style.configure("TSpinbox", fieldbackground=self.bg_input, foreground=self.fg_main, arrowsize=12)
        style.configure("TCombobox", fieldbackground=self.bg_input, foreground=self.fg_main, selectbackground=self.bg_input)
        style.map("TCombobox", fieldbackground=[("readonly", self.bg_input)], foreground=[("readonly", self.fg_main)])

        style.configure("Treeview", background="#11111b", fieldbackground="#11111b", foreground=self.fg_main, rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background=self.bg_input, foreground=self.accent, font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#3b82f6")], foreground=[("selected", "#ffffff")])

        style.configure("Horizontal.TProgressbar", troughcolor="#11111b", background="#22c55e", bordercolor="#11111b", lightcolor="#22c55e", darkcolor="#22c55e")

    def init_variables(self):
        self.var_encoder = tk.StringVar()
        self.var_cq = tk.IntVar()
        self.var_preset_label = tk.StringVar()
        self.var_resolution_label = tk.StringVar()
        self.var_custom_width = tk.StringVar()
        self.var_custom_height = tk.StringVar()
        self.var_ten_bit = tk.BooleanVar()
        self.var_gop = tk.IntVar()
        self.var_bframes = tk.IntVar()
        self.var_b_ref = tk.StringVar()
        self.var_lookahead = tk.IntVar()
        self.var_spatial_aq = tk.BooleanVar()
        self.var_aq_strength = tk.IntVar()
        self.var_temporal_aq = tk.BooleanVar()
        self.var_multipass = tk.StringVar()
        self.var_maxrate_enabled = tk.BooleanVar()
        self.var_maxrate_kbps = tk.IntVar()
        self.var_audio_mode = tk.StringVar()
        self.var_keep_subs = tk.BooleanVar()
        self.var_output_mode = tk.StringVar()
        self.var_custom_dir = tk.StringVar()
        self.var_preserve_subfolders = tk.BooleanVar()
        self.var_suffix = tk.StringVar()
        self.var_container = tk.StringVar()
        self.var_recursive = tk.BooleanVar()
        self.var_skip_existing = tk.BooleanVar()
        self.var_size_guard = tk.BooleanVar()
        self.var_hw_decode = tk.BooleanVar()
        self.var_shutdown_on_finish = tk.BooleanVar()
        self.var_extra_args = tk.StringVar()

        self.apply_settings_to_vars()

    def apply_settings_to_vars(self):
        s = self.settings
        self.var_encoder.set(s.get("encoder", "auto"))
        self.var_cq.set(s.get("cq", 23))
        preset_code = s.get("preset", "p7")
        self.var_preset_label.set(PRESET_LABELS.get(preset_code, PRESET_LABELS["p7"]))
        res_code = s.get("resolution", "original")
        self.var_resolution_label.set(RESOLUTION_LABELS.get(res_code, RESOLUTION_LABELS["original"]))
        self.var_custom_width.set(str(s.get("custom_width", 0)))
        self.var_custom_height.set(str(s.get("custom_height", 0)))
        self.var_ten_bit.set(s.get("ten_bit", True))
        self.var_gop.set(s.get("gop", 250))
        self.var_bframes.set(s.get("bframes", 4))
        self.var_b_ref.set(s.get("b_ref_mode", "middle"))
        self.var_lookahead.set(s.get("lookahead", 32))
        self.var_spatial_aq.set(s.get("spatial_aq", True))
        self.var_aq_strength.set(s.get("aq_strength", 10))
        self.var_temporal_aq.set(s.get("temporal_aq", True))
        self.var_multipass.set(s.get("multipass", "fullres"))
        self.var_maxrate_enabled.set(s.get("maxrate_cap_enabled", True))
        self.var_maxrate_kbps.set(s.get("maxrate_kbps", 2800))
        self.var_audio_mode.set(s.get("audio_mode", "copy"))
        self.var_keep_subs.set(s.get("keep_subtitles", True))
        self.var_output_mode.set(s.get("output_mode", "same_dir"))
        self.var_custom_dir.set(s.get("custom_output_dir", ""))
        self.var_preserve_subfolders.set(s.get("preserve_subfolders", True))
        self.var_suffix.set(s.get("suffix", "_hevc10"))
        self.var_container.set(s.get("container", ".mkv"))
        self.var_recursive.set(s.get("recursive_scan", True))
        self.var_skip_existing.set(s.get("skip_existing", True))
        self.var_size_guard.set(s.get("size_guard", True))
        self.var_hw_decode.set(s.get("hw_decode", True))
        self.var_shutdown_on_finish.set(s.get("shutdown_on_finish", False))
        self.var_extra_args.set(s.get("extra_ffmpeg_args", ""))

    # --------------------------------------------------------------------------
    # Responsive UI Construction
    # --------------------------------------------------------------------------
    def build_ui(self):
        # 1. Top Header Bar
        header = ttk.Frame(self.root, style="Dark.TFrame", padding=(14, 8))
        header.pack(side="top", fill="x")
        ttk.Label(header, text="HEVC 10-Bit Visually Lossless Studio", style="Header.TLabel").pack(side="left")
        self.lbl_gpu = ttk.Label(
            header,
            text="Detecting GPU & Hardware Encoders...",
            style="GPU.TLabel",
        )
        self.lbl_gpu.pack(side="right")

        # 2. BOTTOM BAR: Progress & Action Controls
        # Packed FIRST with side="bottom" so that the controls bar is ALWAYS fully reserved
        # at the bottom of the window and NEVER gets clipped or pushed off-screen!
        self.bottom_frame = ttk.LabelFrame(self.root, text="4. Live Encoding Progress & Controls", padding=(10, 8))
        self.bottom_frame.pack(side="bottom", fill="x", padx=10, pady=(2, 8))
        self.bottom_frame.columnconfigure(0, weight=1)

        self.info_frame = ttk.Frame(self.bottom_frame)
        self.info_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.info_frame.columnconfigure(0, weight=1)

        self.lbl_status = ttk.Label(
            self.info_frame,
            text="Ready. Drag & drop videos/folders, press Ctrl+V, or use the buttons above.",
            font=("Segoe UI", 10, "bold"),
        )
        self.lbl_metrics = ttk.Label(
            self.info_frame,
            text="Speed: --  |  FPS: --  |  ETA: --  |  Total Saved: 0.0 MB",
            foreground=self.accent,
        )

        self.prog_file = ttk.Progressbar(self.bottom_frame, orient="horizontal", mode="determinate", maximum=100)
        self.prog_file.grid(row=1, column=0, sticky="ew", pady=4)

        self.ctrl_row = ttk.Frame(self.bottom_frame)
        self.ctrl_row.grid(row=2, column=0, sticky="ew", pady=(4, 0))

        self.btn_start = ttk.Button(self.ctrl_row, text="▶ Start Batch Encode", style="Accent.TButton", command=lambda: self.start_encoding(sample_mode=False))
        self.btn_sample = ttk.Button(self.ctrl_row, text="⚡ 30s Sample Test (Selected File)", command=lambda: self.start_encoding(sample_mode=True))
        self.btn_skip = ttk.Button(self.ctrl_row, text="⏭ Skip Current File", state="disabled", command=self.skip_current)
        self.btn_cancel = ttk.Button(self.ctrl_row, text="⏹ Stop / Cancel", style="Danger.TButton", state="disabled", command=self.cancel_encoding)
        self.chk_shutdown = ttk.Checkbutton(
            self.ctrl_row,
            text="Shutdown PC when finished",
            variable=self.var_shutdown_on_finish,
            command=self.on_shutdown_toggle,
        )

        self._last_bottom_mode = None
        self.bottom_frame.bind("<Configure>", self._on_bottom_resize)

        # 3. Resizable Middle PanedWindow (Fills all remaining vertical middle space)
        self.paned = ttk.PanedWindow(self.root, orient="horizontal")
        self.paned.pack(side="top", fill="both", expand=True, padx=10, pady=(2, 4))

        # LEFT PANE: Video Queue + Output Location
        left_pane = ttk.Frame(self.paned, style="Dark.TFrame")
        left_pane.rowconfigure(0, weight=1)
        left_pane.columnconfigure(0, weight=1)

        dnd_status = "Drag & Drop: ACTIVE ✓" if HAS_DND else "Use Buttons or Ctrl+V Paste"
        self.q_frame = ttk.LabelFrame(left_pane, text=f"1. Live Video Queue ({dnd_status})", padding=8)
        self.q_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        self.q_frame.rowconfigure(2, weight=1)
        self.q_frame.columnconfigure(0, weight=1)

        self.btn_bar = ttk.Frame(self.q_frame)
        self.btn_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.btn_add_files = ttk.Button(self.btn_bar, text="+ Add Files", command=self.add_files)
        self.btn_add_folder = ttk.Button(self.btn_bar, text="+ Add Folder", command=self.add_folder)
        self.btn_paste = ttk.Button(self.btn_bar, text="📋 Paste (Ctrl+V)", command=self.paste_files_from_clipboard)
        self.chk_recursive = ttk.Checkbutton(self.btn_bar, text="Subfolders", variable=self.var_recursive, command=self.save_settings)
        self.btn_clear = ttk.Button(self.btn_bar, text="Clear Queue", command=self.clear_queue)
        self.btn_remove = ttk.Button(self.btn_bar, text="Remove", command=self.remove_selected)

        self._last_btn_bar_mode = None
        self.btn_bar.bind("<Configure>", self._on_btn_bar_resize)

        # Interactive Visual Drop Zone Banner
        self.drop_banner = tk.Label(
            self.q_frame,
            height=2,
            font=("Segoe UI", 9, "bold"),
            relief="ridge",
            bd=1,
            cursor="hand2",
        )
        self.drop_banner.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.drop_banner.bind("<Button-1>", self.repair_dnd_clicked)
        self._reset_drop_banner()

        cols = ("name", "duration", "src_size", "status", "out_size", "saved")
        self.tree = ttk.Treeview(self.q_frame, columns=cols, show="headings", selectmode="extended", height=6)
        self.tree.heading("name", text="Video File")
        self.tree.heading("duration", text="Duration")
        self.tree.heading("src_size", text="Original")
        self.tree.heading("status", text="Status")
        self.tree.heading("out_size", text="New Size")
        self.tree.heading("saved", text="Saved")

        self.tree.column("name", width=250, minwidth=140, anchor="w", stretch=True)
        self.tree.column("duration", width=70, minwidth=60, anchor="center", stretch=False)
        self.tree.column("src_size", width=80, minwidth=65, anchor="e", stretch=False)
        self.tree.column("status", width=125, minwidth=95, anchor="center", stretch=False)
        self.tree.column("out_size", width=80, minwidth=65, anchor="e", stretch=False)
        self.tree.column("saved", width=95, minwidth=75, anchor="e", stretch=False)

        v_scroll = ttk.Scrollbar(self.q_frame, orient="vertical", command=self.tree.yview)
        h_scroll = ttk.Scrollbar(self.q_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        self.tree.grid(row=2, column=0, sticky="nsew")
        v_scroll.grid(row=2, column=1, sticky="ns")
        h_scroll.grid(row=3, column=0, sticky="ew")
        self.tree.bind("<Configure>", self._on_tree_resize)

        # Output Location Frame
        out_frame = ttk.LabelFrame(left_pane, text="2. Output Destination & Naming", padding=(8, 6))
        out_frame.grid(row=1, column=0, sticky="ew")
        out_frame.columnconfigure(1, weight=1)

        ttk.Radiobutton(
            out_frame,
            text="Save in the same folder as input video (Default)",
            variable=self.var_output_mode,
            value="same_dir",
            command=self.save_settings,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Radiobutton(
            out_frame,
            text="Custom folder:",
            variable=self.var_output_mode,
            value="custom_dir",
            command=self.save_settings,
        ).grid(row=1, column=0, sticky="w", pady=3)

        ttk.Entry(out_frame, textvariable=self.var_custom_dir).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(out_frame, text="Browse...", command=self.browse_output_dir).grid(row=1, column=2, sticky="e")

        self.naming_row = ttk.Frame(out_frame)
        self.naming_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.lbl_suffix = ttk.Label(self.naming_row, text="Suffix:")
        self.entry_suffix = ttk.Entry(self.naming_row, textvariable=self.var_suffix, width=10)
        self.entry_suffix.bind("<FocusOut>", self.save_settings)
        self.lbl_format = ttk.Label(self.naming_row, text="Format:")
        self.cb_format = ttk.Combobox(self.naming_row, textvariable=self.var_container, values=[".mkv", ".mp4"], width=6, state="readonly")
        self.cb_format.bind("<<ComboboxSelected>>", self.save_settings)
        self.chk_preserve_subfolders = ttk.Checkbutton(
            self.naming_row,
            text="Mirror subfolders",
            variable=self.var_preserve_subfolders,
            command=self.save_settings,
        )

        self._last_naming_mode = None
        self.naming_row.bind("<Configure>", self._on_naming_row_resize)

        # RIGHT PANE: Scrollable Settings Panel
        right_outer = ttk.LabelFrame(self.paned, text="3. Quality, GPU & Audio Settings (Auto-Saved)", padding=4)
        right_outer.rowconfigure(0, weight=1)
        right_outer.columnconfigure(0, weight=1)

        self.scroll_container = ScrollableFrame(right_outer, bg_color=self.bg_panel)
        self.scroll_container.grid(row=0, column=0, sticky="nsew")
        right_col = self.scroll_container.inner
        right_col.configure(padding=(8, 4))
        right_col.columnconfigure(1, weight=1)

        self.paned.add(left_pane, weight=3)
        self.paned.add(right_outer, weight=2)

        # Populate Right Scrollable Settings Panel
        r = 0
        ttk.Label(right_col, text="Video Encoder:").grid(row=r, column=0, sticky="w", pady=4)
        self.enc_cb = ttk.Combobox(right_col, textvariable=self.var_encoder, values=["auto", "hevc_nvenc", "libx265"], state="readonly")
        self.enc_cb.grid(row=r, column=1, sticky="ew", pady=4)
        self.enc_cb.bind("<<ComboboxSelected>>", self.save_settings)

        r += 1
        cq_frame = ttk.Frame(right_col)
        cq_frame.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Label(cq_frame, text="Constant Quality (CQ / CRF):").pack(side="left")
        self.lbl_cq_val = ttk.Label(
            cq_frame,
            text=f"{self.var_cq.get()} (Visually Lossless)",
            foreground=self.accent_green,
            font=("Segoe UI", 10, "bold"),
        )
        self.lbl_cq_val.pack(side="right")

        r += 1
        cq_scale = tk.Scale(
            right_col,
            from_=16,
            to=32,
            orient="horizontal",
            variable=self.var_cq,
            bg=self.bg_panel,
            fg=self.fg_main,
            highlightthickness=0,
            troughcolor=self.bg_input,
            activebackground=self.accent,
            showvalue=False,
            command=self.on_cq_change,
        )
        cq_scale.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        r += 1
        ttk.Label(right_col, text="Encoder Preset:").grid(row=r, column=0, sticky="w", pady=4)
        preset_cb = ttk.Combobox(
            right_col,
            textvariable=self.var_preset_label,
            values=list(PRESET_LABELS.values()),
            state="readonly",
        )
        preset_cb.grid(row=r, column=1, sticky="ew", pady=4)
        preset_cb.bind("<<ComboboxSelected>>", self.save_settings)

        r += 1
        ttk.Label(right_col, text="Output Resolution:").grid(row=r, column=0, sticky="w", pady=4)
        res_cb = ttk.Combobox(
            right_col,
            textvariable=self.var_resolution_label,
            values=list(RESOLUTION_LABELS.values()),
            state="readonly",
        )
        res_cb.grid(row=r, column=1, sticky="ew", pady=4)
        res_cb.bind("<<ComboboxSelected>>", self.on_resolution_change)

        r += 1
        self.custom_res_row = ttk.Frame(right_col)
        self.custom_res_row.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(self.custom_res_row, text="Custom W × H:").pack(side="left")
        sp_cw = ttk.Spinbox(self.custom_res_row, from_=0, to=7680, increment=2, textvariable=self.var_custom_width, width=6, command=self.save_settings)
        sp_cw.pack(side="left", padx=(6, 4))
        sp_cw.bind("<FocusOut>", self.save_settings)
        ttk.Label(self.custom_res_row, text="×").pack(side="left")
        sp_ch = ttk.Spinbox(self.custom_res_row, from_=0, to=4320, increment=2, textvariable=self.var_custom_height, width=6, command=self.save_settings)
        sp_ch.pack(side="left", padx=(4, 6))
        sp_ch.bind("<FocusOut>", self.save_settings)
        ttk.Label(self.custom_res_row, text="(0 = auto)", style="Sub.TLabel").pack(side="left")
        self._update_custom_res_visibility()

        r += 1
        ttk.Checkbutton(
            right_col,
            text="10-Bit HEVC (Main10) — Prevents Color Banding",
            variable=self.var_ten_bit,
            command=self.save_settings,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)

        r += 1
        ttk.Checkbutton(
            right_col,
            text="CUDA Hardware Decoding (Fastest RTX 3060 Pipeline)",
            variable=self.var_hw_decode,
            command=self.save_settings,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)

        r += 1
        grid_params = ttk.Frame(right_col)
        grid_params.grid(row=r, column=0, columnspan=2, sticky="ew", pady=6)
        grid_params.columnconfigure((1, 3), weight=1)

        ttk.Label(grid_params, text="GOP (Keyint):").grid(row=0, column=0, sticky="w", pady=3)
        sp_gop = ttk.Spinbox(grid_params, from_=25, to=600, increment=25, textvariable=self.var_gop, width=7, command=self.save_settings)
        sp_gop.grid(row=0, column=1, sticky="w", padx=6)
        sp_gop.bind("<FocusOut>", self.save_settings)

        ttk.Label(grid_params, text="B-Frames:").grid(row=0, column=2, sticky="w", pady=3)
        sp_bf = ttk.Spinbox(grid_params, from_=0, to=8, textvariable=self.var_bframes, width=6, command=self.save_settings)
        sp_bf.grid(row=0, column=3, sticky="w", padx=6)
        sp_bf.bind("<FocusOut>", self.save_settings)

        ttk.Label(grid_params, text="Lookahead:").grid(row=1, column=0, sticky="w", pady=3)
        sp_la = ttk.Spinbox(grid_params, from_=0, to=32, textvariable=self.var_lookahead, width=7, command=self.save_settings)
        sp_la.grid(row=1, column=1, sticky="w", padx=6)
        sp_la.bind("<FocusOut>", self.save_settings)

        ttk.Label(grid_params, text="AQ Strength:").grid(row=1, column=2, sticky="w", pady=3)
        sp_aq = ttk.Spinbox(grid_params, from_=1, to=15, textvariable=self.var_aq_strength, width=6, command=self.save_settings)
        sp_aq.grid(row=1, column=3, sticky="w", padx=6)
        sp_aq.bind("<FocusOut>", self.save_settings)

        ttk.Label(grid_params, text="Multipass:").grid(row=2, column=0, sticky="w", pady=3)
        mp_cb = ttk.Combobox(grid_params, textvariable=self.var_multipass, values=["fullres", "qres", "disabled"], width=8, state="readonly")
        mp_cb.grid(row=2, column=1, sticky="w", padx=6)
        mp_cb.bind("<<ComboboxSelected>>", self.save_settings)

        ttk.Label(grid_params, text="B-Ref Mode:").grid(row=2, column=2, sticky="w", pady=3)
        br_cb = ttk.Combobox(grid_params, textvariable=self.var_b_ref, values=["middle", "each", "disabled"], width=8, state="readonly")
        br_cb.grid(row=2, column=3, sticky="w", padx=6)
        br_cb.bind("<<ComboboxSelected>>", self.save_settings)

        r += 1
        aq_row = ttk.Frame(right_col)
        aq_row.grid(row=r, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(aq_row, text="Spatial AQ", variable=self.var_spatial_aq, command=self.save_settings).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(aq_row, text="Temporal AQ", variable=self.var_temporal_aq, command=self.save_settings).pack(side="left")

        r += 1
        mr_row = ttk.Frame(right_col)
        mr_row.grid(row=r, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Checkbutton(
            mr_row,
            text="Max Bitrate Cap (kbps):",
            variable=self.var_maxrate_enabled,
            command=self.save_settings,
        ).pack(side="left")
        sp_mr = ttk.Spinbox(mr_row, from_=800, to=20000, increment=100, textvariable=self.var_maxrate_kbps, width=8, command=self.save_settings)
        sp_mr.pack(side="left", padx=6)
        sp_mr.bind("<FocusOut>", self.save_settings)

        r += 1
        ttk.Separator(right_col, orient="horizontal").grid(row=r, column=0, columnspan=2, sticky="ew", pady=8)

        r += 1
        ttk.Label(right_col, text="Audio Mode:").grid(row=r, column=0, sticky="w", pady=4)
        aud_cb = ttk.Combobox(
            right_col,
            textvariable=self.var_audio_mode,
            values=["copy", "aac_192k", "opus_128k"],
            state="readonly",
        )
        aud_cb.grid(row=r, column=1, sticky="ew", pady=4)
        aud_cb.bind("<<ComboboxSelected>>", self.save_settings)

        r += 1
        ttk.Checkbutton(
            right_col,
            text="Copy All Subtitle & Chapter Tracks (-c:s copy)",
            variable=self.var_keep_subs,
            command=self.save_settings,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=2)

        r += 1
        ttk.Checkbutton(
            right_col,
            text="Skip files that already have an encoded output",
            variable=self.var_skip_existing,
            command=self.save_settings,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=2)

        r += 1
        ttk.Checkbutton(
            right_col,
            text="Smart Size Guard (Keep original if encoded is larger)",
            variable=self.var_size_guard,
            command=self.save_settings,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=2)

        r += 1
        ttk.Checkbutton(
            right_col,
            text="Shutdown PC when finished (5-second grace countdown)",
            variable=self.var_shutdown_on_finish,
            command=self.on_shutdown_toggle,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=2)

        r += 1
        ttk.Label(right_col, text="Extra FFmpeg Flags:").grid(row=r, column=0, sticky="w", pady=4)
        ex_entry = ttk.Entry(right_col, textvariable=self.var_extra_args)
        ex_entry.grid(row=r, column=1, sticky="ew", pady=4)
        ex_entry.bind("<FocusOut>", self.save_settings)

        r += 1
        ttk.Button(right_col, text="Reset to Best RTX 3060 Defaults", command=self.reset_to_defaults).grid(
            row=r, column=0, columnspan=2, sticky="ew", pady=(10, 4)
        )

        # Trigger initial responsive layout passes
        self.root.after_idle(self._trigger_initial_responsive_layout)

    def _trigger_initial_responsive_layout(self):
        self._on_bottom_resize()
        self._on_btn_bar_resize()
        self._on_naming_row_resize()

    def _on_bottom_resize(self, event=None):
        w = self.bottom_frame.winfo_width()
        if w <= 1:
            return
        mode = "wide" if w >= 860 else ("medium" if w >= 640 else "narrow")
        if mode == self._last_bottom_mode:
            return
        self._last_bottom_mode = mode

        # Status & metrics info layout
        self.lbl_status.grid_forget()
        self.lbl_metrics.grid_forget()
        if mode == "wide":
            self.lbl_status.grid(row=0, column=0, sticky="w")
            self.lbl_metrics.grid(row=0, column=1, sticky="e")
        else:
            self.lbl_status.grid(row=0, column=0, sticky="w", pady=(0, 2))
            self.lbl_metrics.grid(row=1, column=0, sticky="w", pady=(0, 2))

        # Control buttons & shutdown checkbox layout
        for widget in (self.btn_start, self.btn_sample, self.btn_skip, self.btn_cancel, self.chk_shutdown):
            widget.pack_forget()
            widget.grid_forget()

        if mode == "wide":
            self.btn_start.pack(side="left", padx=(0, 8))
            self.btn_sample.pack(side="left", padx=(0, 8))
            self.btn_skip.pack(side="left", padx=(0, 8))
            self.btn_cancel.pack(side="right")
            self.chk_shutdown.pack(side="right", padx=(0, 14))
        elif mode == "medium":
            self.btn_start.grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")
            self.btn_sample.grid(row=0, column=1, padx=(0, 6), pady=2, sticky="w")
            self.btn_skip.grid(row=0, column=2, padx=(0, 6), pady=2, sticky="w")
            self.btn_cancel.grid(row=0, column=3, padx=(0, 6), pady=2, sticky="w")
            self.chk_shutdown.grid(row=1, column=0, columnspan=4, pady=(4, 0), sticky="w")
        else:
            self.btn_start.grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")
            self.btn_sample.grid(row=0, column=1, padx=(0, 6), pady=2, sticky="w")
            self.btn_skip.grid(row=1, column=0, padx=(0, 6), pady=2, sticky="w")
            self.btn_cancel.grid(row=1, column=1, padx=(0, 6), pady=2, sticky="w")
            self.chk_shutdown.grid(row=2, column=0, columnspan=2, pady=(4, 0), sticky="w")

    def _on_btn_bar_resize(self, event=None):
        w = self.btn_bar.winfo_width()
        if w <= 1:
            return
        mode = "wide" if w >= 540 else "narrow"
        if mode == self._last_btn_bar_mode:
            return
        self._last_btn_bar_mode = mode

        for widget in (self.btn_add_files, self.btn_add_folder, self.btn_paste, self.chk_recursive, self.btn_remove, self.btn_clear):
            widget.pack_forget()
            widget.grid_forget()

        if mode == "wide":
            self.btn_add_files.pack(side="left", padx=(0, 5))
            self.btn_add_folder.pack(side="left", padx=(0, 5))
            self.btn_paste.pack(side="left", padx=(0, 6))
            self.chk_recursive.pack(side="left", padx=(2, 6))
            self.btn_clear.pack(side="right")
            self.btn_remove.pack(side="right", padx=(0, 5))
        else:
            self.btn_add_files.grid(row=0, column=0, padx=(0, 4), pady=2, sticky="w")
            self.btn_add_folder.grid(row=0, column=1, padx=(0, 4), pady=2, sticky="w")
            self.btn_paste.grid(row=0, column=2, padx=(0, 4), pady=2, sticky="w")
            self.chk_recursive.grid(row=1, column=0, padx=(2, 4), pady=2, sticky="w")
            self.btn_remove.grid(row=1, column=1, padx=(0, 4), pady=2, sticky="w")
            self.btn_clear.grid(row=1, column=2, padx=(0, 4), pady=2, sticky="w")

    def _on_naming_row_resize(self, event=None):
        w = self.naming_row.winfo_width()
        if w <= 1:
            return
        mode = "wide" if w >= 430 else "narrow"
        if mode == self._last_naming_mode:
            return
        self._last_naming_mode = mode

        for widget in (self.lbl_suffix, self.entry_suffix, self.lbl_format, self.cb_format, self.chk_preserve_subfolders):
            widget.pack_forget()
            widget.grid_forget()

        if mode == "wide":
            self.lbl_suffix.pack(side="left")
            self.entry_suffix.pack(side="left", padx=(4, 12))
            self.lbl_format.pack(side="left")
            self.cb_format.pack(side="left", padx=(4, 12))
            self.chk_preserve_subfolders.pack(side="left")
        else:
            self.lbl_suffix.grid(row=0, column=0, sticky="w")
            self.entry_suffix.grid(row=0, column=1, padx=(4, 8), sticky="w")
            self.lbl_format.grid(row=0, column=2, sticky="w")
            self.cb_format.grid(row=0, column=3, padx=(4, 8), sticky="w")
            self.chk_preserve_subfolders.grid(row=1, column=0, columnspan=4, pady=(4, 0), sticky="w")

    def _on_tree_resize(self, event):
        fixed_cols_width = 70 + 80 + 125 + 80 + 95 + 24
        available_for_name = max(160, event.width - fixed_cols_width)
        self.tree.column("name", width=available_for_name)

    def _update_custom_res_visibility(self):
        res_key = LABEL_TO_RESOLUTION.get(self.var_resolution_label.get(), "original")
        if res_key == "custom":
            self.custom_res_row.grid()
        else:
            self.custom_res_row.grid_remove()

    def on_resolution_change(self, _event=None):
        self._update_custom_res_visibility()
        self.save_settings()

    def on_cq_change(self, val):
        v = int(float(val))
        desc = "Max Detail" if v <= 21 else ("Visually Lossless" if v <= 24 else ("Balanced" if v <= 27 else "Max Compression"))
        self.lbl_cq_val.configure(text=f"{v} ({desc})")
        self.save_settings()

    # --------------------------------------------------------------------------
    # Live Non-Blocking File, Folder & Drag-and-Drop Queueing (Works While Encoding!)
    # --------------------------------------------------------------------------
    def add_files(self):
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))
        files = filedialog.askopenfilenames(
            title="Select Video Episodes",
            filetypes=[("Video Files", exts), ("All Files", "*.*")],
        )
        if not files:
            return
        self.enqueue_raw_paths([Path(f) for f in files], source_label=f"{len(files)} file(s)")

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select Episode Folder")
        if not folder:
            return
        p = Path(folder)
        self.enqueue_raw_paths([p], source_label=p.name)

    def enqueue_raw_paths(self, raw_paths: list, source_label: str):
        """Pushes files or folders into the background ingest worker—never blocks UI or active encoding."""
        if self._shutdown_timer_id:
            self.cancel_shutdown()
        with self.queue_lock:
            self.active_ingest_batches += 1
        self.ingest_tasks_queue.put((raw_paths, self.var_recursive.get(), self.var_suffix.get().strip() or "_hevc10", source_label))

    def _background_ingest_loop(self):
        """Persistent background daemon that expands folders, adds rows to the queue, and probes durations."""
        while True:
            raw_paths, recursive, suffix, source_label = self.ingest_tasks_queue.get()
            try:
                discovered = []
                for p in raw_paths:
                    if p.is_dir():
                        iterator = p.rglob("*") if recursive else p.glob("*")
                        for sub in sorted(iterator):
                            if sub.is_file() and sub.suffix.lower() in VIDEO_EXTENSIONS:
                                if sub.stem.endswith(suffix) or "_sample30s" in sub.stem or ".part" in sub.name:
                                    continue
                                discovered.append((sub, p))
                    elif p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                        if p.stem.endswith(suffix) or "_sample30s" in p.stem or ".part" in p.name:
                            continue
                        discovered.append((p, p.parent))

                added_items = []
                for path, base_root in discovered:
                    with self.queue_lock:
                        if path in self.queued_paths:
                            continue
                        self.queued_paths.add(path)
                        src_size = path.stat().st_size if path.exists() else 0
                        item_id = f"{len(self.file_queue)}_{time.time_ns()}"
                        item = {
                            "id": item_id,
                            "path": path,
                            "base_root": base_root,
                            "duration": 0.0,
                            "src_size": src_size,
                            "status": "Queued",
                            "out_size": 0,
                        }
                        self.file_queue.append(item)
                        added_items.append(item)
                    self.ui_queue.put(("insert_row", item))

                for item in added_items:
                    if item["duration"] <= 0 and item["path"].exists():
                        dur = self.probe_duration(item["path"])
                        item["duration"] = dur
                        self.ui_queue.put(("update_duration", item["id"], self.format_duration(dur)))

                self.ui_queue.put(("ingest_feedback", len(added_items), source_label))
            finally:
                with self.queue_lock:
                    self.active_ingest_batches = max(0, self.active_ingest_batches - 1)
                self.ingest_tasks_queue.task_done()

    def remove_selected(self):
        selected = set(self.tree.selection())
        if not selected:
            return
        with self.queue_lock:
            kept = []
            for item in self.file_queue:
                iid = item["id"]
                if iid in selected and iid != self.current_encoding_id:
                    self.queued_paths.discard(item["path"])
                    if self.tree.exists(iid):
                        self.tree.delete(iid)
                else:
                    kept.append(item)
            self.file_queue = kept

    def clear_queue(self):
        """Clears all non-running items from the queue (even if encoding is currently active)."""
        if self._shutdown_timer_id:
            self.cancel_shutdown()
        with self.queue_lock:
            kept = []
            for item in self.file_queue:
                iid = item["id"]
                if self.is_encoding and iid == self.current_encoding_id:
                    kept.append(item)
                else:
                    self.queued_paths.discard(item["path"])
                    if self.tree.exists(iid):
                        self.tree.delete(iid)
            self.file_queue = kept
        if not self.is_encoding:
            self.lbl_status.configure(text="Queue cleared.")

    def browse_output_dir(self):
        d = filedialog.askdirectory(title="Select Output Folder")
        if d:
            self.var_custom_dir.set(d)
            self.var_output_mode.set("custom_dir")
            self.save_settings()

    # --------------------------------------------------------------------------
    # FFprobe & Formatting Helpers
    # --------------------------------------------------------------------------
    @staticmethod
    def probe_duration(path: Path) -> float:
        if not shutil.which("ffprobe"):
            return 0.0
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        try:
            kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL, "text": True, "timeout": 5}
            if OS_SYSTEM == "windows":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            res = subprocess.run(cmd, **kwargs)
            return float(res.stdout.strip())
        except Exception:
            return 0.0

    @staticmethod
    def format_duration(seconds: float) -> str:
        if seconds <= 0:
            return "--:--"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    @staticmethod
    def format_size(num_bytes: int) -> str:
        if num_bytes <= 0:
            return "0 MB"
        mb = num_bytes / (1024 * 1024)
        return f"{mb:.1f} MB" if mb < 1024 else f"{mb / 1024:.2f} GB"

    def resolve_output_path(self, item: dict, sample_mode: bool = False) -> Path:
        src_path: Path = item["path"]
        base_root: Path = item["base_root"]
        suffix = self.var_suffix.get().strip() or "_hevc10"
        if sample_mode:
            suffix = f"{suffix}_sample30s"
        container = self.var_container.get() or ".mkv"

        if self.var_output_mode.get() == "custom_dir" and self.var_custom_dir.get().strip():
            out_root = Path(self.var_custom_dir.get().strip())
            if self.var_preserve_subfolders.get():
                try:
                    rel = src_path.parent.relative_to(base_root)
                    target_dir = out_root / rel
                except ValueError:
                    target_dir = out_root
            else:
                target_dir = out_root
        else:
            target_dir = src_path.parent

        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / f"{src_path.stem}{suffix}{container}"

    # --------------------------------------------------------------------------
    # FFmpeg Command Builder
    # --------------------------------------------------------------------------
    def build_ffmpeg_command(self, src_path: Path, temp_out_path: Path, duration: float, sample_mode: bool, use_hw_decode: bool) -> list:
        self.save_settings()
        s = self.settings
        enc = self.best_encoder if s["encoder"] == "auto" else s["encoder"]

        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]

        if enc == "hevc_nvenc" and use_hw_decode and s["hw_decode"]:
            cmd += ["-hwaccel", "cuda"]

        if sample_mode and duration > 40:
            start_sec = int(duration * 0.4)
            cmd += ["-ss", str(start_sec)]

        cmd += ["-i", str(src_path)]

        if sample_mode:
            cmd += ["-t", "30"]

        cmd += ["-map", "0:v:0", "-map", "0:a?"]
        if s["keep_subtitles"] and s["container"] == ".mkv":
            cmd += ["-map", "0:s?"]

        vf_filters = []
        res_mode = s.get("resolution", "original")
        if res_mode in RESOLUTION_DIMS:
            tw, th = RESOLUTION_DIMS[res_mode]
            vf_filters.append(
                f"scale={tw}:{th}:force_original_aspect_ratio=decrease:flags=lanczos,scale=trunc(iw/2)*2:trunc(ih/2)*2"
            )
        elif res_mode == "custom":
            cw = int(s.get("custom_width", 0) or 0)
            ch = int(s.get("custom_height", 0) or 0)
            if cw > 0 and ch > 0:
                cw = max(2, cw - (cw % 2))
                ch = max(2, ch - (ch % 2))
                vf_filters.append(f"scale={cw}:{ch}:flags=lanczos")
            elif cw > 0:
                cw = max(2, cw - (cw % 2))
                vf_filters.append(f"scale={cw}:-2:flags=lanczos")
            elif ch > 0:
                ch = max(2, ch - (ch % 2))
                vf_filters.append(f"scale=-2:{ch}:flags=lanczos")

        if vf_filters:
            cmd += ["-vf", ",".join(vf_filters)]

        cmd += ["-c:v", enc]

        if enc == "hevc_nvenc":
            nv_preset = s["preset"] if s["preset"].startswith("p") else "p7"
            cmd += [
                "-preset", nv_preset,
                "-tune", "hq",
                "-rc", "vbr",
                "-cq", str(s["cq"]),
                "-b:v", "0",
                "-g", str(s["gop"]),
                "-bf", str(s["bframes"]),
                "-b_ref_mode", s["b_ref_mode"],
                "-rc-lookahead", str(s["lookahead"]),
                "-multipass", s["multipass"],
            ]
            if s["ten_bit"]:
                cmd += ["-profile:v", "main10", "-pix_fmt", "p010le"]
            else:
                cmd += ["-profile:v", "main", "-pix_fmt", "yuv420p"]

            if s["spatial_aq"]:
                cmd += ["-spatial-aq", "1", "-aq-strength", str(s["aq_strength"])]
            if s["temporal_aq"]:
                cmd += ["-temporal-aq", "1"]

        elif enc == "hevc_videotoolbox":
            vt_q = max(35, min(85, int(100 - (s["cq"] * 2.2))))
            cmd += ["-q:v", str(vt_q), "-g", str(s["gop"])]
            cmd += ["-pix_fmt", "p010le" if s["ten_bit"] else "yuv420p"]

        elif enc in ("hevc_qsv", "hevc_amf", "hevc_vaapi"):
            cmd += ["-global_quality", str(s["cq"]), "-g", str(s["gop"])]
            cmd += ["-pix_fmt", "p010le" if s["ten_bit"] else "yuv420p"]

        else:
            cpu_preset = s["preset"] if not s["preset"].startswith("p") else "slow"
            cmd += [
                "-preset", cpu_preset,
                "-crf", str(s["cq"]),
                "-pix_fmt", "yuv420p10le" if s["ten_bit"] else "yuv420p",
                "-x265-params", f"keyint={s['gop']}:bframes={s['bframes']}:aq-mode=3",
            ]

        if s["maxrate_cap_enabled"] and s["maxrate_kbps"] > 0:
            mr = int(s["maxrate_kbps"])
            cmd += ["-maxrate", f"{mr}k", "-bufsize", f"{mr * 2}k"]

        if s["audio_mode"] == "copy":
            cmd += ["-c:a", "copy"]
        elif s["audio_mode"] == "aac_192k":
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        elif s["audio_mode"] == "opus_128k":
            cmd += ["-c:a", "libopus", "-b:a", "128k"]

        if s["keep_subtitles"] and s["container"] == ".mkv":
            cmd += ["-c:s", "copy"]

        if s["extra_ffmpeg_args"]:
            cmd += s["extra_ffmpeg_args"].split()

        cmd.append(str(temp_out_path))
        return cmd

    # --------------------------------------------------------------------------
    # Dynamic Live Encoding Engine (Picks Up Newly Queued Videos Automatically)
    # --------------------------------------------------------------------------
    def start_encoding(self, sample_mode: bool = False):
        if self._shutdown_timer_id:
            self.cancel_shutdown()
        if self.is_encoding:
            return
        with self.queue_lock:
            if not self.file_queue and self.active_ingest_batches == 0:
                messagebox.showinfo("Queue Empty", "Please drag & drop, paste (Ctrl+V), or add video files first.")
                return

            if not sample_mode:
                has_queued = any(i["status"] == "Queued" for i in self.file_queue)
                if not has_queued:
                    for i in self.file_queue:
                        if i["status"] in ("Cancelled", "Failed", "Skipped"):
                            i["status"] = "Queued"
                            self.ui_queue.put(("row", i["id"], "Queued", "--", "--"))

        sample_target_id = None
        if sample_mode:
            sel = self.tree.selection()
            with self.queue_lock:
                sample_target_id = sel[0] if sel else (self.file_queue[0]["id"] if self.file_queue else None)
            if not sample_target_id:
                return

        self.is_encoding = True
        self.cancel_requested = False
        self.skip_current_requested = False

        self.btn_start.configure(state="disabled")
        self.btn_sample.configure(state="disabled")
        self.btn_skip.configure(state="normal")
        self.btn_cancel.configure(state="normal")

        threading.Thread(target=self.encode_worker, args=(sample_mode, sample_target_id), daemon=True).start()

    def skip_current(self):
        if self.is_encoding and self.current_process:
            self.skip_current_requested = True
            threading.Thread(target=self._terminate_proc, args=(self.current_process,), daemon=True).start()

    def cancel_encoding(self):
        if self._shutdown_timer_id:
            self.cancel_shutdown()
            return
        if self.is_encoding:
            self.cancel_requested = True
            if self.current_process:
                threading.Thread(target=self._terminate_proc, args=(self.current_process,), daemon=True).start()

    @staticmethod
    def _terminate_proc(proc):
        try:
            proc.terminate()
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # Automatic PC Shutdown On Completion
    # --------------------------------------------------------------------------
    def on_shutdown_toggle(self):
        self.save_settings()
        if not self.var_shutdown_on_finish.get() and self._shutdown_timer_id:
            self.cancel_shutdown()

    def start_shutdown_countdown(self, total_saved: int = 0):
        if self._shutdown_timer_id:
            try:
                self.root.after_cancel(self._shutdown_timer_id)
            except Exception:
                pass
            self._shutdown_timer_id = None

        self._shutdown_seconds_left = 5
        self._shutdown_total_saved = total_saved
        self.btn_cancel.configure(text="⏹ Cancel Shutdown (5s)", state="normal", style="Danger.TButton", command=self.cancel_shutdown)
        self.lbl_status.configure(
            text="⚠️ Batch Finished! Shutting down PC in 5s... Click 'Cancel Shutdown' to abort.",
            foreground=self.accent_red,
        )
        self._shutdown_timer_id = self.root.after(1000, self._shutdown_tick)

    def _shutdown_tick(self):
        if not self._shutdown_timer_id:
            return
        self._shutdown_seconds_left -= 1
        if self._shutdown_seconds_left > 0:
            s_label = f"{self._shutdown_seconds_left}s"
            self.lbl_status.configure(
                text=f"⚠️ Batch Finished! Shutting down PC in {s_label}... Click 'Cancel Shutdown' to abort.",
                foreground=self.accent_red,
            )
            self.btn_cancel.configure(text=f"⏹ Cancel Shutdown ({s_label})")
            self._shutdown_timer_id = self.root.after(1000, self._shutdown_tick)
        else:
            self._shutdown_timer_id = None
            self.lbl_status.configure(text="Shutting down PC now...", foreground=self.accent_red)
            self.btn_cancel.configure(text="⏹ Stop / Cancel", state="disabled", command=self.cancel_encoding)
            self.root.update_idletasks()
            self.execute_pc_shutdown()

    def cancel_shutdown(self):
        if self._shutdown_timer_id:
            try:
                self.root.after_cancel(self._shutdown_timer_id)
            except Exception:
                pass
            self._shutdown_timer_id = None
        self._shutdown_seconds_left = 0
        self.var_shutdown_on_finish.set(False)
        self.save_settings()
        self.btn_cancel.configure(text="⏹ Stop / Cancel", state="disabled", command=self.cancel_encoding)
        saved_str = self.format_size(self._shutdown_total_saved) if self._shutdown_total_saved else "0 B"
        self.lbl_status.configure(
            text=f"Automatic shutdown cancelled. Batch Finished! Total Space Saved: {saved_str}",
            foreground=self.fg_main,
        )

    def execute_pc_shutdown(self):
        self.var_shutdown_on_finish.set(False)
        self.save_settings()
        try:
            if OS_SYSTEM == "windows":
                kwargs = {}
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                subprocess.run(["shutdown", "/s", "/f", "/t", "0"], check=False, **kwargs)
            elif OS_SYSTEM == "darwin":
                subprocess.run(["osascript", "-e", 'tell app "System Events" to shut down'], check=False)
            else:
                shut_done = False
                if shutil.which("systemctl"):
                    try:
                        res = subprocess.run(["systemctl", "poweroff"], check=False)
                        if res.returncode == 0:
                            shut_done = True
                    except Exception:
                        pass
                if not shut_done and shutil.which("shutdown"):
                    try:
                        res = subprocess.run(["shutdown", "-h", "now"], check=False)
                        if res.returncode == 0:
                            shut_done = True
                    except Exception:
                        pass
                if not shut_done and shutil.which("poweroff"):
                    subprocess.run(["poweroff"], check=False)
            try:
                self.root.destroy()
            except Exception:
                pass
        except Exception as e:
            try:
                self.lbl_status.configure(text=f"Error initiating shutdown: {e}", foreground=self.accent_red)
            except Exception:
                pass

    def _get_next_queued_item(self, sample_mode: bool, sample_target_id: str, sample_done: bool):
        """Finds the next item to encode dynamically so files added mid-run are seamlessly picked up."""
        with self.queue_lock:
            if sample_mode:
                if sample_done:
                    return None, 1, 1
                for item in self.file_queue:
                    if item["id"] == sample_target_id:
                        return item, 1, 1
                return None, 1, 1

            total_count = len(self.file_queue)
            for idx, item in enumerate(self.file_queue, start=1):
                if item["status"] == "Queued":
                    item["status"] = "Encoding"
                    return item, idx, total_count
            return None, total_count, total_count

    def encode_worker(self, sample_mode: bool, sample_target_id: str):
        total_saved_bytes = 0
        sample_done = False

        while not self.cancel_requested:
            item, cur_idx, total_items = self._get_next_queued_item(sample_mode, sample_target_id, sample_done)

            if item is None:
                with self.queue_lock:
                    still_ingesting = self.active_ingest_batches > 0
                if still_ingesting and not sample_mode:
                    time.sleep(0.15)
                    continue
                break

            sample_done = True
            self.skip_current_requested = False
            iid = item["id"]
            self.current_encoding_id = iid
            src_path: Path = item["path"]

            if item["duration"] <= 0:
                item["duration"] = self.probe_duration(src_path)
                self.ui_queue.put(("update_duration", iid, self.format_duration(item["duration"])))

            duration = 30.0 if (sample_mode and item["duration"] > 30) else item["duration"]
            final_out = self.resolve_output_path(item, sample_mode=sample_mode)
            temp_out = final_out.with_name(f"{final_out.stem}.part{final_out.suffix}")

            if not sample_mode and self.settings["skip_existing"] and final_out.exists():
                out_sz = final_out.stat().st_size
                saved = item["src_size"] - out_sz
                total_saved_bytes += max(0, saved)
                pct = (saved / item["src_size"] * 100) if item["src_size"] else 0
                item["status"] = "Skipped (Exists)"
                self.ui_queue.put(("row", iid, "Skipped (Exists)", self.format_size(out_sz), f"-{pct:.0f}%"))
                continue

            self.ui_queue.put(("row", iid, "Encoding (0%)", "--", "--"))
            self.ui_queue.put(("status", f"[{cur_idx}/{total_items}] Encoding: {src_path.name}"))
            self.ui_queue.put(("prog", 0))

            success = self.run_single_ffmpeg(src_path, temp_out, duration, sample_mode, iid, total_saved_bytes, use_hw_decode=True)
            if not success and not self.cancel_requested and not self.skip_current_requested and self.settings["hw_decode"]:
                temp_out.unlink(missing_ok=True)
                success = self.run_single_ffmpeg(src_path, temp_out, duration, sample_mode, iid, total_saved_bytes, use_hw_decode=False)

            if self.cancel_requested:
                temp_out.unlink(missing_ok=True)
                item["status"] = "Cancelled"
                self.ui_queue.put(("row", iid, "Cancelled", "--", "--"))
                break

            if self.skip_current_requested:
                temp_out.unlink(missing_ok=True)
                item["status"] = "Skipped"
                self.ui_queue.put(("row", iid, "Skipped", "--", "--"))
                continue

            if success and temp_out.exists():
                out_sz = temp_out.stat().st_size
                src_sz = item["src_size"]

                if not sample_mode and self.settings["size_guard"] and src_sz > 0 and out_sz >= src_sz:
                    temp_out.unlink(missing_ok=True)
                    if self.settings["output_mode"] == "custom_dir" and self.settings["custom_output_dir"]:
                        shutil.copy2(src_path, final_out)
                    item["status"] = "Kept Original (Guard)"
                    self.ui_queue.put(("row", iid, "Kept Original (Guard)", self.format_size(src_sz), "0%"))
                else:
                    if final_out.exists():
                        final_out.unlink()
                    temp_out.rename(final_out)
                    saved = src_sz - out_sz
                    if not sample_mode:
                        total_saved_bytes += max(0, saved)
                    pct = (saved / src_sz * 100) if (src_sz and not sample_mode) else 0
                    status_label = "Sample Ready" if sample_mode else "Done ✓"
                    saved_label = "30s Clip" if sample_mode else f"-{pct:.1f}% ({self.format_size(saved)})"
                    item["status"] = status_label
                    self.ui_queue.put(("row", iid, status_label, self.format_size(out_sz), saved_label))
            else:
                temp_out.unlink(missing_ok=True)
                item["status"] = "Failed"
                self.ui_queue.put(("row", iid, "Failed", "--", "--"))

        self.current_encoding_id = None
        self.ui_queue.put(("done", total_saved_bytes, self.cancel_requested, sample_mode))

    def run_single_ffmpeg(self, src_path: Path, temp_out: Path, duration: float, sample_mode: bool, iid: str, total_saved_bytes: int, use_hw_decode: bool) -> bool:
        cmd = self.build_ffmpeg_command(src_path, temp_out, duration, sample_mode, use_hw_decode)
        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if OS_SYSTEM == "windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            self.current_process = subprocess.Popen(cmd, **kwargs)
        except Exception as e:
            print(f"Failed to start FFmpeg: {e}")
            return False

        fps_val = "--"
        speed_val = "--"
        last_ui_update = 0.0

        for line in self.current_process.stdout:
            if self.cancel_requested or self.skip_current_requested:
                break
            line = line.strip()
            if line.startswith("fps="):
                fps_val = line.split("=", 1)[1].strip()
            elif line.startswith("speed="):
                speed_val = line.split("=", 1)[1].strip()
            elif line.startswith("out_time_us="):
                now = time.monotonic()
                if now - last_ui_update < 0.1:
                    continue
                last_ui_update = now

                val_str = line.split("=", 1)[1].strip()
                if val_str.isdigit() and duration > 0:
                    cur_sec = int(val_str) / 1_000_000.0
                    pct = min(99.9, max(0.0, (cur_sec / duration) * 100.0))
                    eta_str = "--:--"
                    try:
                        spd = float(speed_val.replace("x", "").strip())
                        if spd > 0:
                            rem = max(0.0, (duration - cur_sec) / spd)
                            eta_str = self.format_duration(rem)
                    except Exception:
                        pass

                    with self.queue_lock:
                        total_q = len(self.file_queue)
                        done_q = sum(1 for i in self.file_queue if i["status"] not in ("Queued", "Encoding")) + 1

                    self.ui_queue.put(("prog", pct))
                    self.ui_queue.put(("row", iid, f"Encoding ({pct:.0f}%)", "--", "--"))
                    self.ui_queue.put(("status", f"[{done_q}/{total_q}] Encoding: {src_path.name}"))
                    self.ui_queue.put(
                        (
                            "metrics",
                            f"Speed: {speed_val}  |  FPS: {fps_val}  |  ETA: {eta_str}  |  Total Saved: {self.format_size(total_saved_bytes)}",
                        )
                    )

        self.current_process.wait()
        return self.current_process.returncode == 0

    def poll_ui_queue(self):
        try:
            for _ in range(50):
                msg = self.ui_queue.get_nowait()
                kind = msg[0]
                if kind == "gpu_ready":
                    _, gpu_name, best_enc, avail = msg
                    self.gpu_name = gpu_name
                    self.best_encoder = best_enc
                    self.available_encoders = avail
                    self.lbl_gpu.configure(text=f"GPU: {gpu_name}  |  Active HW Encoder: {best_enc}")
                    self.enc_cb.configure(values=["auto"] + [e[0] for e in avail])
                elif kind == "insert_row":
                    item = msg[1]
                    self.tree.insert(
                        "",
                        "end",
                        iid=item["id"],
                        values=(
                            item["path"].name,
                            "Probing...",
                            self.format_size(item["src_size"]),
                            item["status"],
                            "--",
                            "--",
                        ),
                    )
                elif kind == "update_duration":
                    _, iid, dur_str = msg
                    if self.tree.exists(iid):
                        vals = list(self.tree.item(iid, "values"))
                        vals[1] = dur_str
                        self.tree.item(iid, values=vals)
                elif kind == "ingest_feedback":
                    _, count_added, src_label = msg
                    if not self.is_encoding:
                        self.lbl_status.configure(
                            text=f"Added {count_added} video(s) from {src_label}. Total in queue: {len(self.file_queue)}"
                        )
                elif kind == "row":
                    _, iid, status, out_sz, saved = msg
                    if self.tree.exists(iid):
                        vals = list(self.tree.item(iid, "values"))
                        vals[3] = status
                        vals[4] = out_sz
                        vals[5] = saved
                        self.tree.item(iid, values=vals)
                elif kind == "status":
                    self.lbl_status.configure(text=msg[1])
                elif kind == "prog":
                    self.prog_file["value"] = msg[1]
                elif kind == "metrics":
                    self.lbl_metrics.configure(text=msg[1])
                elif kind == "done":
                    total_saved = msg[1]
                    was_cancelled = msg[2]
                    sample_mode = msg[3] if len(msg) > 3 else False
                    self.is_encoding = False
                    self.current_process = None
                    self.btn_start.configure(state="normal")
                    self.btn_sample.configure(state="normal")
                    self.btn_skip.configure(state="disabled")
                    self.prog_file["value"] = 0 if was_cancelled else 100
                    if was_cancelled:
                        self.btn_cancel.configure(text="⏹ Stop / Cancel", state="disabled", command=self.cancel_encoding)
                        self.lbl_status.configure(text="Encoding stopped.", foreground=self.fg_main)
                    else:
                        final_msg = f"Batch Finished! Total Disk Space Saved: {self.format_size(total_saved)}"
                        self.lbl_status.configure(text=final_msg, foreground=self.fg_main)
                        if not sample_mode and self.var_shutdown_on_finish.get():
                            self.start_shutdown_countdown(total_saved)
                        else:
                            self.btn_cancel.configure(text="⏹ Stop / Cancel", state="disabled", command=self.cancel_encoding)
        except queue.Empty:
            pass
        self.root.after(60, self.poll_ui_queue)

    def on_close(self):
        if self._shutdown_timer_id:
            try:
                self.root.after_cancel(self._shutdown_timer_id)
            except Exception:
                pass
            self._shutdown_timer_id = None
        self.save_settings()
        if self.is_encoding:
            if not messagebox.askyesno("Encoding in Progress", "Stop the current encode and exit? (Incomplete .part file will be cleaned up)"):
                return
            self.cancel_encoding()
            time.sleep(0.2)
        self.root.destroy()


if __name__ == "__main__":
    try:
        root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    except Exception as e:
        print(f"[Bootstrap] Warning: TkinterDnD.Tk() failed ({e}), falling back to standard Tk.")
        HAS_DND = False
        root = tk.Tk()
    app = HEVCStudioApp(root)
    # Accept files passed by a platform launcher (including files dropped onto
    # the launcher icon). Ignore bootstrap flags and any non-path arguments.
    startup_paths = []
    for argument in sys.argv[1:]:
        if argument.startswith("--"):
            continue
        path = clean_single_dropped_token(argument)
        if path is not None:
            startup_paths.append(path)
    if startup_paths:
        root.after_idle(lambda: app.enqueue_raw_paths(startup_paths, source_label=f"{len(startup_paths)} launched item(s)"))
    root.mainloop()