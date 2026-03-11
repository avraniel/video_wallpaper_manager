#!/usr/bin/env python3
"""
Video Wallpaper Manager - Consolidated Version
A unified application for managing video wallpapers with:
- MoeWalls integration (search & download)
- Local library management
- Multi-monitor support with smooth transitions
- Auto-change timer
- Global keyboard shortcuts
- System tray integration
- Comprehensive settings panel

Author: Raniel 
License: MIT
"""

import sys
import os
import requests
import subprocess
import threading
import time
import json
import random
import ctypes
import ctypes.wintypes
from datetime import datetime
from collections import deque
from urllib.parse import quote, urljoin
from io import BytesIO

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QListWidgetItem, QLabel,
    QMessageBox, QTabWidget, QComboBox, QSlider, QCheckBox,
    QGroupBox, QGridLayout, QSpinBox, QSystemTrayIcon, QMenu,
    QProgressBar, QTextEdit, QFileDialog, QFrame,
    QScrollArea, QRadioButton, QButtonGroup, QStyle,
    QKeySequenceEdit, QListWidget
)
from PyQt6.QtGui import (
    QPixmap, QFont, QIcon, QAction, QImage, QPainter, QBrush, 
    QColor, QPen, QPolygonF
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QObject, QPointF
from PIL import Image
from bs4 import BeautifulSoup

import win32gui
import win32con
import win32process
from screeninfo import get_monitors

# Keyboard shortcut support (optional)
try:
    from pynput import keyboard
    from pynput.keyboard import Key, KeyCode
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False
    print("pynput not installed. Keyboard shortcuts disabled.")
    print("Install with: pip install pynput")

# ==================== CONFIGURATION ====================

BASE_URL = "https://moewalls.com"
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wallpapers")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wallpaper.log")

VIDEO_EXTENSIONS = (".mp4", ".webm", ".mkv")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

DEFAULT_SETTINGS = {
    "mode": "individual",
    "transition_duration": 1.2,
    "transition_fps": 60,
    "auto_change_enabled": False,
    "auto_change_interval": 300,
    "idle_timeout": 300,
    "screensaver_password": None,
    "monitor_assignments": {},
    "shortcuts_enabled": True,
    "shortcuts": {
        "next": "<ctrl>+<shift>+n",
        "prev": "<ctrl>+<shift>+p",
        "random": "<ctrl>+<shift>+r",
        "toggle": "<ctrl>+<shift>+t"
    },
    "minimize_to_tray": False
}

# Windows constants
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002
SW_HIDE = 0
SW_SHOW = 5

SetLayeredWindowAttributes = ctypes.windll.user32.SetLayeredWindowAttributes

# ==================== GLOBAL STATE ====================

class AppState:
    def __init__(self):
        self.videos = []
        self.current_index = 0
        self.processes = {}
        self.monitors = []
        self.current_mode = DEFAULT_SETTINGS["mode"]
        self.monitor_assignments = {}
        self.transition_duration = DEFAULT_SETTINGS["transition_duration"]
        self.auto_change_enabled = DEFAULT_SETTINGS["auto_change_enabled"]
        self.auto_change_interval = DEFAULT_SETTINGS["auto_change_interval"]
        self.idle_timeout = DEFAULT_SETTINGS["idle_timeout"]
        self.screensaver_password = DEFAULT_SETTINGS["screensaver_password"]
        self.shortcuts_enabled = DEFAULT_SETTINGS["shortcuts_enabled"]
        self.shortcuts = DEFAULT_SETTINGS["shortcuts"].copy()
        self.minimize_to_tray = DEFAULT_SETTINGS["minimize_to_tray"]
        self.transition_active = False
        self.paused = False
        self.log_entries = deque(maxlen=1000)
        self.screensaver_active = False
        self.screensaver_processes = {}

    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] [{level}] {message}"
        self.log_entries.append(entry)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except:
            pass
        print(entry)

state = AppState()

# ==================== KEYBOARD HANDLER ====================

class KeyboardHandler(QObject):
    """Global keyboard shortcut handler using HotKey with canonical keys"""
    next_signal = pyqtSignal()
    prev_signal = pyqtSignal()
    random_signal = pyqtSignal()
    toggle_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.listener = None
        self.hotkeys = []
        self.enabled = True
        self._pressed_keys = set()

    def start(self):
        if not PYNPUT_AVAILABLE:
            return False
        try:
            self._setup_hotkeys()
            state.log("Keyboard shortcuts enabled")
            return True
        except Exception as e:
            state.log(f"Keyboard shortcut error: {e}", "ERROR")
            return False

    def _setup_hotkeys(self):
        """Setup hotkeys using HotKey class with canonical keys"""
        self.hotkeys = []

        # Map actions to callbacks
        actions = {
            'next': lambda: self.next_signal.emit(),
            'prev': lambda: self.prev_signal.emit(),
            'random': lambda: self.random_signal.emit(),
            'toggle': lambda: self.toggle_signal.emit()
        }

        for action, shortcut_str in state.shortcuts.items():
            if action in actions:
                try:
                    # Parse the shortcut string
                    keys = keyboard.HotKey.parse(shortcut_str)
                    hotkey = keyboard.HotKey(keys, actions[action])
                    self.hotkeys.append(hotkey)
                    state.log(f"Registered shortcut: {shortcut_str} -> {action}")
                except Exception as e:
                    state.log(f"Failed to parse shortcut '{shortcut_str}': {e}", "ERROR")

        if self.hotkeys:
            # Create listener with canonical key handling
            self.listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
                suppress=False
            )
            self.listener.start()

    def _on_press(self, key):
        """Handle key press with canonical normalization"""
        if not self.enabled:
            return

        # Get canonical key to normalize modifiers
        canonical_key = self.listener.canonical(key)
        self._pressed_keys.add(canonical_key)

        # Check all hotkeys
        for hotkey in self.hotkeys:
            hotkey.press(canonical_key)

    def _on_release(self, key):
        """Handle key release with canonical normalization"""
        if not self.enabled:
            return

        canonical_key = self.listener.canonical(key)

        # Remove from pressed keys
        try:
            self._pressed_keys.remove(canonical_key)
        except KeyError:
            pass

        # Update hotkeys
        for hotkey in self.hotkeys:
            hotkey.release(canonical_key)

    def stop(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.hotkeys = []
        self._pressed_keys.clear()

    def update_shortcuts(self):
        """Restart with new shortcuts"""
        self.stop()
        if self.enabled and PYNPUT_AVAILABLE:
            self._setup_hotkeys()

    def set_enabled(self, enabled):
        self.enabled = enabled
        if enabled:
            self.update_shortcuts()
        else:
            self.stop()

# ==================== MPV & WINDOW MANAGEMENT ====================

def check_mpv():
    try:
        subprocess.run(["mpv", "--version"], capture_output=True, check=True)
        return True
    except:
        return False

def find_window(pid, timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        hwnds = []
        def callback(hwnd, _):
            try:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid:
                    hwnds.append(hwnd)
            except:
                pass
        win32gui.EnumWindows(callback, None)
        if hwnds:
            return hwnds[0]
        time.sleep(0.1)
    return None

def set_window_opacity(hwnd, opacity):
    try:
        SetLayeredWindowAttributes(hwnd, 0, int(opacity), LWA_ALPHA)
        return True
    except:
        return False

def prepare_window_styles(hwnd, for_screensaver=False):
    try:
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        style |= win32con.WS_DISABLED
        style &= ~(win32con.WS_VISIBLE | win32con.WS_CAPTION | win32con.WS_THICKFRAME | 
                   win32con.WS_SYSMENU | win32con.WS_MAXIMIZEBOX | win32con.WS_MINIMIZEBOX)
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)

        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex_style |= (WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED)
        if for_screensaver:
            ex_style |= win32con.WS_EX_TOPMOST
        ex_style &= ~win32con.WS_EX_CLIENTEDGE
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
        return True
    except:
        return False

def get_monitor_geometry(monitor_idx=None):
    if monitor_idx is not None and 0 <= monitor_idx < len(state.monitors):
        m = state.monitors[monitor_idx]
        return (m['x'], m['y'], m['width'], m['height'])

    if not state.monitors:
        return (0, 0, 1920, 1080)

    min_x = min(m['x'] for m in state.monitors)
    min_y = min(m['y'] for m in state.monitors)
    max_x = max(m['x'] + m['width'] for m in state.monitors)
    max_y = max(m['y'] + m['height'] for m in state.monitors)
    return (min_x, min_y, max_x - min_x, max_y - min_y)

def launch_mpv(video, x, y, width, height):
    geometry = f"{width}x{height}+{x}+{y}"

    args = [
        "mpv",
        "--loop-file=inf",
        "--no-audio",
        "--border=no",
        "--force-window=immediate",
        "--keepaspect=no",
        "--hwdec=auto",
        "--video-sync=display-resample",
        "--interpolation",
        "--tscale=oversample",
        "--no-input-default-bindings",
        "--no-osc",
        "--no-osd-bar",
        "--really-quiet",
        "--ontop=no",
        "--geometry=" + geometry,
        "--force-window-position",
        video
    ]

    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
    return subprocess.Popen(args, creationflags=creationflags)

def setup_wallpaper_window(p, monitor_idx, for_screensaver=False, initial_opacity=255):
    try:
        timeout = 15 if monitor_idx > 0 else 10
        hwnd = find_window(p.pid, timeout=timeout)

        if not hwnd:
            return None, None

        x, y, w, h = get_monitor_geometry(monitor_idx)

        win32gui.ShowWindow(hwnd, SW_HIDE)
        prepare_window_styles(hwnd, for_screensaver)
        time.sleep(0.4)

        if not win32gui.IsWindow(hwnd):
            return None, None

        z_order = win32con.HWND_TOPMOST if for_screensaver else win32con.HWND_BOTTOM

        set_window_opacity(hwnd, initial_opacity)
        flags = (win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED | 
                0x0200 | win32con.SWP_SHOWWINDOW)
        win32gui.SetWindowPos(hwnd, z_order, x, y, w, h, flags)
        time.sleep(0.05)

        win32gui.RedrawWindow(hwnd, None, None, 
                             win32con.RDW_INVALIDATE | win32con.RDW_UPDATENOW)

        if not for_screensaver:
            def keep_at_bottom():
                while True:
                    try:
                        if p.poll() is not None:
                            break
                        if not win32gui.IsWindow(hwnd):
                            break
                        win32gui.SetWindowPos(hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | 
                                            win32con.SWP_NOACTIVATE | 0x0200)
                        time.sleep(2)
                    except:
                        break
            threading.Thread(target=keep_at_bottom, daemon=True).start()

        return hwnd, p

    except Exception as e:
        state.log(f"Error setting up window: {e}", "ERROR")
        return None, None

# ==================== WALLPAPER CONTROL ====================

def detect_monitors():
    state.monitors = []
    for m in get_monitors():
        state.monitors.append({
            'x': m.x, 'y': m.y,
            'width': m.width, 'height': m.height,
            'is_primary': m.is_primary
        })
    state.monitors.sort(key=lambda x: x['x'])
    state.log(f"Detected {len(state.monitors)} monitor(s)")
    return state.monitors

def stop_wallpapers():
    for idx, procs in list(state.processes.items()):
        for p in procs:
            try:
                p.terminate()
                try:
                    p.wait(timeout=2)
                except:
                    p.kill()
            except:
                pass
    state.processes = {}
    state.log("Wallpapers stopped")

def instant_switch_monitor(monitor_idx, new_video_idx):
    if not state.videos or new_video_idx >= len(state.videos):
        return False

    new_video = state.videos[new_video_idx]
    state.log(f"Monitor {monitor_idx}: Switch to {os.path.basename(new_video)}")

    if monitor_idx in state.processes:
        for p in state.processes[monitor_idx]:
            try:
                p.terminate()
                p.wait(timeout=1)
            except:
                p.kill()
    state.processes[monitor_idx] = []

    try:
        x, y, w, h = get_monitor_geometry(monitor_idx)
        p = launch_mpv(new_video, x, y, w, h)

        hwnd, p = setup_wallpaper_window(p, monitor_idx)
        if hwnd:
            state.processes[monitor_idx] = [p]
            return True
        return False

    except Exception as e:
        state.log(f"Monitor {monitor_idx}: Switch error - {e}", "ERROR")
        return False

def crossfade_monitor(monitor_idx, new_video_idx):
    if not state.videos or new_video_idx >= len(state.videos):
        return False

    if state.transition_active:
        wait_count = 0
        while state.transition_active and wait_count < 50:
            time.sleep(0.1)
            wait_count += 1

    state.transition_active = True
    new_video = state.videos[new_video_idx]
    state.log(f"Monitor {monitor_idx}: Crossfading to {os.path.basename(new_video)}")

    try:
        x, y, w, h = get_monitor_geometry(monitor_idx)

        old_procs = state.processes.get(monitor_idx, []).copy()

        new_p = launch_mpv(new_video, x, y, w, h)
        new_hwnd = find_window(new_p.pid, timeout=10)

        if not new_hwnd:
            state.log(f"Monitor {monitor_idx}: Failed to create new window", "ERROR")
            state.transition_active = False
            return False

        win32gui.ShowWindow(new_hwnd, SW_HIDE)
        prepare_window_styles(new_hwnd)
        time.sleep(0.5)

        if not win32gui.IsWindow(new_hwnd):
            state.transition_active = False
            return False

        win32gui.SetWindowPos(new_hwnd, win32con.HWND_BOTTOM, x, y, w, h,
                             win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED | 
                             0x0200 | win32con.SWP_HIDEWINDOW)
        set_window_opacity(new_hwnd, 0)

        if monitor_idx not in state.processes:
            state.processes[monitor_idx] = []
        state.processes[monitor_idx].append(new_p)

        for old_p in old_procs:
            try:
                old_hwnd = find_window(old_p.pid, timeout=1)
                if old_hwnd:
                    set_window_opacity(old_hwnd, 255)
            except:
                pass

        win32gui.SetWindowPos(new_hwnd, win32con.HWND_BOTTOM, x, y, w, h,
                             win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED | 
                             0x0200 | win32con.SWP_SHOWWINDOW)

        time.sleep(0.05)

        steps = int(state.transition_duration * DEFAULT_SETTINGS["transition_fps"])
        step_duration = state.transition_duration / steps

        for i in range(steps + 1):
            progress = i / steps
            eased = progress * progress * (3 - 2 * progress)

            new_opacity = int(255 * eased)
            old_opacity = int(255 * (1 - eased))

            set_window_opacity(new_hwnd, new_opacity)

            for old_p in old_procs:
                try:
                    old_hwnd = find_window(old_p.pid, timeout=0.5)
                    if old_hwnd:
                        set_window_opacity(old_hwnd, old_opacity)
                except:
                    pass

            time.sleep(step_duration)

        for old_p in old_procs:
            try:
                old_hwnd = find_window(old_p.pid, timeout=0.5)
                if old_hwnd:
                    set_window_opacity(old_hwnd, 0)
                    time.sleep(0.1)

                old_p.terminate()
                try:
                    old_p.wait(timeout=1)
                except:
                    old_p.kill()
            except:
                pass

        set_window_opacity(new_hwnd, 255)
        win32gui.SetWindowPos(new_hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                             win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | 
                             win32con.SWP_NOACTIVATE | 0x0200)

        state.processes[monitor_idx] = [p for p in state.processes[monitor_idx] if p.poll() is None]

        state.log(f"Monitor {monitor_idx}: Transition complete")
        state.transition_active = False
        return True

    except Exception as e:
        state.log(f"Monitor {monitor_idx}: Transition error - {e}", "ERROR")
        state.transition_active = False
        return False

def start_wallpaper(video=None, use_transition=False):
    stop_wallpapers()

    if not state.videos:
        return

    if state.current_mode == "span":
        video = video or state.videos[state.current_index]
        x, y, w, h = get_monitor_geometry()
        try:
            p = launch_mpv(video, x, y, w, h)
            hwnd, p = setup_wallpaper_window(p, 0)
            if hwnd:
                state.processes = {0: [p]}
        except Exception as e:
            state.log(f"Span mode error: {e}", "ERROR")

    elif state.current_mode in ["duplicate", "individual"]:
        for i in range(len(state.monitors)):
            if state.current_mode == "duplicate":
                video_idx = state.current_index
            else:
                video_idx = state.monitor_assignments.get(i, i) % len(state.videos)

            instant_switch_monitor(i, video_idx)
            if i < len(state.monitors) - 1:
                time.sleep(0.3)

def next_wallpaper():
    if not state.videos:
        return
    state.current_index = (state.current_index + 1) % len(state.videos)
    if state.current_mode == "individual":
        for i in range(len(state.monitors)):
            new_idx = (state.monitor_assignments.get(i, 0) + 1) % len(state.videos)
            state.monitor_assignments[i] = new_idx
            threading.Thread(target=crossfade_monitor, args=(i, new_idx), daemon=True).start()
        save_config()
    else:
        start_wallpaper(use_transition=True)
    state.log("Next wallpaper")

def prev_wallpaper():
    if not state.videos:
        return
    state.current_index = (state.current_index - 1) % len(state.videos)
    if state.current_mode == "individual":
        for i in range(len(state.monitors)):
            new_idx = (state.monitor_assignments.get(i, 0) - 1) % len(state.videos)
            state.monitor_assignments[i] = new_idx
            threading.Thread(target=crossfade_monitor, args=(i, new_idx), daemon=True).start()
        save_config()
    else:
        start_wallpaper(use_transition=True)
    state.log("Previous wallpaper")

def random_wallpaper():
    if not state.videos:
        return
    if state.current_mode == "individual":
        for i in range(len(state.monitors)):
            new_idx = random.randint(0, len(state.videos) - 1)
            state.monitor_assignments[i] = new_idx
            threading.Thread(target=crossfade_monitor, args=(i, new_idx), daemon=True).start()
        save_config()
    else:
        state.current_index = random.randint(0, len(state.videos) - 1)
        start_wallpaper(use_transition=True)
    state.log("Random wallpaper")

# ==================== CONFIG & DATA ====================

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                state.current_mode = config.get('mode', DEFAULT_SETTINGS["mode"])
                state.monitor_assignments = {int(k): v for k, v in config.get('assignments', {}).items()}
                state.idle_timeout = config.get('idle_timeout', DEFAULT_SETTINGS["idle_timeout"])
                state.screensaver_password = config.get('screensaver_password', DEFAULT_SETTINGS["screensaver_password"])
                state.transition_duration = config.get('transition_duration', DEFAULT_SETTINGS["transition_duration"])
                state.auto_change_enabled = config.get('auto_change_enabled', DEFAULT_SETTINGS["auto_change_enabled"])
                state.auto_change_interval = config.get('auto_change_interval', DEFAULT_SETTINGS["auto_change_interval"])
                state.shortcuts_enabled = config.get('shortcuts_enabled', DEFAULT_SETTINGS["shortcuts_enabled"])
                state.shortcuts = config.get('shortcuts', DEFAULT_SETTINGS["shortcuts"]).copy()
                state.minimize_to_tray = config.get('minimize_to_tray', DEFAULT_SETTINGS["minimize_to_tray"])
        except Exception as e:
            state.log(f"Config load error: {e}", "ERROR")

def save_config():
    config = {
        'mode': state.current_mode,
        'assignments': state.monitor_assignments,
        'idle_timeout': state.idle_timeout,
        'screensaver_password': state.screensaver_password,
        'transition_duration': state.transition_duration,
        'auto_change_enabled': state.auto_change_enabled,
        'auto_change_interval': state.auto_change_interval,
        'shortcuts_enabled': state.shortcuts_enabled,
        'shortcuts': state.shortcuts,
        'minimize_to_tray': state.minimize_to_tray
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        state.log(f"Config save error: {e}", "ERROR")

def load_videos():
    state.videos = []
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)
    for f in os.listdir(SAVE_DIR):
        if f.lower().endswith(VIDEO_EXTENSIONS):
            state.videos.append(os.path.join(SAVE_DIR, f))
    state.videos.sort()
    state.log(f"Loaded {len(state.videos)} video(s)")
    return state.videos

# ==================== MOEWALLS SCRAPER ====================

def search_wallpapers(keyword):
    url = f"{BASE_URL}/?s={quote(keyword)}"
    r = requests.get(url, headers=HEADERS)
    soup = BeautifulSoup(r.text, "html.parser")
    results = []

    articles = soup.find_all("article")
    for article in articles:
        link = article.find("a", href=True)
        img = article.find("img")
        if not link or not img:
            continue

        title = img.get("alt", "Wallpaper")
        page = link["href"]
        thumb = img.get("src")

        results.append({
            "title": title,
            "page": page if page.startswith("http") else urljoin(BASE_URL, page),
            "thumbnail": thumb
        })

    return results

def get_download_link(page_url):
    r = requests.get(page_url, headers=HEADERS)
    soup = BeautifulSoup(r.text, "html.parser")

    for a in soup.find_all("a"):
        if "download" in a.text.lower():
            href = a.get("href")
            if href:
                return urljoin(BASE_URL, href)
    return None

def download_video(url, progress_callback=None):
    filename = url.split("/")[-1].split("?")[0]
    if not filename:
        filename = "wallpaper.mp4"
    filepath = os.path.join(SAVE_DIR, filename)

    r = requests.get(url, headers=HEADERS, stream=True)
    total_size = int(r.headers.get('content-length', 0))

    downloaded = 0
    with open(filepath, "wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size > 0:
                    progress_callback(int(downloaded * 100 / total_size))

    return filepath

# ==================== WORKER THREADS ====================

class SearchThread(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, keyword):
        super().__init__()
        self.keyword = keyword

    def run(self):
        try:
            results = search_wallpapers(self.keyword)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

class DownloadThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, page_url):
        super().__init__()
        self.page_url = page_url

    def run(self):
        try:
            dl_url = get_download_link(self.page_url)
            if not dl_url:
                self.error.emit("Download link not found")
                return

            filepath = download_video(dl_url, lambda p: self.progress.emit(p))
            self.finished.emit(filepath)
        except Exception as e:
            self.error.emit(str(e))

class AutoChangeThread(QThread):
    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        while self.running and state.auto_change_enabled:
            time.sleep(state.auto_change_interval)
            if self.running and state.auto_change_enabled and state.videos:
                if state.current_mode == "individual":
                    next_wallpaper()
                else:
                    random_wallpaper()

    def stop(self):
        self.running = False

# ==================== GUI COMPONENTS ====================

class WallpaperCard(QFrame):
    clicked = pyqtSignal(dict)
    download_clicked = pyqtSignal(dict)
    set_clicked = pyqtSignal(str)

    def __init__(self, video_path, is_local=True, online_data=None):
        super().__init__()
        self.video_path = video_path
        self.is_local = is_local
        self.online_data = online_data
        self.setup_ui()

    def setup_ui(self):
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet("""
            WallpaperCard {
                background-color: #2d2d2d;
                border-radius: 8px;
                border: 1px solid #3d3d3d;
            }
            WallpaperCard:hover {
                border: 1px solid #00d4aa;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(200, 120)
        self.thumb_label.setStyleSheet("background-color: #1e1e1e; border-radius: 4px;")
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self.is_local:
            self.thumb_label.setText("🎬")
            font = self.thumb_label.font()
            font.setPointSize(24)
            self.thumb_label.setFont(font)
        else:
            self.thumb_label.setText("⏳")
            self.load_thumbnail()

        layout.addWidget(self.thumb_label, alignment=Qt.AlignmentFlag.AlignCenter)

        title = os.path.basename(self.video_path) if self.is_local else self.online_data.get("title", "Unknown")
        self.title_label = QLabel(title[:30] + "..." if len(title) > 30 else title)
        self.title_label.setStyleSheet("color: white; font-weight: bold;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        btn_layout = QHBoxLayout()

        if self.is_local:
            set_btn = QPushButton("Set")
            set_btn.setStyleSheet("""
                QPushButton {
                    background-color: #00d4aa;
                    color: black;
                    border: none;
                    padding: 5px 15px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #00b894;
                }
            """)
            set_btn.clicked.connect(lambda: self.set_clicked.emit(self.video_path))
            btn_layout.addWidget(set_btn)
        else:
            dl_btn = QPushButton("Download")
            dl_btn.setStyleSheet("""
                QPushButton {
                    background-color: #00d4aa;
                    color: black;
                    border: none;
                    padding: 5px 15px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #00b894;
                }
            """)
            dl_btn.clicked.connect(lambda: self.download_clicked.emit(self.online_data))
            btn_layout.addWidget(dl_btn)

        layout.addLayout(btn_layout)
        self.setFixedWidth(240)

    def load_thumbnail(self):
        def fetch():
            try:
                url = self.online_data.get("thumbnail")
                if url:
                    r = requests.get(url, headers=HEADERS)
                    img = Image.open(BytesIO(r.content))
                    img = img.resize((200, 120), Image.Resampling.LANCZOS)

                    img_bytes = BytesIO()
                    img.save(img_bytes, format='PNG')
                    pixmap = QPixmap()
                    pixmap.loadFromData(img_bytes.getvalue())

                    self.thumb_label.setPixmap(pixmap)
            except:
                self.thumb_label.setText("❌")

        threading.Thread(target=fetch, daemon=True).start()

    def mousePressEvent(self, event):
        self.clicked.emit({
            "path": self.video_path,
            "is_local": self.is_local,
            "data": self.online_data
        })

class MoeWallsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.search_results = []
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        search_layout = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search anime wallpapers (e.g., 'rain', 'cyberpunk', 'nature')...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                padding: 12px;
                border: 2px solid #3d3d3d;
                border-radius: 6px;
                background-color: #2d2d2d;
                color: white;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 2px solid #00d4aa;
            }
        """)
        self.search_input.returnPressed.connect(self.do_search)
        search_layout.addWidget(self.search_input)

        self.search_btn = QPushButton("🔍 Search")
        self.search_btn.setStyleSheet("""
            QPushButton {
                background-color: #00d4aa;
                color: black;
                border: none;
                padding: 12px 24px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #00b894;
            }
        """)
        self.search_btn.clicked.connect(self.do_search)
        search_layout.addWidget(self.search_btn)

        layout.addLayout(search_layout)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: 2px solid #3d3d3d;
                border-radius: 5px;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #00d4aa;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        self.results_container = QWidget()
        self.results_layout = QGridLayout(self.results_container)
        self.results_layout.setSpacing(15)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self.results_container)
        layout.addWidget(scroll)

        self.status_label = QLabel("Enter a search term to find wallpapers")
        self.status_label.setStyleSheet("color: #a0a0a0; padding: 10px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

    def do_search(self):
        keyword = self.search_input.text().strip()
        if not keyword:
            return

        self.status_label.setText(f"Searching for '{keyword}'...")
        self.search_btn.setEnabled(False)

        self.search_thread = SearchThread(keyword)
        self.search_thread.finished.connect(self.on_search_finished)
        self.search_thread.error.connect(self.on_search_error)
        self.search_thread.start()

    def on_search_finished(self, results):
        self.search_btn.setEnabled(True)
        self.search_results = results

        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not results:
            self.status_label.setText("No results found. Try a different search term.")
            return

        self.status_label.setText(f"Found {len(results)} wallpapers")

        for i, result in enumerate(results):
            card = WallpaperCard(
                video_path=result["page"],
                is_local=False,
                online_data=result
            )
            card.download_clicked.connect(self.start_download)
            row = i // 3
            col = i % 3
            self.results_layout.addWidget(card, row, col)

    def on_search_error(self, error):
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"Error: {error}")
        QMessageBox.warning(self, "Search Error", str(error))

    def start_download(self, data):
        self.progress.setVisible(True)
        self.progress.setValue(0)

        self.download_thread = DownloadThread(data["page"])
        self.download_thread.progress.connect(self.progress.setValue)
        self.download_thread.finished.connect(self.on_download_finished)
        self.download_thread.error.connect(self.on_download_error)
        self.download_thread.start()

    def on_download_finished(self, filepath):
        self.progress.setVisible(False)
        state.log(f"Downloaded: {os.path.basename(filepath)}")
        load_videos()

        if self.parent:
            self.parent.refresh_library()

        QMessageBox.information(self, "Download Complete", f"Saved to: {os.path.basename(filepath)}\n\nAdded to your library!")

    def on_download_error(self, error):
        self.progress.setVisible(False)
        QMessageBox.warning(self, "Download Error", str(error))

class LibraryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setup_ui()
        self.refresh_library()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        controls = QHBoxLayout()

        self.info_label = QLabel("0 videos in library")
        self.info_label.setStyleSheet("color: #a0a0a0;")
        controls.addWidget(self.info_label)

        controls.addStretch()

        add_btn = QPushButton("+ Add Videos")
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d3d;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
            }
        """)
        add_btn.clicked.connect(self.add_videos)
        controls.addWidget(add_btn)

        open_btn = QPushButton("📁 Open Folder")
        open_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d3d;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
            }
        """)
        open_btn.clicked.connect(self.open_folder)
        controls.addWidget(open_btn)

        layout.addLayout(controls)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        self.library_container = QWidget()
        self.library_layout = QGridLayout(self.library_container)
        self.library_layout.setSpacing(15)
        self.library_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self.library_container)
        layout.addWidget(scroll)

        actions_box = QGroupBox("Quick Actions")
        actions_box.setStyleSheet("""
            QGroupBox {
                color: #00d4aa;
                font-weight: bold;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        actions_layout = QHBoxLayout(actions_box)

        prev_btn = QPushButton("⏮ Previous")
        prev_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d3d;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
            }
        """)
        prev_btn.clicked.connect(prev_wallpaper)
        actions_layout.addWidget(prev_btn)

        next_btn = QPushButton("▶ Next Wallpaper")
        next_btn.setStyleSheet("""
            QPushButton {
                background-color: #00d4aa;
                color: black;
                border: none;
                padding: 10px 30px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00b894;
            }
        """)
        next_btn.clicked.connect(next_wallpaper)
        actions_layout.addWidget(next_btn)

        random_btn = QPushButton("🔀 Random")
        random_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d3d;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
            }
        """)
        random_btn.clicked.connect(random_wallpaper)
        actions_layout.addWidget(random_btn)

        layout.addWidget(actions_box)

    def refresh_library(self):
        while self.library_layout.count():
            item = self.library_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        load_videos()
        self.info_label.setText(f"{len(state.videos)} video(s) in library")

        for i, video_path in enumerate(state.videos):
            card = WallpaperCard(video_path, is_local=True)
            card.set_clicked.connect(self.set_wallpaper)
            row = i // 3
            col = i % 3
            self.library_layout.addWidget(card, row, col)

    def set_wallpaper(self, video_path):
        try:
            idx = state.videos.index(video_path)
            state.current_index = idx

            if state.current_mode == "individual":
                for i in range(len(state.monitors)):
                    state.monitor_assignments[i] = idx
                    threading.Thread(target=crossfade_monitor, args=(i, idx), daemon=True).start()
                save_config()
            else:
                start_wallpaper(video_path, use_transition=True)

            state.log(f"Set wallpaper: {os.path.basename(video_path)}")
        except ValueError:
            QMessageBox.warning(self, "Error", "Video not found in library")

    def add_videos(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Videos",
            "",
            "Videos (*.mp4 *.webm *.mkv);;All Files (*)"
        )

        if files:
            import shutil
            added = 0
            for f in files:
                dest = os.path.join(SAVE_DIR, os.path.basename(f))
                if not os.path.exists(dest):
                    shutil.copy2(f, dest)
                    added += 1

            if added > 0:
                self.refresh_library()
                QMessageBox.information(self, "Success", f"Added {added} video(s)")

    def open_folder(self):
        if not os.path.exists(SAVE_DIR):
            os.makedirs(SAVE_DIR)
        os.startfile(SAVE_DIR)

class DisplayTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)

        mode_box = QGroupBox("Display Mode")
        mode_box.setStyleSheet("""
            QGroupBox {
                color: #00d4aa;
                font-weight: bold;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        mode_layout = QVBoxLayout(mode_box)

        self.mode_group = QButtonGroup(self)

        modes = [
            ("span", "Span", "One video across all monitors"),
            ("duplicate", "Duplicate", "Same video on all monitors"),
            ("individual", "Individual", "Different video per monitor")
        ]

        for value, name, desc in modes:
            row = QHBoxLayout()
            rb = QRadioButton(name)
            rb.setStyleSheet("color: white; font-size: 12px;")
            self.mode_group.addButton(rb)
            rb.mode_value = value
            row.addWidget(rb)

            lbl = QLabel(desc)
            lbl.setStyleSheet("color: #a0a0a0; font-size: 11px;")
            row.addWidget(lbl)
            row.addStretch()

            mode_layout.addLayout(row)

        self.mode_group.buttonClicked.connect(self.on_mode_changed)
        layout.addWidget(mode_box)

        self.monitor_box = QGroupBox("Per-Monitor Assignment")
        self.monitor_box.setStyleSheet(mode_box.styleSheet())
        self.monitor_layout = QVBoxLayout(self.monitor_box)
        self.monitor_box.setVisible(False)
        layout.addWidget(self.monitor_box)

        trans_box = QGroupBox("Transition Effects")
        trans_box.setStyleSheet(mode_box.styleSheet())
        trans_layout = QVBoxLayout(trans_box)

        duration_row = QHBoxLayout()
        duration_row.addWidget(QLabel("Duration:"))
        self.duration_slider = QSlider(Qt.Orientation.Horizontal)
        self.duration_slider.setRange(5, 30)
        self.duration_slider.setValue(12)
        self.duration_slider.valueChanged.connect(self.on_duration_changed)
        duration_row.addWidget(self.duration_slider)

        self.duration_label = QLabel("1.2s")
        self.duration_label.setStyleSheet("color: #00d4aa; font-weight: bold;")
        duration_row.addWidget(self.duration_label)

        trans_layout.addLayout(duration_row)

        test_btn = QPushButton("▶ Test Transition")
        test_btn.setStyleSheet("""
            QPushButton {
                background-color: #00d4aa;
                color: black;
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00b894;
            }
        """)
        test_btn.clicked.connect(self.test_transition)
        trans_layout.addWidget(test_btn)

        layout.addWidget(trans_box)

        auto_box = QGroupBox("Auto-Change Timer")
        auto_box.setStyleSheet(mode_box.styleSheet())
        auto_layout = QVBoxLayout(auto_box)

        self.auto_check = QCheckBox("Enable Auto-Change")
        self.auto_check.setStyleSheet("color: white; font-size: 12px;")
        self.auto_check.stateChanged.connect(self.on_auto_changed)
        auto_layout.addWidget(self.auto_check)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Interval (minutes):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 120)
        self.interval_spin.setValue(5)
        self.interval_spin.valueChanged.connect(self.on_interval_changed)
        interval_row.addWidget(self.interval_spin)
        interval_row.addStretch()

        auto_layout.addLayout(interval_row)
        layout.addWidget(auto_box)

        layout.addStretch()

    def load_settings(self):
        for btn in self.mode_group.buttons():
            if btn.mode_value == state.current_mode:
                btn.setChecked(True)
                break

        self.duration_slider.setValue(int(state.transition_duration * 10))
        self.duration_label.setText(f"{state.transition_duration:.1f}s")

        self.auto_check.setChecked(state.auto_change_enabled)
        self.interval_spin.setValue(state.auto_change_interval // 60)

        self.refresh_monitor_assignment()

    def refresh_monitor_assignment(self):
        while self.monitor_layout.count():
            item = self.monitor_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if state.current_mode != "individual" or len(state.monitors) <= 1:
            self.monitor_box.setVisible(False)
            return

        self.monitor_box.setVisible(True)

        for i, m in enumerate(state.monitors):
            row = QHBoxLayout()

            info = f"Monitor {i+1}"
            if m.get('is_primary'):
                info += " (Primary)"
            info += f" - {m['width']}x{m['height']}"

            row.addWidget(QLabel(info))

            combo = QComboBox()
            combo.setStyleSheet("""
                QComboBox {
                    background-color: #2d2d2d;
                    color: white;
                    border: 1px solid #3d3d3d;
                    padding: 5px;
                    min-width: 200px;
                }
            """)

            for v in state.videos:
                combo.addItem(os.path.basename(v))

            current = state.monitor_assignments.get(i, i) % len(state.videos) if state.videos else 0
            combo.setCurrentIndex(current)
            combo.currentIndexChanged.connect(lambda idx, mon=i: self.on_monitor_video_changed(mon, idx))

            row.addWidget(combo)
            row.addStretch()

            self.monitor_layout.addLayout(row)

    def on_mode_changed(self, btn):
        mode = btn.mode_value
        state.current_mode = mode
        save_config()
        state.log(f"Mode changed to: {mode}")

        self.refresh_monitor_assignment()
        start_wallpaper(use_transition=False)

    def on_duration_changed(self, value):
        seconds = value / 10.0
        state.transition_duration = seconds
        self.duration_label.setText(f"{seconds:.1f}s")
        save_config()

    def on_auto_changed(self, state_val):
        enabled = bool(state_val)
        state.auto_change_enabled = enabled
        save_config()

        if enabled:
            if not hasattr(self, 'auto_thread') or not self.auto_thread.isRunning():
                self.auto_thread = AutoChangeThread()
                self.auto_thread.start()
            state.log(f"Auto-change enabled: {state.auto_change_interval//60}min")
        else:
            if hasattr(self, 'auto_thread'):
                self.auto_thread.stop()
            state.log("Auto-change disabled")

    def on_interval_changed(self, value):
        state.auto_change_interval = value * 60
        save_config()

    def on_monitor_video_changed(self, monitor_idx, video_idx):
        if 0 <= video_idx < len(state.videos):
            state.monitor_assignments[monitor_idx] = video_idx
            save_config()
            threading.Thread(target=crossfade_monitor, args=(monitor_idx, video_idx), daemon=True).start()

    def test_transition(self):
        if len(state.videos) < 2:
            QMessageBox.warning(self, "Need More Videos", "Add at least 2 videos to test transitions")
            return

        for i in range(len(state.monitors)):
            new_idx = (state.monitor_assignments.get(i, 0) + 1) % len(state.videos)
            state.monitor_assignments[i] = new_idx
            threading.Thread(target=crossfade_monitor, args=(i, new_idx), daemon=True).start()
        save_config()
        self.refresh_monitor_assignment()

class LogTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.refresh_log()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_log)
        self.timer.start(1000)

    def setup_ui(self):
        layout = QVBoxLayout(self)

        controls = QHBoxLayout()

        clear_btn = QPushButton("🗑 Clear")
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d3d;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
            }
        """)
        clear_btn.clicked.connect(self.clear_log)
        controls.addWidget(clear_btn)

        copy_btn = QPushButton("📋 Copy")
        copy_btn.setStyleSheet(clear_btn.styleSheet())
        copy_btn.clicked.connect(self.copy_log)
        controls.addWidget(copy_btn)

        controls.addStretch()
        layout.addLayout(controls)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d0d;
                color: #00d4aa;
                border: none;
                font-family: Consolas, monospace;
                font-size: 11px;
                padding: 10px;
            }
        """)
        layout.addWidget(self.log_text)

    def refresh_log(self):
        text = "\n".join(state.log_entries)
        self.log_text.setPlainText(text)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def clear_log(self):
        state.log_entries.clear()
        try:
            if os.path.exists(LOG_FILE):
                os.remove(LOG_FILE)
        except:
            pass
        state.log("Log cleared")
        self.refresh_log()

    def copy_log(self):
        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(list(state.log_entries)))
        QMessageBox.information(self, "Copied", "Log copied to clipboard")

class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.shortcut_edits = {}
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)

        general_box = QGroupBox("General")
        general_box.setStyleSheet("""
            QGroupBox {
                color: #00d4aa;
                font-weight: bold;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        general_layout = QVBoxLayout(general_box)

        self.tray_start_check = QCheckBox("Minimize to tray on startup")
        self.tray_start_check.setStyleSheet("color: white;")
        general_layout.addWidget(self.tray_start_check)

        layout.addWidget(general_box)

        shortcuts_box = QGroupBox("Keyboard Shortcuts")
        shortcuts_box.setStyleSheet(general_box.styleSheet())
        shortcuts_layout = QVBoxLayout(shortcuts_box)

        self.shortcuts_enable_check = QCheckBox("Enable Global Hotkeys")
        self.shortcuts_enable_check.setStyleSheet("""
            QCheckBox {
                color: white;
                font-size: 13px;
                font-weight: bold;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
            }
        """)
        self.shortcuts_enable_check.stateChanged.connect(self.on_shortcuts_toggle)
        shortcuts_layout.addWidget(self.shortcuts_enable_check)

        info_label = QLabel("Click on a shortcut field and press your desired key combination")
        info_label.setStyleSheet("color: #a0a0a0; font-size: 11px; padding: 5px;")
        shortcuts_layout.addWidget(info_label)

        shortcuts_grid = QGridLayout()
        shortcuts_grid.setSpacing(10)

        shortcut_configs = [
            ("next", "Next Wallpaper", "Switch to next wallpaper"),
            ("prev", "Previous Wallpaper", "Switch to previous wallpaper"),
            ("random", "Random Wallpaper", "Select random wallpaper"),
            ("toggle", "Pause/Resume", "Pause or resume current wallpaper")
        ]

        for i, (key, title, description) in enumerate(shortcut_configs):
            label = QLabel(f"{title}:")
            label.setStyleSheet("color: white; font-weight: bold;")
            shortcuts_grid.addWidget(label, i, 0)

            edit = QKeySequenceEdit()
            edit.setStyleSheet("""
                QKeySequenceEdit {
                    background-color: #2d2d2d;
                    border: 2px solid #3d3d3d;
                    border-radius: 4px;
                    padding: 8px;
                    color: white;
                    min-width: 200px;
                }
                QKeySequenceEdit:focus {
                    border: 2px solid #00d4aa;
                }
            """)
            edit.setToolTip(description)
            edit.keySequenceChanged.connect(lambda seq, k=key: self.on_shortcut_changed(k, seq))
            self.shortcut_edits[key] = edit
            shortcuts_grid.addWidget(edit, i, 1)

            reset_btn = QPushButton("Reset")
            reset_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3d3d3d;
                    color: white;
                    border: none;
                    padding: 5px 12px;
                    border-radius: 4px;
                    font-size: 10px;
                }
                QPushButton:hover {
                    background-color: #4d4d4d;
                }
            """)
            reset_btn.clicked.connect(lambda checked, k=key: self.reset_shortcut(k))
            shortcuts_grid.addWidget(reset_btn, i, 2)

        shortcuts_layout.addLayout(shortcuts_grid)

        ref_label = QLabel("Default: Ctrl+Shift+N (Next) | Ctrl+Shift+P (Prev) | Ctrl+Shift+R (Random) | Ctrl+Shift+T (Toggle)")
        ref_label.setStyleSheet("color: #666; font-size: 10px; padding: 10px;")
        ref_label.setWordWrap(True)
        shortcuts_layout.addWidget(ref_label)

        layout.addWidget(shortcuts_box)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("💾 Save Settings")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #00d4aa;
                color: black;
                border: none;
                padding: 10px 24px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #00b894;
            }
        """)
        save_btn.clicked.connect(self.save_settings)
        btn_layout.addWidget(save_btn)

        reset_all_btn = QPushButton("Reset All to Default")
        reset_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d3d;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #ff6b6b;
                color: white;
            }
        """)
        reset_all_btn.clicked.connect(self.reset_all_shortcuts)
        btn_layout.addWidget(reset_all_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

    def load_settings(self):
        self.shortcuts_enable_check.setChecked(state.shortcuts_enabled)
        self.tray_start_check.setChecked(state.minimize_to_tray)

        for key, edit in self.shortcut_edits.items():
            shortcut_str = state.shortcuts.get(key, DEFAULT_SETTINGS["shortcuts"][key])
            qshortcut = self.pynput_to_qt(shortcut_str)
            edit.setKeySequence(qshortcut)

    def pynput_to_qt(self, pynput_str):
        parts = pynput_str.lower().replace("<", "").replace(">", "").split("+")
        qt_parts = []

        for part in parts:
            if part == "ctrl":
                qt_parts.append("Ctrl")
            elif part == "shift":
                qt_parts.append("Shift")
            elif part == "alt":
                qt_parts.append("Alt")
            elif part == "cmd" or part == "win":
                qt_parts.append("Meta")
            elif len(part) == 1:
                qt_parts.append(part.upper())

        return "+".join(qt_parts) if qt_parts else ""

    def qt_to_pynput(self, qt_str):
        if not qt_str:
            return ""

        parts = qt_str.split("+")
        pynput_parts = []

        for part in parts:
            p = part.strip().lower()
            if p == "ctrl":
                pynput_parts.append("<ctrl>")
            elif p == "shift":
                pynput_parts.append("<shift>")
            elif p == "alt":
                pynput_parts.append("<alt>")
            elif p == "meta":
                pynput_parts.append("<cmd>")
            elif len(p) == 1:
                pynput_parts.append(p)

        return "+".join(pynput_parts)

    def on_shortcut_changed(self, key, sequence):
        qt_str = sequence.toString()
        pynput_str = self.qt_to_pynput(qt_str)

        if pynput_str:
            state.shortcuts[key] = pynput_str
            state.log(f"Shortcut '{key}' changed to: {qt_str}")

    def reset_shortcut(self, key):
        default = DEFAULT_SETTINGS["shortcuts"][key]
        state.shortcuts[key] = default

        edit = self.shortcut_edits[key]
        qshortcut = self.pynput_to_qt(default)
        edit.setKeySequence(qshortcut)

        state.log(f"Shortcut '{key}' reset to default")

    def reset_all_shortcuts(self):
        reply = QMessageBox.question(
            self, "Reset Shortcuts",
            "Reset all keyboard shortcuts to default values?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            state.shortcuts = DEFAULT_SETTINGS["shortcuts"].copy()
            self.load_settings()
            save_config()

            if self.parent and hasattr(self.parent, 'restart_keyboard_handler'):
                self.parent.restart_keyboard_handler()

            QMessageBox.information(self, "Reset Complete", "All shortcuts reset to defaults!")

    def on_shortcuts_toggle(self, state_val):
        enabled = bool(state_val)
        state.shortcuts_enabled = enabled

        for edit in self.shortcut_edits.values():
            edit.setEnabled(enabled)

        if enabled:
            state.log("Keyboard shortcuts enabled")
        else:
            state.log("Keyboard shortcuts disabled")

        if self.parent and hasattr(self.parent, 'update_keyboard_handler'):
            self.parent.update_keyboard_handler()

    def save_settings(self):
        state.minimize_to_tray = self.tray_start_check.isChecked()
        save_config()

        if self.parent and hasattr(self.parent, 'restart_keyboard_handler'):
            self.parent.restart_keyboard_handler()

        QMessageBox.information(self, "Settings Saved", "Settings saved successfully!\n\nKeyboard shortcuts will take effect immediately.")

class VideoWallpaperManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Wallpaper Manager")
        self.setMinimumSize(1000, 800)

        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QWidget {
                background-color: #1e1e1e;
                color: #ffffff;
                font-family: 'Segoe UI', sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid #3d3d3d;
                background-color: #1e1e1e;
                border-radius: 6px;
            }
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #a0a0a0;
                padding: 12px 24px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background-color: #00d4aa;
                color: #000000;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected {
                background-color: #3d3d3d;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QScrollBar:vertical {
                background-color: #2d2d2d;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #4d4d4d;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #00d4aa;
            }
        """)

        self.setup_ui()
        self.setup_tray()

        if PYNPUT_AVAILABLE and state.shortcuts_enabled:
            self.keyboard_handler = KeyboardHandler()
            self.keyboard_handler.next_signal.connect(next_wallpaper)
            self.keyboard_handler.prev_signal.connect(prev_wallpaper)
            self.keyboard_handler.random_signal.connect(random_wallpaper)
            self.keyboard_handler.start()

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)

        if state.minimize_to_tray:
            QTimer.singleShot(0, self.hide_to_tray)

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header = QHBoxLayout()

        title = QLabel("🎬 Video Wallpaper Manager")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #00d4aa;")
        header.addWidget(title)

        header.addStretch()

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #a0a0a0;")
        header.addWidget(self.status_label)

        layout.addLayout(header)

        self.tabs = QTabWidget()

        self.discover_tab = MoeWallsTab(self)
        self.tabs.addTab(self.discover_tab, "🔍 Discover")

        self.library_tab = LibraryTab(self)
        self.tabs.addTab(self.library_tab, "📁 Library")

        self.display_tab = DisplayTab(self)
        self.tabs.addTab(self.display_tab, "🖥️ Display")

        self.log_tab = LogTab(self)
        self.tabs.addTab(self.log_tab, "📋 Log")

        self.settings_tab = SettingsTab(self)
        self.tabs.addTab(self.settings_tab, "⚙️ Settings")

        layout.addWidget(self.tabs)

        bottom = QHBoxLayout()

        self.info_bar = QLabel("0 monitors • 0 videos")
        self.info_bar.setStyleSheet("color: #a0a0a0; padding: 5px;")
        bottom.addWidget(self.info_bar)

        bottom.addStretch()

        hide_btn = QPushButton("⬇ Hide to Tray")
        hide_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d3d;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
            }
        """)
        hide_btn.clicked.connect(self.hide_to_tray)
        bottom.addWidget(hide_btn)

        layout.addLayout(bottom)

    def create_tray_icon(self):
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg_brush = QBrush(QColor("#1e1e1e"))
        painter.setBrush(bg_brush)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, size-4, size-4)

        accent_brush = QBrush(QColor("#00d4aa"))
        painter.setBrush(accent_brush)
        painter.drawEllipse(8, 8, size-16, size-16)

        painter.setBrush(QBrush(QColor("#ffffff")))

        play_size = 24
        center_x = size // 2
        center_y = size // 2

        points = [
            QPointF(center_x - play_size//3, center_y - play_size//2),
            QPointF(center_x - play_size//3, center_y + play_size//2),
            QPointF(center_x + play_size//2, center_y)
        ]

        polygon = QPolygonF(points)
        painter.drawPolygon(polygon)

        painter.end()
        return QIcon(pixmap)

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.create_tray_icon())

        menu = QMenu()

        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        menu.addAction(show_action)

        menu.addSeparator()

        next_action = QAction("Next Wallpaper", self)
        next_action.triggered.connect(next_wallpaper)
        menu.addAction(next_action)

        random_action = QAction("Random", self)
        random_action.triggered.connect(random_wallpaper)
        menu.addAction(random_action)

        menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()

    def hide_to_tray(self):
        self.hide()
        self.tray_icon.showMessage(
            "Video Wallpaper Manager",
            "Running in background. Double-click tray icon to restore.",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )

    def update_status(self):
        running = sum(len(procs) for procs in state.processes.values())

        info_text = f"{len(state.monitors)} monitor(s) • {len(state.videos)} video(s)"
        if state.current_mode:
            info_text += f" • Mode: {state.current_mode}"
        self.info_bar.setText(info_text)

        status = f"Active: {running} video(s)"
        if state.auto_change_enabled:
            status += " | Auto: ON"
        if state.transition_active:
            status = "Transitioning..."
            self.status_label.setStyleSheet("color: #ffd93d; font-weight: bold;")
        else:
            self.status_label.setStyleSheet("color: #a0a0a0;")

        self.status_label.setText(status)

    def refresh_library(self):
        self.library_tab.refresh_library()

    def closeEvent(self, event):
        event.ignore()
        self.hide_to_tray()

    def update_keyboard_handler(self):
        if hasattr(self, 'keyboard_handler'):
            self.keyboard_handler.set_enabled(state.shortcuts_enabled)
            if state.shortcuts_enabled:
                self.keyboard_handler.update_shortcuts()

    def restart_keyboard_handler(self):
        if not PYNPUT_AVAILABLE:
            return

        if hasattr(self, 'keyboard_handler'):
            self.keyboard_handler.stop()
            del self.keyboard_handler

        if state.shortcuts_enabled:
            self.keyboard_handler = KeyboardHandler()
            self.keyboard_handler.next_signal.connect(next_wallpaper)
            self.keyboard_handler.prev_signal.connect(prev_wallpaper)
            self.keyboard_handler.random_signal.connect(random_wallpaper)
            self.keyboard_handler.update_shortcuts()
            self.keyboard_handler.start()
            state.log("Keyboard handler restarted with new shortcuts")

    def quit_app(self):
        if hasattr(self, 'keyboard_handler'):
            self.keyboard_handler.stop()
        stop_wallpapers()
        if hasattr(self, 'auto_thread'):
            self.auto_thread.stop()
        QApplication.quit()

# ==================== MAIN ====================

def main():
    if not check_mpv():
        print("ERROR: mpv not found! Please install mpv and add it to PATH.")
        print("Download: https://mpv.io/installation/")
        input("Press Enter to exit...")
        return

    os.makedirs(SAVE_DIR, exist_ok=True)
    load_config()
    load_videos()
    detect_monitors()

    for i in range(len(state.monitors)):
        if i not in state.monitor_assignments:
            state.monitor_assignments[i] = i % len(state.videos) if state.videos else 0

    if state.videos:
        start_wallpaper()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    window = VideoWallpaperManager()
    window.show()

    state.log("Application started")

    sys.exit(app.exec())

if __name__ == "__main__":
    main()