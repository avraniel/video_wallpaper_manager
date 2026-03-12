#!/usr/bin/env python3
"""
Video Wallpaper Manager - Final UX Update
- Clicking 'X' now minimizes to tray (hides window).
- Application only fully quits via 'Quit' in System Tray.
- All previous fixes retained.
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
import atexit
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

# Keyboard shortcut support
try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

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
    "monitor_assignments": {},
    "shortcuts_enabled": True,
    "shortcuts": {
        "next": "<ctrl>+<shift>+n",
        "prev": "<ctrl>+<shift>+p",
        "random": "<ctrl>+<shift>+r",
        "toggle": "<ctrl>+<shift>+t"
    },
}

# Windows constants
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
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
        self.shortcuts_enabled = DEFAULT_SETTINGS["shortcuts_enabled"]
        self.shortcuts = DEFAULT_SETTINGS["shortcuts"].copy()
        self.transition_active = False
        self.log_entries = deque(maxlen=1000)
        self.lock = threading.Lock()

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

# ==================== CLEANUP HANDLER ====================
def cleanup_handler():
    state.log("Application closing, cleaning up processes...")
    stop_wallpapers()

atexit.register(cleanup_handler)

# ==================== KEYBOARD HANDLER ====================

class KeyboardHandler(QObject):
    next_signal = pyqtSignal()
    prev_signal = pyqtSignal()
    random_signal = pyqtSignal()
    toggle_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.listener = None
        self.hotkeys = []
        self.enabled = True

    def start(self):
        if not PYNPUT_AVAILABLE: return False
        try:
            self._setup_hotkeys()
            return True
        except Exception as e:
            state.log(f"Keyboard shortcut error: {e}", "ERROR")
            return False

    def _setup_hotkeys(self):
        self.hotkeys = []
        actions = {
            'next': lambda: self.next_signal.emit(),
            'prev': lambda: self.prev_signal.emit(),
            'random': lambda: self.random_signal.emit(),
            'toggle': lambda: self.toggle_signal.emit()
        }
        for action, shortcut_str in state.shortcuts.items():
            if action in actions:
                try:
                    keys = keyboard.HotKey.parse(shortcut_str)
                    hotkey = keyboard.HotKey(keys, actions[action])
                    self.hotkeys.append(hotkey)
                except: pass
        if self.hotkeys:
            self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release, suppress=False)
            self.listener.start()

    def _on_press(self, key):
        if not self.enabled: return
        canonical = self.listener.canonical(key)
        for hotkey in self.hotkeys: hotkey.press(canonical)

    def _on_release(self, key):
        if not self.enabled: return
        canonical = self.listener.canonical(key)
        for hotkey in self.hotkeys: hotkey.release(canonical)

    def stop(self):
        if self.listener: self.listener.stop()

# ==================== MPV & WINDOW MANAGEMENT ====================

def find_window(pid, timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        hwnds = []
        def callback(hwnd, _):
            try:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid: hwnds.append(hwnd)
            except: pass
        win32gui.EnumWindows(callback, None)
        if hwnds: return hwnds[0]
        time.sleep(0.1)
    return None

def set_window_opacity(hwnd, opacity):
    try:
        SetLayeredWindowAttributes(hwnd, 0, int(opacity), LWA_ALPHA)
        return True
    except: return False

def prepare_window_styles(hwnd):
    """Setup window styles: Popup, Transparent, Layered, NoActivate."""
    try:
        # 1. Set Standard Styles: WS_POPUP (borderless)
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        style = win32con.WS_POPUP | win32con.WS_CLIPCHILDREN | win32con.WS_CLIPSIBLINGS
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)

        # 2. Set Extended Styles: Layered, Transparent, NoActivate, ToolWindow
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex_style |= (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
        return True
    except Exception as e:
        state.log(f"Style error: {e}", "ERROR")
        return False

def get_monitor_geometry(monitor_idx=None):
    if monitor_idx is not None and 0 <= monitor_idx < len(state.monitors):
        m = state.monitors[monitor_idx]
        return (m['x'], m['y'], m['width'], m['height'])
    if not state.monitors: return (0, 0, 1920, 1080)
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
        "--profile=fast",
        "--hwdec=auto-safe",
        "--framedrop=decoder+vo",
        "--no-input-default-bindings",
        "--no-osc",
        "--really-quiet",
        "--ontop=no",
        "--input-cursor=no",   # Disable cursor handling inside MPV
        "--cursor-autohide=no",# Ensure cursor isn't manipulated
        "--geometry=" + geometry,
        video
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
    return subprocess.Popen(args, creationflags=creationflags)

def keep_at_bottom(hwnd):
    """Thread to aggressively keep window behind everything."""
    while True:
        try:
            if not win32gui.IsWindow(hwnd): break
            win32gui.SetWindowPos(hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | 
                                win32con.SWP_NOACTIVATE | 0x0200)
            time.sleep(2)
        except: break

def setup_wallpaper_window(p, monitor_idx):
    try:
        hwnd = find_window(p.pid, timeout=10)
        if not hwnd: return None, None

        x, y, w, h = get_monitor_geometry(monitor_idx)
        win32gui.ShowWindow(hwnd, SW_HIDE)
        prepare_window_styles(hwnd)
        time.sleep(0.4)
        
        if not win32gui.IsWindow(hwnd): return None, None

        # Position it
        win32gui.SetWindowPos(hwnd, win32con.HWND_BOTTOM, x, y, w, h,
                             win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED | 
                             0x0200 | win32con.SWP_SHOWWINDOW)
        
        # Start thread to keep it down
        threading.Thread(target=keep_at_bottom, args=(hwnd,), daemon=True).start()
        return hwnd, p
    except Exception as e:
        state.log(f"Setup error: {e}", "ERROR")
        return None, None

# ==================== WALLPAPER CONTROL ====================

def detect_monitors():
    state.monitors = []
    for m in get_monitors():
        state.monitors.append({'x': m.x, 'y': m.y, 'width': m.width, 'height': m.height, 'is_primary': m.is_primary})
    state.monitors.sort(key=lambda x: x['x'])

def stop_wallpapers():
    for idx, procs in list(state.processes.items()):
        for p in procs:
            try: p.kill()
            except: pass
    state.processes = {}

def instant_switch_monitor(monitor_idx, new_video_idx):
    if not state.videos or new_video_idx >= len(state.videos): return False
    new_video = state.videos[new_video_idx]
    
    if monitor_idx in state.processes:
        for p in state.processes[monitor_idx]: 
            try: p.kill()
            except: pass
    state.processes[monitor_idx] = []

    try:
        x, y, w, h = get_monitor_geometry(monitor_idx)
        p = launch_mpv(new_video, x, y, w, h)
        hwnd, p = setup_wallpaper_window(p, monitor_idx)
        if hwnd:
            state.processes[monitor_idx] = [p]
            return True
        return False
    except: return False

def crossfade_monitor(monitor_idx, new_video_idx):
    with state.lock:
        if state.transition_active: return False
        state.transition_active = True
    
    if not state.videos or new_video_idx >= len(state.videos):
        state.transition_active = False
        return False

    new_video = state.videos[new_video_idx]
    state.log(f"Monitor {monitor_idx}: Crossfading to {os.path.basename(new_video)}")

    try:
        x, y, w, h = get_monitor_geometry(monitor_idx)
        old_procs = state.processes.get(monitor_idx, []).copy()

        # Launch NEW window
        new_p = launch_mpv(new_video, x, y, w, h)
        new_hwnd = find_window(new_p.pid, timeout=10)
        if not new_hwnd:
            state.transition_active = False
            return False

        win32gui.ShowWindow(new_hwnd, SW_HIDE)
        prepare_window_styles(new_hwnd)
        set_window_opacity(new_hwnd, 0) # Start invisible
        
        # Position New window
        win32gui.SetWindowPos(new_hwnd, win32con.HWND_BOTTOM, x, y, w, h,
                             win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED | 0x0200 | win32con.SWP_SHOWWINDOW)
        
        if monitor_idx not in state.processes: state.processes[monitor_idx] = []
        state.processes[monitor_idx].append(new_p)
        threading.Thread(target=keep_at_bottom, args=(new_hwnd,), daemon=True).start()

        # Perform Fade
        steps = int(state.transition_duration * 60)
        step_duration = state.transition_duration / steps
        for i in range(steps + 1):
            progress = i / steps
            eased = progress * progress * (3 - 2 * progress)
            
            new_opacity = int(255 * eased)
            old_opacity = int(255 * (1 - eased))
            
            set_window_opacity(new_hwnd, new_opacity)
            
            for old_p in old_procs:
                try:
                    old_hwnd = find_window(old_p.pid, timeout=0.1)
                    if old_hwnd: set_window_opacity(old_hwnd, old_opacity)
                except: pass
            time.sleep(step_duration)

        # Cleanup
        for old_p in old_procs:
            try: old_p.kill()
            except: pass
        
        state.processes[monitor_idx] = [p for p in state.processes[monitor_idx] if p.poll() is None]
        return True
    except Exception as e:
        state.log(f"Transition error: {e}", "ERROR")
        return False
    finally:
        state.transition_active = False

def start_wallpaper(video=None):
    stop_wallpapers()
    if not state.videos: return
    if state.current_mode == "span":
        video = video or state.videos[state.current_index]
        x, y, w, h = get_monitor_geometry()
        p = launch_mpv(video, x, y, w, h)
        hwnd, p = setup_wallpaper_window(p, 0)
        if hwnd: state.processes = {0: [p]}
    else:
        for i in range(len(state.monitors)):
            video_idx = state.current_index
            if state.current_mode == "individual":
                video_idx = state.monitor_assignments.get(i, i) % len(state.videos)
            instant_switch_monitor(i, video_idx)
            time.sleep(0.2)

def next_wallpaper():
    if not state.videos: return
    state.current_index = (state.current_index + 1) % len(state.videos)
    if state.current_mode == "individual":
        for i in range(len(state.monitors)):
            new_idx = (state.monitor_assignments.get(i, 0) + 1) % len(state.videos)
            state.monitor_assignments[i] = new_idx
            threading.Thread(target=crossfade_monitor, args=(i, new_idx), daemon=True).start()
    else: start_wallpaper()

def prev_wallpaper():
    if not state.videos: return
    state.current_index = (state.current_index - 1) % len(state.videos)
    if state.current_mode == "individual":
        for i in range(len(state.monitors)):
            new_idx = (state.monitor_assignments.get(i, 0) - 1) % len(state.videos)
            state.monitor_assignments[i] = new_idx
            threading.Thread(target=crossfade_monitor, args=(i, new_idx), daemon=True).start()
    else: start_wallpaper()

def random_wallpaper():
    if not state.videos: return
    state.current_index = random.randint(0, len(state.videos) - 1)
    start_wallpaper()

# ==================== CONFIG & DATA ====================

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                state.current_mode = config.get('mode', DEFAULT_SETTINGS["mode"])
                state.monitor_assignments = {int(k): v for k, v in config.get('assignments', {}).items()}
                state.transition_duration = config.get('transition_duration', DEFAULT_SETTINGS["transition_duration"])
                state.auto_change_enabled = config.get('auto_change_enabled', DEFAULT_SETTINGS["auto_change_enabled"])
                state.auto_change_interval = config.get('auto_change_interval', DEFAULT_SETTINGS["auto_change_interval"])
        except: pass

def save_config():
    config = {
        'mode': state.current_mode, 'assignments': state.monitor_assignments,
        'transition_duration': state.transition_duration,
        'auto_change_enabled': state.auto_change_enabled, 'auto_change_interval': state.auto_change_interval
    }
    try:
        with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=2)
    except: pass

def load_videos():
    state.videos = []
    if not os.path.exists(SAVE_DIR): os.makedirs(SAVE_DIR)
    for f in os.listdir(SAVE_DIR):
        if f.lower().endswith(VIDEO_EXTENSIONS): state.videos.append(os.path.join(SAVE_DIR, f))
    state.videos.sort()

# ==================== MOEWALLS SCRAPER ====================

def search_wallpapers(keyword):
    url = f"{BASE_URL}/?s={quote(keyword)}"
    r = requests.get(url, headers=HEADERS)
    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    for article in soup.find_all("article"):
        link = article.find("a", href=True)
        img = article.find("img")
        if link and img:
            results.append({"title": img.get("alt", "Wallpaper"), "page": link["href"], "thumbnail": img.get("src")})
    return results

def get_download_link(page_url):
    r = requests.get(page_url, headers=HEADERS)
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a"):
        if "download" in a.text.lower() and a.get("href"): return a["href"]
    return None

def download_video(url, progress_callback=None):
    filename = url.split("/")[-1].split("?")[0]
    filepath = os.path.join(SAVE_DIR, filename)
    r = requests.get(url, headers=HEADERS, stream=True)
    total = int(r.headers.get('content-length', 0))
    downloaded = 0
    with open(filepath, "wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total > 0: progress_callback(int(downloaded * 100 / total))
    return filepath

# ==================== WORKER THREADS ====================

class SearchThread(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    def __init__(self, keyword): super().__init__(); self.keyword = keyword
    def run(self):
        try: self.finished.emit(search_wallpapers(self.keyword))
        except Exception as e: self.error.emit(str(e))

class DownloadThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    def __init__(self, page_url): super().__init__(); self.page_url = page_url
    def run(self):
        try:
            dl_url = get_download_link(self.page_url)
            if not dl_url: self.error.emit("Link not found"); return
            filepath = download_video(dl_url, lambda p: self.progress.emit(p))
            self.finished.emit(filepath)
        except Exception as e: self.error.emit(str(e))

class AutoChangeThread(QThread):
    def __init__(self): super().__init__(); self.running = True
    def run(self):
        while self.running and state.auto_change_enabled:
            time.sleep(state.auto_change_interval)
            if self.running and state.auto_change_enabled and state.videos: random_wallpaper()
    def stop(self): self.running = False

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
        self.setStyleSheet("WallpaperCard { background-color: #2d2d2d; border-radius: 8px; border: 1px solid #3d3d3d; } WallpaperCard:hover { border: 1px solid #00d4aa; }")

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
            set_btn.setStyleSheet("QPushButton { background-color: #00d4aa; color: black; border: none; padding: 5px 15px; border-radius: 4px; font-weight: bold; }")
            set_btn.clicked.connect(lambda: self.set_clicked.emit(self.video_path))
            btn_layout.addWidget(set_btn)
        else:
            dl_btn = QPushButton("Download")
            dl_btn.setStyleSheet("QPushButton { background-color: #00d4aa; color: black; border: none; padding: 5px 15px; border-radius: 4px; font-weight: bold; }")
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
            except: self.thumb_label.setText("❌")
        threading.Thread(target=fetch, daemon=True).start()

    def mousePressEvent(self, event):
        self.clicked.emit({"path": self.video_path, "is_local": self.is_local, "data": self.online_data})

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
        self.search_input.setPlaceholderText("Search anime wallpapers...")
        self.search_input.setStyleSheet("QLineEdit { padding: 12px; border: 2px solid #3d3d3d; border-radius: 6px; background-color: #2d2d2d; color: white; }")
        self.search_input.returnPressed.connect(self.do_search)
        search_layout.addWidget(self.search_input)

        self.search_btn = QPushButton("🔍 Search")
        self.search_btn.setStyleSheet("QPushButton { background-color: #00d4aa; color: black; border: none; padding: 12px 24px; border-radius: 6px; font-weight: bold; }")
        self.search_btn.clicked.connect(self.do_search)
        search_layout.addWidget(self.search_btn)
        layout.addLayout(search_layout)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
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
        if not keyword: return
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
            if item.widget(): item.widget().deleteLater()
        if not results:
            self.status_label.setText("No results found.")
            return
        self.status_label.setText(f"Found {len(results)} wallpapers")
        for i, result in enumerate(results):
            card = WallpaperCard(video_path=result["page"], is_local=False, online_data=result)
            card.download_clicked.connect(self.start_download)
            self.results_layout.addWidget(card, i // 3, i % 3)

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
        if self.parent: self.parent.refresh_library()
        QMessageBox.information(self, "Download Complete", f"Saved to: {os.path.basename(filepath)}")

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
        add_btn.setStyleSheet("QPushButton { background-color: #3d3d3d; color: white; border: none; padding: 8px 16px; border-radius: 4px; }")
        add_btn.clicked.connect(self.add_videos)
        controls.addWidget(add_btn)

        open_btn = QPushButton("📁 Open Folder")
        open_btn.setStyleSheet("QPushButton { background-color: #3d3d3d; color: white; border: none; padding: 8px 16px; border-radius: 4px; }")
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
        actions_box.setStyleSheet("QGroupBox { color: #00d4aa; font-weight: bold; border: 1px solid #3d3d3d; border-radius: 6px; margin-top: 10px; padding-top: 10px; }")
        actions_layout = QHBoxLayout(actions_box)

        prev_btn = QPushButton("⏮ Previous")
        prev_btn.setStyleSheet("QPushButton { background-color: #3d3d3d; color: white; border: none; padding: 10px 20px; border-radius: 4px; font-weight: bold; }")
        prev_btn.clicked.connect(prev_wallpaper)
        actions_layout.addWidget(prev_btn)

        next_btn = QPushButton("▶ Next Wallpaper")
        next_btn.setStyleSheet("QPushButton { background-color: #00d4aa; color: black; border: none; padding: 10px 30px; border-radius: 4px; font-weight: bold; }")
        next_btn.clicked.connect(next_wallpaper)
        actions_layout.addWidget(next_btn)

        random_btn = QPushButton("🔀 Random")
        random_btn.setStyleSheet("QPushButton { background-color: #3d3d3d; color: white; border: none; padding: 10px 20px; border-radius: 4px; font-weight: bold; }")
        random_btn.clicked.connect(random_wallpaper)
        actions_layout.addWidget(random_btn)
        layout.addWidget(actions_box)

    def refresh_library(self):
        while self.library_layout.count():
            item = self.library_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        load_videos()
        self.info_label.setText(f"{len(state.videos)} video(s) in library")
        for i, video_path in enumerate(state.videos):
            card = WallpaperCard(video_path, is_local=True)
            card.set_clicked.connect(self.set_wallpaper)
            self.library_layout.addWidget(card, i // 3, i % 3)

    def set_wallpaper(self, video_path):
        try:
            idx = state.videos.index(video_path)
            state.current_index = idx
            if state.current_mode == "individual":
                for i in range(len(state.monitors)):
                    state.monitor_assignments[i] = idx
                    threading.Thread(target=crossfade_monitor, args=(i, idx), daemon=True).start()
            else: start_wallpaper(video_path)
        except: pass

    def add_videos(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Videos", "", "Videos (*.mp4 *.webm *.mkv)")
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
        if not os.path.exists(SAVE_DIR): os.makedirs(SAVE_DIR)
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
        mode_box.setStyleSheet("QGroupBox { color: #00d4aa; font-weight: bold; border: 1px solid #3d3d3d; border-radius: 6px; margin-top: 10px; padding-top: 10px; }")
        mode_layout = QVBoxLayout(mode_box)

        self.mode_group = QButtonGroup(self)
        modes = [("span", "Span", "One video across all monitors"), ("duplicate", "Duplicate", "Same video on all monitors"), ("individual", "Individual", "Different video per monitor")]
        for value, name, desc in modes:
            row = QHBoxLayout()
            rb = QRadioButton(name)
            rb.setStyleSheet("color: white; font-size: 12px;")
            rb.mode_value = value
            self.mode_group.addButton(rb)
            row.addWidget(rb)
            lbl = QLabel(desc)
            lbl.setStyleSheet("color: #a0a0a0; font-size: 11px;")
            row.addWidget(lbl)
            row.addStretch()
            mode_layout.addLayout(row)
        self.mode_group.buttonClicked.connect(self.on_mode_changed)
        layout.addWidget(mode_box)

        self.monitor_box = QGroupBox("Per-Monitor Assignment")
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
        test_btn.setStyleSheet("QPushButton { background-color: #00d4aa; color: black; border: none; padding: 10px 20px; border-radius: 4px; font-weight: bold; }")
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
        self.auto_check.setChecked(state.auto_change_enabled)
        self.interval_spin.setValue(state.auto_change_interval // 60)
        self.refresh_monitor_assignment()

    def refresh_monitor_assignment(self):
        while self.monitor_layout.count():
            item = self.monitor_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if state.current_mode != "individual" or len(state.monitors) <= 1:
            self.monitor_box.setVisible(False)
            return
        self.monitor_box.setVisible(True)
        for i, m in enumerate(state.monitors):
            row = QHBoxLayout()
            info = f"Monitor {i+1} - {m['width']}x{m['height']}"
            row.addWidget(QLabel(info))
            combo = QComboBox()
            for v in state.videos: combo.addItem(os.path.basename(v))
            current = state.monitor_assignments.get(i, i) % len(state.videos) if state.videos else 0
            combo.setCurrentIndex(current)
            combo.currentIndexChanged.connect(lambda idx, mon=i: self.on_monitor_video_changed(mon, idx))
            row.addWidget(combo)
            self.monitor_layout.addLayout(row)

    def on_mode_changed(self, btn):
        state.current_mode = btn.mode_value
        save_config()
        self.refresh_monitor_assignment()
        start_wallpaper()

    def on_duration_changed(self, value):
        seconds = value / 10.0
        state.transition_duration = seconds
        self.duration_label.setText(f"{seconds:.1f}s")
        save_config()

    def on_auto_changed(self, state_val):
        state.auto_change_enabled = bool(state_val)
        save_config()

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
        new_idx = (state.current_index + 1) % len(state.videos)
        threading.Thread(target=crossfade_monitor, args=(0, new_idx), daemon=True).start()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Wallpaper Manager")
        self.resize(900, 700)
        self.setStyleSheet("QMainWindow, QWidget { background-color: #1e1e1e; color: white; } QGroupBox { border: 1px solid #3d3d3d; border-radius: 6px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #00d4aa; } QPushButton { background-color: #3d3d3d; color: white; border: none; padding: 8px 16px; border-radius: 4px; } QPushButton:hover { background-color: #4d4d4d; } QSlider::groove:horizontal { background: #3d3d3d; height: 8px; border-radius: 4px; } QSlider::handle:horizontal { background: #00d4aa; width: 18px; margin: -5px 0; border-radius: 9px; }")

        load_config()
        detect_monitors()
        load_videos()

        tabs = QTabWidget()
        tabs.addTab(LibraryTab(self), "📁 Library")
        tabs.addTab(MoeWallsTab(self), "🌐 MoeWalls")
        tabs.addTab(DisplayTab(self), "🖥 Display")
        self.setCentralWidget(tabs)

        # System Tray with more options
        tray_icon = QSystemTrayIcon(self)
        tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        
        tray_menu = QMenu()
        
        # Add Actions
        next_action = QAction("Next Wallpaper", self)
        next_action.triggered.connect(next_wallpaper)
        tray_menu.addAction(next_action)

        prev_action = QAction("Previous Wallpaper", self)
        prev_action.triggered.connect(prev_wallpaper)
        tray_menu.addAction(prev_action)

        random_action = QAction("Random Wallpaper", self)
        random_action.triggered.connect(random_wallpaper)
        tray_menu.addAction(random_action)

        tray_menu.addSeparator()

        stop_action = QAction("Stop Wallpapers", self)
        stop_action.triggered.connect(stop_wallpapers)
        tray_menu.addAction(stop_action)

        tray_menu.addSeparator()

        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self.show)
        show_action.triggered.connect(self.activateWindow) # Bring to front
        tray_menu.addAction(show_action)

        quit_action = QAction("Quit", self)
        # Connect quit to the QApplication quit method, not window close
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)
        
        tray_icon.setContextMenu(tray_menu)
        tray_icon.show()

    def closeEvent(self, event):
        # Override close event to hide the window instead of quitting
        event.ignore()
        self.hide()

    def refresh_library(self):
        central = self.centralWidget()
        if isinstance(central, QTabWidget):
            lib_tab = central.widget(0)
            if hasattr(lib_tab, 'refresh_library'): lib_tab.refresh_library()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
