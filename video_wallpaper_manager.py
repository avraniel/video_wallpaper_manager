#!/usr/bin/env python3
"""
Video Wallpaper Manager - Theme Engine + Visualizer Customization
- Added 'Rainbow Mode' for visualizer.
- Added 'Bar Width' setting.
- Styles: Bars, Slim, Wave, Wave Dots, Radial.
- Added Keyboard Shortcuts with UI
- Fixed Windows Taskbar Icon
- Fixed Random Wallpaper functionality
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
import struct
import math
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
    QKeySequenceEdit, QListWidget, QSizePolicy
)
from PyQt6.QtGui import (
    QPixmap, QFont, QIcon, QAction, QImage, QPainter, QBrush,
    QColor, QPen, QPolygonF, QPalette, QPainterPath
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QObject, QPointF
from PIL import Image
from bs4 import BeautifulSoup
import win32gui
import win32con
import win32process
from screeninfo import get_monitors

# Audio Vis Dependencies
try:
    import pyaudiowpatch as pyaudio
    import numpy as np
    AUDIO_VIS_AVAILABLE = True
except ImportError:
    AUDIO_VIS_AVAILABLE = False
    print("Audio Visualizer dependencies not found. Install: pip install pyaudiowpatch numpy")

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
    "theme": "Dark",
    "accent_color": "#00d4aa",
    "visualizer_enabled": False,
    "visualizer_style": "Radial",
    "visualizer_bars": 64,
    "visualizer_height": 100,
    "visualizer_rainbow": False,
    "visualizer_bar_width": 3
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

# ==================== THEME ENGINE ====================
class ThemeManager:
    THEMES = {
        "Dark": {
            "name": "Dark", "window": "#1e1e1e", "base": "#252525", "alt_base": "#2d2d2d",
            "text": "#ffffff", "text_disabled": "#a0a0a0", "accent": "#00d4aa", "accent_hover": "#00ffcc",
            "selection": "#00d4aa", "border": "#3d3d3d", "input_bg": "#2d2d2d",
            "scrollbar_bg": "#2d2d2d", "scrollbar_handle": "#555555",
        },
        "Light": {
            "name": "Light", "window": "#f0f0f0", "base": "#ffffff", "alt_base": "#f8f8f8",
            "text": "#1e1e1e", "text_disabled": "#888888", "accent": "#0078d4", "accent_hover": "#1084d8",
            "selection": "#0078d4", "border": "#d0d0d0", "input_bg": "#ffffff",
            "scrollbar_bg": "#f0f0f0", "scrollbar_handle": "#c0c0c0",
        },
        "Dracula": {
            "name": "Dracula", "window": "#282a36", "base": "#44475a", "alt_base": "#44475a",
            "text": "#f8f8f2", "text_disabled": "#6272a4", "accent": "#bd93f9", "accent_hover": "#ff79c6",
            "selection": "#bd93f9", "border": "#6272a4", "input_bg": "#44475a",
            "scrollbar_bg": "#282a36", "scrollbar_handle": "#6272a4",
        },
        "Nord": {
            "name": "Nord", "window": "#2e3440", "base": "#3b4252", "alt_base": "#434c5e",
            "text": "#eceff4", "text_disabled": "#d8dee9", "accent": "#88c0d0", "accent_hover": "#81a1c1",
            "selection": "#5e81ac", "border": "#4c566a", "input_bg": "#3b4252",
            "scrollbar_bg": "#2e3440", "scrollbar_handle": "#4c566a",
        },
        "Midnight": {
            "name": "Midnight", "window": "#0a0a0a", "base": "#121212", "alt_base": "#1e1e1e",
            "text": "#e0e0e0", "text_disabled": "#606060", "accent": "#bb86fc", "accent_hover": "#cf9fff",
            "selection": "#bb86fc", "border": "#2e2e2e", "input_bg": "#1e1e1e",
            "scrollbar_bg": "#121212", "scrollbar_handle": "#333333",
        }
    }

    def __init__(self, app):
        self.app = app
        self.current_theme_name = "Dark"
        self.palette = self.THEMES[self.current_theme_name]
        self.color_changed_callbacks = []

    def set_theme(self, theme_name):
        if theme_name in self.THEMES:
            self.current_theme_name = theme_name
            self.palette = self.THEMES[theme_name]
            self.apply_theme()
            self._notify_color_change()
            return True
        return False

    def get_accent_color(self):
        return QColor(self.palette['accent'])

    def register_color_callback(self, func):
        self.color_changed_callbacks.append(func)

    def _notify_color_change(self):
        for func in self.color_changed_callbacks:
            func()

    def get_stylesheet(self):
        p = self.palette
        btn_primary = f"""
        QPushButton {{
            background-color: {p['accent']};
            color: {"black" if p['name'] in ['Light'] else "white"};
            border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold;
        }}
        QPushButton:hover {{ background-color: {p['accent_hover']}; }}
        QPushButton:disabled {{ background-color: {p['border']}; color: {p['text_disabled']}; }}
        """
        btn_secondary = f"""
        QPushButton {{
            background-color: {p['alt_base']}; color: {p['text']};
            border: 1px solid {p['border']}; padding: 8px 16px; border-radius: 4px;
        }}
        QPushButton:hover {{ background-color: {p['border']}; }}
        """
        return f"""
        QWidget {{ background-color: {p['window']}; color: {p['text']}; font-family: 'Segoe UI', Arial, sans-serif; }}
        QMainWindow {{ background-color: {p['window']}; }}
        QTabWidget::pane {{ border: 1px solid {p['border']}; background-color: {p['window']}; border-radius: 4px; }}
        QTabBar::tab {{
            background-color: {p['alt_base']}; color: {p['text_disabled']}; padding: 10px 20px;
            border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px;
        }}
        QTabBar::tab:selected {{ background-color: {p['window']}; color: {p['accent']}; font-weight: bold; border-bottom: 2px solid {p['accent']}; }}
        QGroupBox {{ color: {p['accent']}; font-weight: bold; border: 1px solid {p['border']}; border-radius: 6px; margin-top: 12px; padding-top: 12px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
        QLineEdit, QTextEdit, QSpinBox, QComboBox {{
            background-color: {p['input_bg']}; color: {p['text']}; border: 1px solid {p['border']};
            padding: 8px; border-radius: 4px; selection-background-color: {p['selection']};
        }}
        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{ border: 1px solid {p['accent']}; }}
        QComboBox::drop-down {{ border: none; width: 30px; }}
        QComboBox QAbstractItemView {{ background-color: {p['base']}; selection-background-color: {p['accent']}; border: 1px solid {p['border']}; }}
        QPushButton#btnPrimary {{ {btn_primary} }}
        QPushButton#btnSecondary {{ {btn_secondary} }}
        QPushButton {{
            background-color: {p['alt_base']}; color: {p['text']}; border: 1px solid {p['border']};
            padding: 8px 16px; border-radius: 4px;
        }}
        QPushButton:hover {{ background-color: {p['border']}; }}
        QScrollArea {{ border: none; background-color: transparent; }}
        QScrollBar:vertical {{ background-color: {p['scrollbar_bg']}; width: 12px; border-radius: 6px; }}
        QScrollBar::handle:vertical {{ background-color: {p['scrollbar_handle']}; min-height: 20px; border-radius: 6px; margin: 2px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QScrollBar:horizontal {{ background-color: {p['scrollbar_bg']}; height: 12px; border-radius: 6px; }}
        QScrollBar::handle:horizontal {{ background-color: {p['scrollbar_handle']}; min-width: 20px; border-radius: 6px; margin: 2px; }}
        QSlider::groove:horizontal {{ background: {p['border']}; height: 6px; border-radius: 3px; }}
        QSlider::handle:horizontal {{ background: {p['accent']}; width: 18px; margin: -6px 0; border-radius: 9px; }}
        QProgressBar {{ border: none; border-radius: 4px; background-color: {p['border']}; text-align: center; color: white; }}
        QProgressBar::chunk {{ background-color: {p['accent']}; border-radius: 4px; }}
        QCheckBox, QRadioButton {{ spacing: 8px; color: {p['text']}; }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 18px; height: 18px; border-radius: 4px;
            border: 2px solid {p['border']}; background-color: {p['input_bg']};
        }}
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
            background-color: {p['accent']}; border-color: {p['accent']};
        }}
        QToolTip {{ background-color: {p['base']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 4px; }}
        WallpaperCard {{ background-color: {p['alt_base']}; border-radius: 8px; border: 1px solid {p['border']}; }}
        WallpaperCard:hover {{ border: 1px solid {p['accent']}; }}
        """

    def apply_theme(self):
        self.app.setStyleSheet(self.get_stylesheet())
        current_style = self.app.style()
        for widget in self.app.topLevelWidgets():
            widget.setStyle(current_style)

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
        self.theme = DEFAULT_SETTINGS["theme"]
        self.visualizer_enabled = DEFAULT_SETTINGS["visualizer_enabled"]
        self.visualizer_style = DEFAULT_SETTINGS["visualizer_style"]
        self.visualizer_bars = DEFAULT_SETTINGS["visualizer_bars"]
        self.visualizer_height = DEFAULT_SETTINGS["visualizer_height"]
        self.visualizer_rainbow = DEFAULT_SETTINGS["visualizer_rainbow"]
        self.visualizer_bar_width = DEFAULT_SETTINGS["visualizer_bar_width"]
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

# ==================== AUDIO VISUALIZER ====================
class AudioVisualizerWindow(QWidget):
    def __init__(self, theme_manager):
        super().__init__()
        self.theme_manager = theme_manager
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.style = state.visualizer_style
        self.bars = state.visualizer_bars
        self.height_factor = state.visualizer_height
        self.audio_data = np.zeros(self.bars)
        self.color = self.theme_manager.get_accent_color()
        self.theme_manager.register_color_callback(self.update_color)
        self.setWindowTitle("AudioVisualizer")
        self.resize_screen()

    def update_color(self):
        self.color = self.theme_manager.get_accent_color()

    def resize_screen(self):
        if state.monitors:
            m = state.monitors[0]
            if self.style == "Radial":
                self.setGeometry(m['x'], m['y'], m['width'], m['height'])
            else:
                self.setGeometry(m['x'], m['y'] + m['height'] - self.height_factor - 50,
                               m['width'], self.height_factor + 50)
        else:
            self.setGeometry(0, 0, 1920, 1080)

    def update_data(self, data):
        self.audio_data = data
        self.update()

    def get_color_for_bar(self, index, total):
        """Returns either accent color or rainbow color based on settings."""
        if state.visualizer_rainbow:
            hue = (index / total) * 360
            return QColor.fromHsv(int(hue), 255, 255)
        else:
            return self.color

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        if self.style == "Bars":
            self.draw_bars(painter, w, h)
        elif self.style == "Slim":
            self.draw_slim(painter, w, h)
        elif self.style == "Wave":
            self.draw_wave(painter, w, h)
        elif self.style == "Wave Dots":
            self.draw_wave_dots(painter, w, h)
        elif self.style == "Radial":
            self.draw_radial(painter, w, h)

    def draw_bars(self, painter, w, h):
        bar_width = w / self.bars
        painter.setPen(Qt.PenStyle.NoPen)
        draw_width = min(state.visualizer_bar_width, bar_width)
        offset = (bar_width - draw_width) / 2
        for i, val in enumerate(self.audio_data):
            bar_h = val * self.height_factor
            x = i * bar_width + offset
            y = h - bar_h
            color = self.get_color_for_bar(i, self.bars)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(int(x), int(y), int(draw_width), int(bar_h), 3, 3)

    def draw_slim(self, painter, w, h):
        bar_width = w / self.bars
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i, val in enumerate(self.audio_data):
            bar_h = val * self.height_factor
            x = i * bar_width + (bar_width / 2)
            y_start = h
            y_end = h - bar_h
            color = self.get_color_for_bar(i, self.bars)
            color.setAlpha(200)
            pen = QPen(color, state.visualizer_bar_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, y_start), QPointF(x, y_end))

    def draw_wave(self, painter, w, h):
        path = QPainterPath()
        step = w / self.bars
        path.moveTo(0, h)
        for i, val in enumerate(self.audio_data):
            x = i * step
            y = h - (val * self.height_factor)
            path.lineTo(x, y)
        path.lineTo(w, h)
        path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        fill_color = QColor(self.color) if not state.visualizer_rainbow else QColor.fromHsv(0, 0, 255)
        fill_color.setAlpha(100)
        painter.setBrush(QBrush(fill_color))
        painter.drawPath(path)
        for i, val in enumerate(self.audio_data):
            x1 = (i-1) * step if i > 0 else 0
            y1 = h - (self.audio_data[i-1] * self.height_factor) if i > 0 else h - (val * self.height_factor)
            x2 = i * step
            y2 = h - (val * self.height_factor)
            if i == 0:
                x1, y1 = x2, y2
            color = self.get_color_for_bar(i, self.bars)
            painter.setPen(QPen(color, state.visualizer_bar_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if i > 0:
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def draw_wave_dots(self, painter, w, h):
        step = w / self.bars
        painter.setPen(Qt.PenStyle.NoPen)
        for i, val in enumerate(self.audio_data):
            x = i * step + step / 2
            y = h - (val * self.height_factor)
            color = self.get_color_for_bar(i, self.bars)
            painter.setBrush(QBrush(color))
            radius = (state.visualizer_bar_width / 2) + (val * 4)
            painter.drawEllipse(QPointF(x, y), radius, radius)

    def draw_radial(self, painter, w, h):
        center_x = w / 2
        center_y = h / 2
        radius_inner = min(w, h) * 0.2
        max_bar_length = min(w, h) * 0.25
        pen_width_glow = state.visualizer_bar_width + 4
        for i, val in enumerate(self.audio_data):
            angle = (360.0 / self.bars) * i - 90
            angle_rad = math.radians(angle)
            bar_len = val * max_bar_length
            x1 = center_x + radius_inner * math.cos(angle_rad)
            y1 = center_y + radius_inner * math.sin(angle_rad)
            x2 = center_x + (radius_inner + bar_len) * math.cos(angle_rad)
            y2 = center_y + (radius_inner + bar_len) * math.sin(angle_rad)
            color = self.get_color_for_bar(i, self.bars)
            glow_color = QColor(color)
            glow_color.setAlpha(60)
            painter.setPen(QPen(glow_color, pen_width_glow, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            painter.setPen(QPen(color, state.visualizer_bar_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        painter.setPen(QPen(self.color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(center_x, center_y), radius_inner, radius_inner)

class AudioEngine(QThread):
    data_ready = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.running = False
        self.CHUNK = 1024

    def run(self):
        if not AUDIO_VIS_AVAILABLE:
            return
        self.running = True
        p = pyaudio.PyAudio()
        try:
            default_speakers = p.get_default_wasapi_loopback()
            stream = p.open(
                format=pyaudio.paFloat32,
                channels=2,
                rate=int(default_speakers['defaultSampleRate']),
                input=True,
                input_device_index=default_speakers['index'],
                frames_per_buffer=self.CHUNK
            )
            while self.running:
                try:
                    data = stream.read(self.CHUNK, exception_on_overflow=False)
                    self.process_audio(data)
                except:
                    time.sleep(0.1)
        except Exception as e:
            state.log(f"Audio Engine Error: {e}", "ERROR")
        finally:
            p.terminate()

    def process_audio(self, data):
        try:
            np_data = np.frombuffer(data, dtype=np.float32)
            fft_data = np.abs(np.fft.rfft(np_data))
            step = len(fft_data) // state.visualizer_bars
            if step > 0:
                bar_data = []
                for i in range(state.visualizer_bars):
                    idx = i * step
                    val = np.mean(fft_data[idx:idx+step])
                    val = min(1.0, val * 20.0)
                    bar_data.append(val)
                self.data_ready.emit(np.array(bar_data))
        except:
            pass

    def stop(self):
        self.running = False

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
        if not PYNPUT_AVAILABLE:
            return False
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
                except:
                    pass
        if self.hotkeys:
            self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release, suppress=False)
            self.listener.start()

    def _on_press(self, key):
        if not self.enabled:
            return
        canonical = self.listener.canonical(key)
        for hotkey in self.hotkeys:
            hotkey.press(canonical)

    def _on_release(self, key):
        if not self.enabled:
            return
        canonical = self.listener.canonical(key)
        for hotkey in self.hotkeys:
            hotkey.release(canonical)

    def stop(self):
        if self.listener:
            self.listener.stop()

# ==================== MPV & WINDOW MANAGEMENT ====================
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

def prepare_window_styles(hwnd):
    try:
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        style = win32con.WS_POPUP | win32con.WS_CLIPCHILDREN | win32con.WS_CLIPSIBLINGS
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
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
    if not state.monitors:
        return (0, 0, 1920, 1080)
    min_x = min(m['x'] for m in state.monitors)
    min_y = min(m['y'] for m in state.monitors)
    max_x = max(m['x'] + m['width'] for m in state.monitors)
    max_y = max(m['y'] + m['height'] for m in state.monitors)
    return (min_x, min_y, max_x - min_x, max_y - max_y)

def launch_mpv(video, x, y, width, height):
    geometry = f"{width}x{height}+{x}+{y}"
    args = [
        "mpv", "--loop-file=inf", "--no-audio", "--border=no", "--force-window=immediate",
        "--keepaspect=no", "--profile=fast", "--hwdec=auto-safe", "--framedrop=decoder+vo",
        "--no-input-default-bindings", "--no-osc", "--really-quiet", "--ontop=no",
        "--input-cursor=no", "--cursor-autohide=no", "--geometry=" + geometry, video
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
    return subprocess.Popen(args, creationflags=creationflags)

def keep_at_bottom(hwnd):
    while True:
        try:
            if not win32gui.IsWindow(hwnd):
                break
            win32gui.SetWindowPos(hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                                win32con.SWP_NOACTIVATE | 0x0200)
            time.sleep(2)
        except:
            break

def setup_wallpaper_window(p, monitor_idx):
    try:
        hwnd = find_window(p.pid, timeout=10)
        if not hwnd:
            return None, None
        x, y, w, h = get_monitor_geometry(monitor_idx)
        win32gui.ShowWindow(hwnd, SW_HIDE)
        prepare_window_styles(hwnd)
        time.sleep(0.4)
        if not win32gui.IsWindow(hwnd):
            return None, None
        win32gui.SetWindowPos(hwnd, win32con.HWND_BOTTOM, x, y, w, h,
                            win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED |
                            0x0200 | win32con.SWP_SHOWWINDOW)
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
            try:
                p.kill()
            except:
                pass
    state.processes = {}

def instant_switch_monitor(monitor_idx, new_video_idx):
    if not state.videos or new_video_idx >= len(state.videos):
        return False
    new_video = state.videos[new_video_idx]
    if monitor_idx in state.processes:
        for p in state.processes[monitor_idx]:
            try:
                p.kill()
            except:
                pass
        state.processes[monitor_idx] = []
    try:
        x, y, w, h = get_monitor_geometry(monitor_idx)
        p = launch_mpv(new_video, x, y, w, h)
        hwnd, p = setup_wallpaper_window(p, monitor_idx)
        if hwnd:
            state.processes[monitor_idx] = [p]
            return True
        return False
    except:
        return False

def crossfade_monitor(monitor_idx, new_video_idx):
    with state.lock:
        if state.transition_active:
            return False
        state.transition_active = True
        if not state.videos or new_video_idx >= len(state.videos):
            state.transition_active = False
            return False
        new_video = state.videos[new_video_idx]
        state.log(f"Monitor {monitor_idx}: Crossfading to {os.path.basename(new_video)}")
        try:
            x, y, w, h = get_monitor_geometry(monitor_idx)
            old_procs = state.processes.get(monitor_idx, []).copy()
            new_p = launch_mpv(new_video, x, y, w, h)
            new_hwnd = find_window(new_p.pid, timeout=10)
            if not new_hwnd:
                state.transition_active = False
                return False
            win32gui.ShowWindow(new_hwnd, SW_HIDE)
            prepare_window_styles(new_hwnd)
            set_window_opacity(new_hwnd, 0)
            win32gui.SetWindowPos(new_hwnd, win32con.HWND_BOTTOM, x, y, w, h,
                                win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED | 0x0200 | win32con.SWP_SHOWWINDOW)
            if monitor_idx not in state.processes:
                state.processes[monitor_idx] = []
            state.processes[monitor_idx].append(new_p)
            threading.Thread(target=keep_at_bottom, args=(new_hwnd,), daemon=True).start()
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
                        if old_hwnd:
                            set_window_opacity(old_hwnd, old_opacity)
                    except:
                        pass
                time.sleep(step_duration)
            for old_p in old_procs:
                try:
                    old_p.kill()
                except:
                    pass
            state.processes[monitor_idx] = [p for p in state.processes[monitor_idx] if p.poll() is None]
            return True
        except Exception as e:
            state.log(f"Transition error: {e}", "ERROR")
            return False
        finally:
            state.transition_active = False

def start_wallpaper(video=None):
    """Start wallpaper on all monitors"""
    stop_wallpapers()
    if not state.videos:
        state.log("No videos in library", "WARNING")
        return
    
    # If video is None, use current_index
    if video is None:
        video = state.videos[state.current_index]
    
    if state.current_mode == "span":
        x, y, w, h = get_monitor_geometry()
        p = launch_mpv(video, x, y, w, h)
        hwnd, p = setup_wallpaper_window(p, 0)
        if hwnd:
            state.processes = {0: [p]}
            state.log(f"Started wallpaper: {os.path.basename(video)}")
    else:
        # Individual or duplicate mode
        for i in range(len(state.monitors)):
            video_idx = state.current_index
            if state.current_mode == "individual":
                video_idx = state.monitor_assignments.get(i, i) % len(state.videos)
                video_to_use = state.videos[video_idx]
            else:  # duplicate mode
                video_to_use = video
                
            threading.Thread(target=instant_switch_monitor, args=(i, video_idx if state.current_mode == "individual" else state.current_index), daemon=True).start()
            time.sleep(0.2)  # Small delay to prevent conflicts

def next_wallpaper():
    if not state.videos:
        return
    state.current_index = (state.current_index + 1) % len(state.videos)
    if state.current_mode == "individual":
        for i in range(len(state.monitors)):
            new_idx = (state.monitor_assignments.get(i, 0) + 1) % len(state.videos)
            state.monitor_assignments[i] = new_idx
            threading.Thread(target=crossfade_monitor, args=(i, new_idx), daemon=True).start()
    else:
        start_wallpaper()

def prev_wallpaper():
    if not state.videos:
        return
    state.current_index = (state.current_index - 1) % len(state.videos)
    if state.current_mode == "individual":
        for i in range(len(state.monitors)):
            new_idx = (state.monitor_assignments.get(i, 0) - 1) % len(state.videos)
            state.monitor_assignments[i] = new_idx
            threading.Thread(target=crossfade_monitor, args=(i, new_idx), daemon=True).start()
    else:
        start_wallpaper()

def random_wallpaper():
    """Set a random wallpaper from the library"""
    if not state.videos:
        state.log("No videos in library to set random wallpaper", "WARNING")
        # Show message to user if QApplication exists
        try:
            QMessageBox.information(None, "No Videos", "Please add videos to the library first")
        except:
            pass
        return
    
    # Generate random index
    new_index = random.randint(0, len(state.videos) - 1)
    state.current_index = new_index
    video_name = os.path.basename(state.videos[new_index])
    state.log(f"Setting random wallpaper: {video_name}")
    
    if state.current_mode == "individual":
        # For individual mode, set all monitors to the same random video
        for i in range(len(state.monitors)):
            state.monitor_assignments[i] = new_index
            # Use threading for smooth transitions
            threading.Thread(target=crossfade_monitor, args=(i, new_index), daemon=True).start()
    else:
        # For span or duplicate mode
        stop_wallpapers()  # Clean stop before starting new
        time.sleep(0.1)    # Brief pause
        start_wallpaper(state.videos[new_index])

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
                state.theme = config.get('theme', DEFAULT_SETTINGS["theme"])
                state.visualizer_enabled = config.get('visualizer_enabled', DEFAULT_SETTINGS["visualizer_enabled"])
                state.visualizer_style = config.get('visualizer_style', DEFAULT_SETTINGS["visualizer_style"])
                state.visualizer_bars = config.get('visualizer_bars', DEFAULT_SETTINGS["visualizer_bars"])
                state.visualizer_height = config.get('visualizer_height', DEFAULT_SETTINGS["visualizer_height"])
                state.visualizer_rainbow = config.get('visualizer_rainbow', DEFAULT_SETTINGS["visualizer_rainbow"])
                state.visualizer_bar_width = config.get('visualizer_bar_width', DEFAULT_SETTINGS["visualizer_bar_width"])
                state.shortcuts_enabled = config.get('shortcuts_enabled', DEFAULT_SETTINGS["shortcuts_enabled"])
        except:
            pass

def save_config():
    config = {
        'mode': state.current_mode,
        'assignments': state.monitor_assignments,
        'transition_duration': state.transition_duration,
        'auto_change_enabled': state.auto_change_enabled,
        'auto_change_interval': state.auto_change_interval,
        'theme': state.theme,
        'visualizer_enabled': state.visualizer_enabled,
        'visualizer_style': state.visualizer_style,
        'visualizer_bars': state.visualizer_bars,
        'visualizer_height': state.visualizer_height,
        'visualizer_rainbow': state.visualizer_rainbow,
        'visualizer_bar_width': state.visualizer_bar_width,
        'shortcuts_enabled': state.shortcuts_enabled
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except:
        pass

def load_videos():
    state.videos = []
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)
    for f in os.listdir(SAVE_DIR):
        if f.lower().endswith(VIDEO_EXTENSIONS):
            state.videos.append(os.path.join(SAVE_DIR, f))
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
        if "download" in a.text.lower() and a.get("href"):
            return a["href"]
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
                if progress_callback and total > 0:
                    progress_callback(int(downloaded * 100 / total))
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
            self.finished.emit(search_wallpapers(self.keyword))
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
                self.error.emit("Link not found")
                return
            filepath = download_video(dl_url, lambda p: self.progress.emit(p))
            self.finished.emit(filepath)
        except Exception as e:
            self.error.emit(str(e))

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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(200, 120)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.is_local:
            self.thumb_label.setText("🎬")
            font = self.thumb_label.font()
            font.setPointSize(24)
            self.thumb_label.setFont(font)
        else:
            self.thumb_label.setText("⬇")
            self.load_thumbnail()
        layout.addWidget(self.thumb_label, alignment=Qt.AlignmentFlag.AlignCenter)
        title = os.path.basename(self.video_path) if self.is_local else self.online_data.get("title", "Unknown")
        self.title_label = QLabel(title[:30] + "..." if len(title) > 30 else title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        btn_layout = QHBoxLayout()
        if self.is_local:
            set_btn = QPushButton("Set")
            set_btn.setObjectName("btnPrimary")
            set_btn.clicked.connect(lambda: self.set_clicked.emit(self.video_path))
            btn_layout.addWidget(set_btn)
        else:
            dl_btn = QPushButton("Download")
            dl_btn.setObjectName("btnPrimary")
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
        self.search_input.returnPressed.connect(self.do_search)
        search_layout.addWidget(self.search_input)
        self.search_btn = QPushButton("🔍 Search")
        self.search_btn.setObjectName("btnPrimary")
        self.search_btn.clicked.connect(self.do_search)
        search_layout.addWidget(self.search_btn)
        layout.addLayout(search_layout)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.results_container = QWidget()
        self.results_layout = QGridLayout(self.results_container)
        self.results_layout.setSpacing(15)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.results_container)
        layout.addWidget(scroll)
        self.status_label = QLabel("Enter a search term to find wallpapers")
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
        if self.parent:
            self.parent.refresh_library()
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
        controls.addWidget(self.info_label)
        controls.addStretch()
        add_btn = QPushButton("+ Add Videos")
        add_btn.setObjectName("btnSecondary")
        add_btn.clicked.connect(self.add_videos)
        controls.addWidget(add_btn)
        open_btn = QPushButton("📁 Open Folder")
        open_btn.setObjectName("btnSecondary")
        open_btn.clicked.connect(self.open_folder)
        controls.addWidget(open_btn)
        layout.addLayout(controls)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.library_container = QWidget()
        self.library_layout = QGridLayout(self.library_container)
        self.library_layout.setSpacing(15)
        self.library_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.library_container)
        layout.addWidget(scroll)
        actions_box = QGroupBox("Quick Actions")
        actions_layout = QHBoxLayout(actions_box)
        prev_btn = QPushButton("⏮ Previous")
        prev_btn.setObjectName("btnSecondary")
        prev_btn.clicked.connect(prev_wallpaper)
        actions_layout.addWidget(prev_btn)
        next_btn = QPushButton("▶ Next Wallpaper")
        next_btn.setObjectName("btnPrimary")
        next_btn.clicked.connect(next_wallpaper)
        actions_layout.addWidget(next_btn)
        random_btn = QPushButton("🔀 Random")
        random_btn.setObjectName("btnSecondary")
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
            self.library_layout.addWidget(card, i // 3, i % 3)

    def set_wallpaper(self, video_path):
        try:
            idx = state.videos.index(video_path)
            state.current_index = idx
            if state.current_mode == "individual":
                for i in range(len(state.monitors)):
                    state.monitor_assignments[i] = idx
                    threading.Thread(target=crossfade_monitor, args=(i, idx), daemon=True).start()
            else:
                start_wallpaper(video_path)
        except:
            pass

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
        if not os.path.exists(SAVE_DIR):
            os.makedirs(SAVE_DIR)
        os.startfile(SAVE_DIR)

class DisplayTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)

        # Theme
        theme_box = QGroupBox("Interface Theme")
        theme_layout = QHBoxLayout(theme_box)
        theme_label = QLabel("Select Theme:")
        theme_layout.addWidget(theme_label)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(ThemeManager.THEMES.keys()))
        self.theme_combo.currentTextChanged.connect(self.on_theme_changed)
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addStretch()
        layout.addWidget(theme_box)

        # Visualizer
        vis_box = QGroupBox("Audio Visualizer")
        vis_layout = QVBoxLayout(vis_box)
        row1 = QHBoxLayout()
        self.vis_check = QCheckBox("Enable")
        self.vis_check.setChecked(state.visualizer_enabled)
        self.vis_check.stateChanged.connect(self.on_vis_toggled)
        row1.addWidget(self.vis_check)
        row1.addWidget(QLabel("Style:"))
        self.vis_style_combo = QComboBox()
        self.vis_style_combo.addItems(["Bars", "Slim", "Wave", "Wave Dots", "Radial"])
        self.vis_style_combo.setCurrentText(state.visualizer_style)
        self.vis_style_combo.currentTextChanged.connect(self.on_vis_style_changed)
        row1.addWidget(self.vis_style_combo)
        row1.addStretch()
        vis_layout.addLayout(row1)
        row2 = QHBoxLayout()
        self.rainbow_check = QCheckBox("Rainbow Mode")
        self.rainbow_check.setChecked(state.visualizer_rainbow)
        self.rainbow_check.stateChanged.connect(self.on_rainbow_toggled)
        row2.addWidget(self.rainbow_check)
        row2.addWidget(QLabel("Width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 20)
        self.width_spin.setValue(state.visualizer_bar_width)
        self.width_spin.valueChanged.connect(self.on_width_changed)
        row2.addWidget(self.width_spin)
        row2.addStretch()
        vis_layout.addLayout(row2)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Bars:"))
        self.vis_bars_spin = QSpinBox()
        self.vis_bars_spin.setRange(16, 200)
        self.vis_bars_spin.setValue(state.visualizer_bars)
        self.vis_bars_spin.valueChanged.connect(self.on_vis_bars_changed)
        row3.addWidget(self.vis_bars_spin)
        row3.addWidget(QLabel("Height/Size:"))
        self.vis_height_spin = QSpinBox()
        self.vis_height_spin.setRange(30, 300)
        self.vis_height_spin.setValue(state.visualizer_height)
        self.vis_height_spin.valueChanged.connect(self.on_vis_height_changed)
        row3.addWidget(self.vis_height_spin)
        row3.addStretch()
        vis_layout.addLayout(row3)
        if not AUDIO_VIS_AVAILABLE:
            self.vis_check.setEnabled(False)
            err_label = QLabel("Requires: pip install pyaudiowpatch numpy")
            err_label.setStyleSheet("color: red;")
            vis_layout.addWidget(err_label)
        layout.addWidget(vis_box)

        # Keyboard Shortcuts
        shortcut_box = QGroupBox("Keyboard Shortcuts")
        shortcut_layout = QVBoxLayout(shortcut_box)

        self.shortcut_check = QCheckBox("Enable Keyboard Shortcuts")
        self.shortcut_check.setChecked(state.shortcuts_enabled)
        self.shortcut_check.stateChanged.connect(self.on_shortcut_toggled)
        shortcut_layout.addWidget(self.shortcut_check)

        info_layout = QGridLayout()
        info_layout.addWidget(QLabel("Next Wallpaper:"), 0, 0)
        info_layout.addWidget(QLabel("Ctrl + Shift + N"), 0, 1)
        info_layout.addWidget(QLabel("Previous Wallpaper:"), 1, 0)
        info_layout.addWidget(QLabel("Ctrl + Shift + P"), 1, 1)
        info_layout.addWidget(QLabel("Random Wallpaper:"), 2, 0)
        info_layout.addWidget(QLabel("Ctrl + Shift + R"), 2, 1)
        info_layout.addWidget(QLabel("Toggle Visualizer:"), 3, 0)
        info_layout.addWidget(QLabel("Ctrl + Shift + T"), 3, 1)
        shortcut_layout.addLayout(info_layout)

        if not PYNPUT_AVAILABLE:
            warn_label = QLabel("⚠️ Requires: pip install pynput")
            warn_label.setStyleSheet("color: orange;")
            shortcut_layout.addWidget(warn_label)
            self.shortcut_check.setEnabled(False)

        layout.addWidget(shortcut_box)

        # Display Mode
        mode_box = QGroupBox("Display Mode")
        mode_layout = QVBoxLayout(mode_box)
        self.mode_group = QButtonGroup(self)
        modes = [("span", "Span", "One video across all monitors"),
                 ("duplicate", "Duplicate", "Same video on all monitors"),
                 ("individual", "Individual", "Different video per monitor")]
        for value, name, desc in modes:
            row = QHBoxLayout()
            rb = QRadioButton(name)
            rb.mode_value = value
            self.mode_group.addButton(rb)
            row.addWidget(rb)
            lbl = QLabel(desc)
            row.addWidget(lbl)
            row.addStretch()
            mode_layout.addLayout(row)
        self.mode_group.buttonClicked.connect(self.on_mode_changed)
        layout.addWidget(mode_box)

        self.monitor_box = QGroupBox("Per-Monitor Assignment")
        self.monitor_layout = QVBoxLayout(self.monitor_box)
        self.monitor_box.setVisible(False)
        layout.addWidget(self.monitor_box)

        # Transitions
        trans_box = QGroupBox("Transition Effects")
        trans_layout = QVBoxLayout(trans_box)
        duration_row = QHBoxLayout()
        duration_row.addWidget(QLabel("Duration:"))
        self.duration_slider = QSlider(Qt.Orientation.Horizontal)
        self.duration_slider.setRange(5, 30)
        self.duration_slider.setValue(12)
        self.duration_slider.valueChanged.connect(self.on_duration_changed)
        duration_row.addWidget(self.duration_slider)
        self.duration_label = QLabel("1.2s")
        duration_row.addWidget(self.duration_label)
        trans_layout.addLayout(duration_row)
        test_btn = QPushButton("▶ Test Transition")
        test_btn.setObjectName("btnPrimary")
        test_btn.clicked.connect(self.test_transition)
        trans_layout.addWidget(test_btn)
        layout.addWidget(trans_box)

        # Auto Change
        auto_box = QGroupBox("Auto-Change Timer")
        auto_layout = QVBoxLayout(auto_box)
        self.auto_check = QCheckBox("Enable Auto-Change")
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
        idx = self.theme_combo.findText(state.theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
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
            if item.widget():
                item.widget().deleteLater()
        if state.current_mode != "individual" or len(state.monitors) <= 1:
            self.monitor_box.setVisible(False)
            return
        self.monitor_box.setVisible(True)
        for i, m in enumerate(state.monitors):
            row = QHBoxLayout()
            info = f"Monitor {i+1} - {m['width']}x{m['height']}"
            row.addWidget(QLabel(info))
            combo = QComboBox()
            for v in state.videos:
                combo.addItem(os.path.basename(v))
            current = state.monitor_assignments.get(i, i) % len(state.videos) if state.videos else 0
            combo.setCurrentIndex(current)
            combo.currentIndexChanged.connect(lambda idx, mon=i: self.on_monitor_video_changed(mon, idx))
            row.addWidget(combo)
            self.monitor_layout.addLayout(row)

    def on_theme_changed(self, theme_name):
        state.theme = theme_name
        save_config()
        if self.parent:
            self.parent.apply_theme(theme_name)

    def on_vis_toggled(self, state_val):
        state.visualizer_enabled = bool(state_val)
        save_config()
        if self.parent:
            self.parent.toggle_visualizer(state.visualizer_enabled)

    def on_vis_style_changed(self, style):
        state.visualizer_style = style
        save_config()
        if self.parent and hasattr(self.parent, 'visualizer_window') and self.parent.visualizer_window:
            self.parent.visualizer_window.style = style
            self.parent.visualizer_window.resize_screen()

    def on_rainbow_toggled(self, state_val):
        state.visualizer_rainbow = bool(state_val)
        save_config()

    def on_width_changed(self, val):
        state.visualizer_bar_width = val
        save_config()

    def on_vis_bars_changed(self, val):
        state.visualizer_bars = val
        save_config()
        if self.parent and hasattr(self.parent, 'visualizer_window') and self.parent.visualizer_window:
            self.parent.visualizer_window.bars = val
            self.parent.visualizer_window.audio_data = np.zeros(val)

    def on_vis_height_changed(self, val):
        state.visualizer_height = val
        save_config()
        if self.parent and hasattr(self.parent, 'visualizer_window') and self.parent.visualizer_window:
            self.parent.visualizer_window.height_factor = val
            self.parent.visualizer_window.resize_screen()

    def on_shortcut_toggled(self, state_val):
        state.shortcuts_enabled = bool(state_val)
        save_config()
        if self.parent and hasattr(self.parent, 'keyboard_handler'):
            self.parent.keyboard_handler.stop()
            if state.shortcuts_enabled and PYNPUT_AVAILABLE:
                self.parent.keyboard_handler.start()

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
        load_config()
        detect_monitors()
        load_videos()
        tabs = QTabWidget()
        tabs.addTab(LibraryTab(self), "📁 Library")
        tabs.addTab(MoeWallsTab(self), "🌐 MoeWalls")
        tabs.addTab(DisplayTab(self), "🖥 Display")
        self.setCentralWidget(tabs)

        # Visualizer Init
        self.visualizer_window = None
        self.audio_engine = None
        if state.visualizer_enabled and AUDIO_VIS_AVAILABLE:
            self.toggle_visualizer(True)

        # Keyboard Shortcuts Init
        self.keyboard_handler = KeyboardHandler()
        self.keyboard_handler.next_signal.connect(next_wallpaper)
        self.keyboard_handler.prev_signal.connect(prev_wallpaper)
        self.keyboard_handler.random_signal.connect(random_wallpaper)
        self.keyboard_handler.toggle_signal.connect(self.toggle_visualizer_tray)
        if state.shortcuts_enabled and PYNPUT_AVAILABLE:
            if self.keyboard_handler.start():
                state.log("Keyboard shortcuts enabled")
            else:
                state.log("Failed to start keyboard shortcuts")
        else:
            if not PYNPUT_AVAILABLE:
                state.log("pynput not available - keyboard shortcuts disabled")

        # System Tray
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        tray_menu = QMenu()
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
        self.vis_tray_action = QAction("Visualizer: ON" if state.visualizer_enabled else "Visualizer: OFF", self)
        self.vis_tray_action.triggered.connect(self.toggle_visualizer_tray)
        tray_menu.addAction(self.vis_tray_action)
        tray_menu.addSeparator()
        stop_action = QAction("Stop Wallpapers", self)
        stop_action.triggered.connect(stop_wallpapers)
        tray_menu.addAction(stop_action)
        tray_menu.addSeparator()
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self.show)
        show_action.triggered.connect(self.activateWindow)
        tray_menu.addAction(show_action)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def toggle_visualizer_tray(self):
        is_enabled = not state.visualizer_enabled
        state.visualizer_enabled = is_enabled
        save_config()
        self.toggle_visualizer(is_enabled)
        self.vis_tray_action.setText("Visualizer: ON" if is_enabled else "Visualizer: OFF")

    def toggle_visualizer(self, enabled):
        if not AUDIO_VIS_AVAILABLE:
            return
        if enabled:
            if not self.visualizer_window:
                self.visualizer_window = AudioVisualizerWindow(theme_engine)
                self.visualizer_window.show()
            if not self.audio_engine:
                self.audio_engine = AudioEngine()
                self.audio_engine.bars = state.visualizer_bars
                self.audio_engine.data_ready.connect(self.visualizer_window.update_data)
                self.audio_engine.start()
        else:
            if self.audio_engine:
                self.audio_engine.stop()
                self.audio_engine = None
            if self.visualizer_window:
                self.visualizer_window.close()
                self.visualizer_window = None

    def closeEvent(self, event):
        if hasattr(self, 'keyboard_handler') and self.keyboard_handler:
            self.keyboard_handler.stop()
        event.ignore()
        self.hide()

    def refresh_library(self):
        central = self.centralWidget()
        if isinstance(central, QTabWidget):
            lib_tab = central.widget(0)
            if hasattr(lib_tab, 'refresh_library'):
                lib_tab.refresh_library()

    def apply_theme(self, theme_name):
        if theme_engine:
            theme_engine.set_theme(theme_name)

if __name__ == "__main__":
    # Get the correct path for both script and exe
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        application_path = os.path.dirname(sys.executable)
        # Set a more specific AppUserModelID
        myappid = 'VideoWallpaperManager.MainApp.1.0'
    else:
        # Running as script
        application_path = os.path.dirname(os.path.abspath(__file__))
        myappid = 'com.videowallpaper.app.script.1.0'
    
    # Set Windows App User Model ID (important for taskbar icon)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception as e:
        print(f"Failed to set AppUserModelID: {e}")

    app = QApplication(sys.argv)

    # Load icon with multiple fallback methods
    icon = QIcon()
    
    # Try loading from various possible locations
    icon_paths = [
        os.path.join(application_path, 'icon.ico'),
        os.path.join(application_path, 'resources', 'icon.ico'),
        os.path.join(os.path.dirname(application_path), 'icon.ico'),
        os.path.join(os.getcwd(), 'icon.ico'),
    ]
    
    for icon_path in icon_paths:
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            app.setWindowIcon(icon)
            print(f"Loaded icon from: {icon_path}")
            break
    
    # If no icon found, create a default one
    if icon.isNull():
        print("No icon file found, using default icon")
        # Create a simple colored icon as fallback
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor('#00d4aa'))
        icon = QIcon(pixmap)
        app.setWindowIcon(icon)

    # Initialize Theme Engine
    theme_engine = ThemeManager(app)
    theme_engine.set_theme(state.theme)

    window = MainWindow()
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()
    
    sys.exit(app.exec())
