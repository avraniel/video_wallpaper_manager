#!/usr/bin/env python3
"""
Video Wallpaper Manager - Complete Version with Format Selection
- Choose between MP4 (smaller) and WebM (better quality)
- Fixed MoeWalls download links
- Fixed auto-change timer
- Fixed tab references
- Added manual download option
- Improved error handling
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
import signal
import psutil
import shutil
import webbrowser
from datetime import datetime
from collections import deque
from urllib.parse import quote, urljoin
from io import BytesIO
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QMessageBox, QTabWidget, 
    QComboBox, QSlider, QCheckBox, QGroupBox, QGridLayout, 
    QSpinBox, QSystemTrayIcon, QMenu, QProgressBar, QFileDialog, 
    QFrame, QScrollArea, QRadioButton, QButtonGroup, QStyle,
    QListWidget
)
from PyQt6.QtGui import QPixmap, QIcon, QAction, QColor
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PIL import Image
from bs4 import BeautifulSoup
import win32gui
import win32con
import win32process
import win32api
from screeninfo import get_monitors

# ==================== PATH CONFIGURATION ====================
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
DEFAULT_VIDEO_PATH = os.path.join(os.path.expanduser("~"), "Videos", "wallpapers")

def load_settings():
    """Load settings from JSON file"""
    default_settings = {
        "video_path": DEFAULT_VIDEO_PATH,
        "library_paths": [],
        "check_subfolders": False,
        "preferred_format": "mp4"  # Default format
    }
    
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                for key in default_settings:
                    if key not in settings:
                        settings[key] = default_settings[key]
                return settings
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading settings: {e}")
            return default_settings
    return default_settings

def save_settings(settings):
    """Save settings to JSON file"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False

def get_video_path():
    """Get the video storage path from settings"""
    settings = load_settings()
    path = settings.get("video_path", DEFAULT_VIDEO_PATH)
    
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except Exception as e:
            print(f"Error creating video directory: {e}")
            path = DEFAULT_VIDEO_PATH
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
    
    return path

def get_config_file():
    """Get the configuration file path"""
    return os.path.join(get_video_path(), "config.json")

def get_log_file():
    """Get the log file path"""
    return os.path.join(get_video_path(), "wallpaper.log")

# Set global paths
SAVE_DIR = get_video_path()
CONFIG_FILE = get_config_file()
LOG_FILE = get_log_file()

# ==================== CONFIGURATION ====================
BASE_URL = "https://moewalls.com"
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mkv")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MAX_RETRIES = 3
RETRY_DELAY = 1
PROCESS_CLEANUP_TIMEOUT = 3
PROCESS_HEALTH_CHECK_INTERVAL = 5

DEFAULT_SETTINGS = {
    "mode": "individual",
    "transition_duration": 1.2,
    "transition_fps": 60,
    "auto_change_enabled": False,
    "auto_change_interval": 300,
    "monitor_assignments": {},
    "theme": "Dark",
    "accent_color": "#00d4aa",
    "library_paths": [],
    "preferred_format": "mp4"
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
        self.video_paths = set()
        self.current_index = 0
        self.processes = {}
        self.process_info = {}
        self.monitors = []
        self.current_mode = DEFAULT_SETTINGS["mode"]
        self.monitor_assignments = {}
        self.transition_duration = DEFAULT_SETTINGS["transition_duration"]
        self.auto_change_enabled = DEFAULT_SETTINGS["auto_change_enabled"]
        self.auto_change_interval = DEFAULT_SETTINGS["auto_change_interval"]
        self.theme = DEFAULT_SETTINGS["theme"]
        self.transition_active = False
        self.log_entries = deque(maxlen=1000)
        self.lock = threading.RLock()
        self.shutting_down = False
        self.mpv_path = None
        self.process_monitor_running = False
        self.library_paths = set()
        self.save_dir = SAVE_DIR
        self.check_subfolders = False
        self.settings_tab = None
        self.library_tab = None
        self.auto_change_thread = None
        self.preferred_format = "mp4"

    def log(self, message, level="INFO"):
        if self.shutting_down:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] [{level}] {message}"
        self.log_entries.append(entry)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except (IOError, OSError) as e:
            print(f"Failed to write to log: {e}")
        print(entry)

state = AppState()

# ==================== VIDEO LIBRARY MANAGEMENT ====================
def scan_folder_for_videos(folder, recursive=False):
    """Scan a folder for video files"""
    videos = []
    try:
        if recursive:
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if file.lower().endswith(VIDEO_EXTENSIONS):
                        videos.append(os.path.join(root, file))
        else:
            for file in os.listdir(folder):
                if file.lower().endswith(VIDEO_EXTENSIONS):
                    full_path = os.path.join(folder, file)
                    if os.path.isfile(full_path):
                        videos.append(full_path)
    except Exception as e:
        state.log(f"Error scanning folder {folder}: {e}", "ERROR")
    
    return videos

def load_videos():
    """Load videos from all library paths"""
    state.videos = []
    state.video_paths = set()
    
    settings = load_settings()
    check_subfolders = settings.get("check_subfolders", False)
    
    library_paths = [state.save_dir] + list(state.library_paths)
    
    for library_path in library_paths:
        if not os.path.exists(library_path):
            state.log(f"Library path does not exist: {library_path}", "WARNING")
            continue
            
        videos = scan_folder_for_videos(library_path, check_subfolders)
        
        for video_path in videos:
            if video_path not in state.video_paths:
                state.videos.append(video_path)
                state.video_paths.add(video_path)
    
    state.videos.sort()
    state.log(f"Loaded {len(state.videos)} videos from {len(library_paths)} location(s)")
    
    if state.videos and state.current_index >= len(state.videos):
        state.current_index = 0

def add_library_path(path):
    """Add a new library path and scan for videos"""
    if os.path.exists(path) and os.path.isdir(path):
        if path not in state.library_paths:
            state.library_paths.add(path)
            
            settings = load_settings()
            settings["library_paths"] = list(state.library_paths)
            save_settings(settings)
            
            load_videos()
            save_config()
            state.log(f"Added library path: {path}")
            return True
    return False

def remove_library_path(path):
    """Remove a library path"""
    if path in state.library_paths:
        state.library_paths.remove(path)
        
        settings = load_settings()
        settings["library_paths"] = list(state.library_paths)
        save_settings(settings)
        
        load_videos()
        save_config()
        state.log(f"Removed library path: {path}")
        return True
    return False

def add_video_to_library(source_path):
    """Add a video to the main library"""
    if not os.path.exists(source_path):
        return None
        
    filename = os.path.basename(source_path)
    dest_path = os.path.join(state.save_dir, filename)
    
    if os.path.exists(dest_path):
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(dest_path):
            new_filename = f"{base}_{counter}{ext}"
            dest_path = os.path.join(state.save_dir, new_filename)
            counter += 1
    
    try:
        shutil.copy2(source_path, dest_path)
        state.log(f"Added video to library: {os.path.basename(dest_path)}")
        load_videos()
        return dest_path
    except Exception as e:
        state.log(f"Error adding video: {e}", "ERROR")
        return None

def change_video_storage_location(new_path):
    """Change the video storage location and migrate videos"""
    if not os.path.exists(new_path):
        try:
            os.makedirs(new_path)
        except Exception as e:
            state.log(f"Error creating new directory: {e}", "ERROR")
            return False
    
    old_path = state.save_dir
    
    settings = load_settings()
    settings["video_path"] = new_path
    if save_settings(settings):
        global SAVE_DIR, CONFIG_FILE, LOG_FILE
        SAVE_DIR = new_path
        CONFIG_FILE = os.path.join(new_path, "config.json")
        LOG_FILE = os.path.join(new_path, "wallpaper.log")
        state.save_dir = new_path
        
        reply = QMessageBox.question(
            None,
            "Migrate Videos",
            f"Do you want to copy existing videos from\n{old_path}\nto\n{new_path}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes and os.path.exists(old_path):
            try:
                if os.path.exists(os.path.join(old_path, "config.json")):
                    shutil.copy2(
                        os.path.join(old_path, "config.json"),
                        os.path.join(new_path, "config.json")
                    )
                
                for filename in os.listdir(old_path):
                    if filename.lower().endswith(VIDEO_EXTENSIONS):
                        src = os.path.join(old_path, filename)
                        dst = os.path.join(new_path, filename)
                        if not os.path.exists(dst):
                            shutil.copy2(src, dst)
                
                state.log("Videos migrated successfully")
            except Exception as e:
                state.log(f"Error migrating videos: {e}", "ERROR")
        
        load_videos()
        return True
    
    return False

# ==================== CONFIG & DATA ====================
def load_config():
    """Load configuration with validation"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if not isinstance(config, dict):
                state.log("Invalid config format, using defaults", "WARNING")
                return
            
            if 'mode' in config and config['mode'] in ["span", "duplicate", "individual"]:
                state.current_mode = config['mode']
            
            if 'assignments' in config and isinstance(config['assignments'], dict):
                state.monitor_assignments = {}
                for k, v in config['assignments'].items():
                    try:
                        state.monitor_assignments[int(k)] = int(v)
                    except (ValueError, TypeError):
                        continue
                    
            if 'transition_duration' in config:
                try:
                    duration = float(config['transition_duration'])
                    state.transition_duration = max(0.5, min(3.0, duration))
                except (ValueError, TypeError):
                    pass
            
            if 'auto_change_enabled' in config:
                state.auto_change_enabled = bool(config['auto_change_enabled'])
            
            if 'auto_change_interval' in config:
                try:
                    interval = int(config['auto_change_interval'])
                    state.auto_change_interval = max(60, min(7200, interval))
                except (ValueError, TypeError):
                    pass
            
            if 'theme' in config:
                state.theme = config['theme']
            
            if 'library_paths' in config and isinstance(config['library_paths'], list):
                for path in config['library_paths']:
                    if os.path.exists(path) and os.path.isdir(path):
                        state.library_paths.add(path)
            
            if 'preferred_format' in config:
                state.preferred_format = config['preferred_format']
            
            state.log("Configuration loaded")
            
        except Exception as e:
            state.log(f"Error loading config: {e}", "ERROR")
    
    if not os.path.exists(state.save_dir):
        try:
            os.makedirs(state.save_dir)
        except Exception as e:
            state.log(f"Error creating save directory: {e}", "ERROR")

def save_config():
    """Save configuration safely"""
    config = {
        'mode': state.current_mode,
        'assignments': state.monitor_assignments,
        'transition_duration': state.transition_duration,
        'auto_change_enabled': state.auto_change_enabled,
        'auto_change_interval': state.auto_change_interval,
        'theme': state.theme,
        'library_paths': list(state.library_paths),
        'preferred_format': state.preferred_format
    }
    
    temp_file = CONFIG_FILE + ".tmp"
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        
        if os.path.exists(CONFIG_FILE):
            os.replace(temp_file, CONFIG_FILE)
        else:
            os.rename(temp_file, CONFIG_FILE)
            
        state.log("Configuration saved")
            
    except Exception as e:
        state.log(f"Error saving config: {e}", "ERROR")
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except:
            pass

# ==================== PROCESS MANAGEMENT ====================
class ProcessManager:
    """Dedicated process manager for handling MPV processes"""
    
    @staticmethod
    def get_process_info(pid):
        """Get detailed process information using psutil"""
        try:
            process = psutil.Process(pid)
            with process.oneshot():
                return {
                    'pid': pid,
                    'name': process.name(),
                    'exe': process.exe(),
                    'cmdline': process.cmdline(),
                    'status': process.status(),
                    'create_time': process.create_time(),
                    'cpu_percent': process.cpu_percent(),
                    'memory_percent': process.memory_percent(),
                    'connections': len(process.connections()),
                    'is_running': process.is_running()
                }
        except psutil.NoSuchProcess:
            return {'pid': pid, 'is_running': False}
        except (psutil.AccessDenied, psutil.ZombieProcess) as e:
            state.log(f"Access denied to process {pid}: {e}", "WARNING")
            return {'pid': pid, 'is_running': False, 'error': str(e)}
        except Exception as e:
            state.log(f"Unexpected error getting process info for {pid}: {e}", "ERROR")
            return {'pid': pid, 'is_running': False}

    @staticmethod
    def is_zombie_process(pid):
        """Check if a process is a zombie"""
        try:
            process = psutil.Process(pid)
            return process.status() == psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
        except Exception:
            return False

    @staticmethod
    def graceful_terminate(pid, timeout=PROCESS_CLEANUP_TIMEOUT):
        """Gracefully terminate a process with proper cleanup"""
        try:
            process = psutil.Process(pid)
            
            if ProcessManager.is_zombie_process(pid):
                state.log(f"Process {pid} is a zombie, killing forcefully", "WARNING")
                process.kill()
                return True
            
            state.log(f"Attempting graceful termination of process {pid}")
            process.terminate()
            
            gone, alive = psutil.wait_procs([process], timeout=timeout)
            
            if process in alive:
                state.log(f"Process {pid} did not terminate gracefully, force killing", "WARNING")
                process.kill()
                
                gone, alive = psutil.wait_procs([process], timeout=timeout/2)
                
                if process in alive:
                    state.log(f"Process {pid} still alive after kill", "ERROR")
                    return False
            
            try:
                handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, pid)
                if handle:
                    win32api.CloseHandle(handle)
            except (win32api.error, Exception):
                pass
            
            state.log(f"Process {pid} successfully terminated")
            return True
            
        except psutil.NoSuchProcess:
            return True
        except psutil.AccessDenied as e:
            state.log(f"Access denied terminating process {pid}: {e}", "ERROR")
            return False
        except Exception as e:
            state.log(f"Unexpected error terminating process {pid}: {e}", "ERROR")
            return False

    @staticmethod
    def kill_process_tree(pid, include_parent=True):
        """Kill an entire process tree"""
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            
            for child in children:
                try:
                    ProcessManager.graceful_terminate(child.pid)
                except Exception as e:
                    state.log(f"Error killing child process {child.pid}: {e}", "ERROR")
            
            if include_parent:
                ProcessManager.graceful_terminate(pid)
                
            return True
            
        except psutil.NoSuchProcess:
            return True
        except Exception as e:
            state.log(f"Error killing process tree for {pid}: {e}", "ERROR")
            return False

    @staticmethod
    def cleanup_dead_processes():
        """Clean up dead processes from state"""
        with state.lock:
            dead_pids = []
            
            for pid, info in list(state.process_info.items()):
                try:
                    process = psutil.Process(pid)
                    if not process.is_running() or ProcessManager.is_zombie_process(pid):
                        dead_pids.append(pid)
                        state.log(f"Found dead/zombie process {pid}, cleaning up")
                except psutil.NoSuchProcess:
                    dead_pids.append(pid)
                except Exception:
                    dead_pids.append(pid)
            
            for pid in dead_pids:
                if pid in state.process_info:
                    del state.process_info[pid]
                
                for monitor_idx, procs in list(state.processes.items()):
                    state.processes[monitor_idx] = [p for p in procs if p.pid != pid]
            
            return len(dead_pids)

    @staticmethod
    def get_all_mpv_processes():
        """Get all MPV processes running on the system"""
        mpv_processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] and 'mpv' in proc.info['name'].lower():
                        mpv_processes.append(proc.info)
                    elif proc.info['cmdline'] and any('mpv' in arg.lower() for arg in proc.info['cmdline']):
                        mpv_processes.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            state.log(f"Error scanning for MPV processes: {e}", "ERROR")
        
        return mpv_processes

    @staticmethod
    def cleanup_orphaned_mpv():
        """Clean up MPV processes that aren't tracked"""
        our_pids = set(state.process_info.keys())
        all_mpv = ProcessManager.get_all_mpv_processes()
        
        for proc_info in all_mpv:
            pid = proc_info['pid']
            if pid not in our_pids:
                cmdline = ' '.join(proc_info.get('cmdline', [])).lower()
                if '--geometry' in cmdline and any(res in cmdline for res in ['x', '+']):
                    state.log(f"Found orphaned MPV process {pid}, terminating")
                    ProcessManager.graceful_terminate(pid)

# ==================== PROCESS MONITOR THREAD ====================
class ProcessMonitorThread(QThread):
    """Background thread to monitor process health"""
    
    def __init__(self):
        super().__init__()
        self.running = False
        
    def run(self):
        self.running = True
        state.process_monitor_running = True
        
        while self.running and not state.shutting_down:
            try:
                dead_count = ProcessManager.cleanup_dead_processes()
                
                if dead_count > 0:
                    ProcessManager.cleanup_orphaned_mpv()
                
                for _ in range(PROCESS_HEALTH_CHECK_INTERVAL):
                    if not self.running or state.shutting_down:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                state.log(f"Process monitor error: {e}", "ERROR")
                time.sleep(5)
    
    def stop(self):
        self.running = False
        state.process_monitor_running = False

# ==================== AUTO-CHANGE TIMER ====================
class AutoChangeThread(QThread):
    """Thread for auto-changing wallpapers"""
    change_signal = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.running = False
        self.change_signal.connect(self.do_change)
        
    def do_change(self):
        """Safely trigger wallpaper change in main thread"""
        if state.auto_change_enabled and len(state.videos) > 1 and not state.shutting_down:
            state.log("Auto-change: Changing wallpaper")
            random_wallpaper()
        
    def run(self):
        self.running = True
        state.log("Auto-change thread started")
        
        while self.running and not state.shutting_down:
            try:
                if state.auto_change_enabled and len(state.videos) > 1:
                    interval = state.auto_change_interval
                    minutes = interval // 60
                    state.log(f"Auto-change: Next change in {minutes} minute(s)")
                    
                    for i in range(interval):
                        if not self.running or state.shutting_down or not state.auto_change_enabled:
                            break
                        time.sleep(1)
                        
                        if i > 0 and i % 60 == 0:
                            remaining = (interval - i) // 60
                            if remaining > 0:
                                state.log(f"Auto-change: {remaining} minute(s) remaining")
                    
                    if (self.running and not state.shutting_down and 
                        state.auto_change_enabled and len(state.videos) > 1):
                        self.change_signal.emit()
                else:
                    time.sleep(1)
                    
            except Exception as e:
                state.log(f"Auto-change thread error: {e}", "ERROR")
                time.sleep(5)
        
        state.log("Auto-change thread stopped")
                
    def stop(self):
        state.log("Stopping auto-change thread")
        self.running = False

# ==================== CLEANUP HANDLER ====================
def cleanup_handler():
    """Enhanced cleanup with specific exception handling"""
    state.shutting_down = True
    state.log("Application closing, performing graceful cleanup...")
    
    if hasattr(state, 'process_monitor') and state.process_monitor:
        try:
            state.process_monitor.stop()
            state.process_monitor.wait(2000)
        except Exception as e:
            state.log(f"Error stopping process monitor: {e}", "ERROR")
    
    if state.auto_change_thread:
        try:
            state.auto_change_thread.stop()
            state.auto_change_thread.wait(2000)
        except Exception as e:
            state.log(f"Error stopping auto-change thread: {e}", "ERROR")
    
    stop_wallpapers()
    
    try:
        ProcessManager.cleanup_orphaned_mpv()
    except Exception as e:
        state.log(f"Error in final orphan cleanup: {e}", "ERROR")
    
    state.log("Cleanup completed")

def signal_handler(signum, frame):
    """Handle termination signals"""
    state.log(f"Received signal {signum}, shutting down...")
    cleanup_handler()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
atexit.register(cleanup_handler)

# ==================== MPV MANAGEMENT ====================
def find_mpv():
    """Find mpv executable in common locations with caching"""
    if state.mpv_path:
        return state.mpv_path
        
    possible_paths = [
        "mpv",
        "mpv.exe",
        os.path.join(os.path.dirname(sys.executable), "mpv.exe"),
        os.path.join(os.environ.get('PROGRAMFILES', ''), "mpv", "mpv.exe"),
        os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), "mpv", "mpv.exe"),
        os.path.join(os.path.expanduser("~"), "scoop", "apps", "mpv", "current", "mpv.exe"),
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "mpv", "mpv.exe"),
    ]
    
    for path in possible_paths:
        try:
            result = subprocess.run(
                [path, "--version"], 
                capture_output=True, 
                text=True, 
                timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            if result.returncode == 0:
                state.mpv_path = path
                state.log(f"Found mpv at: {path}")
                return path
        except (subprocess.SubprocessError, FileNotFoundError, PermissionError):
            continue
        except Exception as e:
            state.log(f"Unexpected error checking mpv at {path}: {e}", "DEBUG")
            continue
    
    state.log("MPV not found in PATH or common locations", "ERROR")
    return None

def verify_mpv():
    """Verify mpv is available and show error if not"""
    mpv_path = find_mpv()
    if not mpv_path:
        QMessageBox.critical(
            None, 
            "MPV Not Found",
            "MPV player is required but not found.\n\n"
            "Please install mpv:\n"
            "1. Download from: https://mpv.io/installation/\n"
            "2. Add to PATH or install in default location\n"
            "3. Restart the application"
        )
        return False
    return True

# ==================== WINDOW MANAGEMENT ====================
def find_window(pid, timeout=15):
    """Find window by PID with improved error handling"""
    start = time.time()
    while time.time() - start < timeout and not state.shutting_down:
        hwnds = []
        def callback(hwnd, _):
            try:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid:
                    hwnds.append(hwnd)
            except (win32process.error, Exception):
                pass
                
        try:
            win32gui.EnumWindows(callback, None)
            if hwnds:
                return hwnds[0]
        except win32gui.error as e:
            state.log(f"Error enumerating windows: {e}", "DEBUG")
            
        time.sleep(0.1)
    return None

def set_window_opacity(hwnd, opacity):
    """Set window opacity with validation"""
    try:
        if win32gui.IsWindow(hwnd):
            result = SetLayeredWindowAttributes(hwnd, 0, int(opacity), LWA_ALPHA)
            return result != 0
    except (ctypes.ArgumentError, OSError, Exception):
        pass
    return False

def prepare_window_styles(hwnd):
    """Prepare window styles for wallpaper"""
    try:
        if not win32gui.IsWindow(hwnd):
            return False
        
        try:
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        except win32gui.error as e:
            state.log(f"Error getting window styles: {e}", "ERROR")
            return False
        
        style = win32con.WS_POPUP | win32con.WS_CLIPCHILDREN | win32con.WS_CLIPSIBLINGS
        try:
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
        except win32gui.error as e:
            state.log(f"Error setting window style: {e}", "ERROR")
            return False
        
        ex_style |= (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        try:
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
        except win32gui.error as e:
            state.log(f"Error setting extended style: {e}", "ERROR")
            return False
        
        return True
        
    except Exception as e:
        state.log(f"Unexpected error in prepare_window_styles: {e}", "ERROR")
        return False

def keep_at_bottom(hwnd):
    """Keep window at bottom with health checks"""
    check_interval = 2
    while not state.shutting_down:
        try:
            if not win32gui.IsWindow(hwnd):
                break
            
            try:
                current_z = win32gui.GetWindow(hwnd, win32con.GW_HWNDPREV)
                if current_z != 0:
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                        win32con.SWP_NOACTIVATE | 0x0200
                    )
            except win32gui.error as e:
                if "invalid window handle" in str(e).lower():
                    break
                
        except Exception:
            break
            
        time.sleep(check_interval)

# ==================== MONITOR MANAGEMENT ====================
def detect_monitors():
    """Detect monitors with fallback"""
    try:
        monitors = []
        for m in get_monitors():
            monitors.append({
                'x': m.x, 'y': m.y, 
                'width': m.width, 'height': m.height, 
                'is_primary': m.is_primary
            })
        
        if not monitors:
            monitors.append({'x': 0, 'y': 0, 'width': 1920, 'height': 1080, 'is_primary': True})
            state.log("No monitors detected, using fallback resolution", "WARNING")
        
        monitors.sort(key=lambda x: x['x'])
        state.monitors = monitors
        state.log(f"Detected {len(monitors)} monitor(s)")
        return True
        
    except Exception as e:
        state.log(f"Monitor detection error: {e}", "ERROR")
        state.monitors = [{'x': 0, 'y': 0, 'width': 1920, 'height': 1080, 'is_primary': True}]
        return False

def get_monitor_geometry(monitor_idx=None):
    """Get geometry for specific monitor or combined span"""
    if not state.monitors:
        return (0, 0, 1920, 1080)
        
    if monitor_idx is not None and 0 <= monitor_idx < len(state.monitors):
        m = state.monitors[monitor_idx]
        return (m['x'], m['y'], m['width'], m['height'])
    
    try:
        min_x = min(m['x'] for m in state.monitors)
        min_y = min(m['y'] for m in state.monitors)
        max_x = max(m['x'] + m['width'] for m in state.monitors)
        max_y = max(m['y'] + m['height'] for m in state.monitors)
        return (min_x, min_y, max_x - min_x, max_y - min_y)
    except (KeyError, ValueError) as e:
        state.log(f"Error calculating monitor geometry: {e}", "ERROR")
        return (0, 0, 1920, 1080)

# ==================== WALLPAPER CONTROL ====================
def launch_mpv(video, x, y, width, height):
    """Launch mpv with retry logic and process tracking"""
    if not state.mpv_path and not find_mpv():
        return None
        
    geometry = f"{width}x{height}+{x}+{y}"
    args = [
        state.mpv_path, 
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
        "--input-cursor=no", 
        "--cursor-autohide=no", 
        "--geometry=" + geometry, 
        video
    ]
    
    for attempt in range(MAX_RETRIES):
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            p = subprocess.Popen(
                args, 
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            with state.lock:
                state.process_info[p.pid] = {
                    'start_time': time.time(),
                    'video': video,
                    'geometry': geometry
                }
            
            return p
            
        except (subprocess.SubprocessError, OSError) as e:
            state.log(f"Failed to launch mpv (attempt {attempt + 1}): {e}", "WARNING")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                state.log(f"Failed to launch mpv after {MAX_RETRIES} attempts", "ERROR")
                return None
        except Exception as e:
            state.log(f"Unexpected error launching mpv: {e}", "ERROR")
            return None

def setup_wallpaper_window(p, monitor_idx):
    """Setup wallpaper window with comprehensive error handling"""
    try:
        hwnd = find_window(p.pid, timeout=10)
        if not hwnd:
            state.log(f"Could not find window for process {p.pid}", "WARNING")
            return None, None
            
        x, y, w, h = get_monitor_geometry(monitor_idx)
        
        try:
            win32gui.ShowWindow(hwnd, SW_HIDE)
        except win32gui.error as e:
            state.log(f"Error hiding window: {e}", "ERROR")
            return None, None
        
        if not prepare_window_styles(hwnd):
            state.log("Failed to prepare window styles", "ERROR")
            return None, None
            
        time.sleep(0.4)
        
        if not win32gui.IsWindow(hwnd):
            state.log("Window destroyed during setup", "WARNING")
            return None, None
            
        try:
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_BOTTOM, x, y, w, h,
                win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED |
                0x0200 | win32con.SWP_SHOWWINDOW
            )
        except win32gui.error as e:
            state.log(f"Error positioning window: {e}", "ERROR")
            return None, None
        
        with state.lock:
            if p.pid in state.process_info:
                state.process_info[p.pid]['hwnd'] = hwnd
                state.process_info[p.pid]['monitor_idx'] = monitor_idx
        
        bottom_thread = threading.Thread(target=keep_at_bottom, args=(hwnd,), daemon=True)
        bottom_thread.start()
        
        return hwnd, p
        
    except Exception as e:
        state.log(f"Unexpected error in setup_wallpaper_window: {e}", "ERROR")
        return None, None

def stop_wallpapers():
    """Stop all wallpaper processes gracefully"""
    state.log("Stopping all wallpapers...")
    
    with state.lock:
        all_processes = []
        for procs in state.processes.values():
            all_processes.extend(procs)
        
        state.processes = {}
        pids_to_stop = list(state.process_info.keys())
        state.process_info.clear()
    
    for p in all_processes:
        try:
            if p and p.pid:
                ProcessManager.graceful_terminate(p.pid)
        except Exception as e:
            state.log(f"Error stopping process {p.pid if p else 'unknown'}: {e}", "ERROR")
    
    for pid in pids_to_stop:
        try:
            ProcessManager.graceful_terminate(pid)
        except Exception as e:
            state.log(f"Error stopping process {pid}: {e}", "ERROR")
    
    try:
        ProcessManager.cleanup_orphaned_mpv()
    except Exception as e:
        state.log(f"Error in orphan cleanup: {e}", "ERROR")
    
    state.log("All wallpapers stopped")

def instant_switch_monitor(monitor_idx, new_video_idx):
    """Instant switch for a monitor"""
    if not state.videos or new_video_idx >= len(state.videos):
        return False
        
    new_video = state.videos[new_video_idx]
    
    with state.lock:
        old_procs = state.processes.get(monitor_idx, [])
        if monitor_idx in state.processes:
            del state.processes[monitor_idx]
    
    for p in old_procs:
        try:
            if p and p.pid:
                ProcessManager.graceful_terminate(p.pid)
        except Exception as e:
            state.log(f"Error terminating old process: {e}", "ERROR")
    
    try:
        x, y, w, h = get_monitor_geometry(monitor_idx)
        p = launch_mpv(new_video, x, y, w, h)
        if not p:
            return False
            
        hwnd, p = setup_wallpaper_window(p, monitor_idx)
        if hwnd:
            with state.lock:
                if monitor_idx not in state.processes:
                    state.processes[monitor_idx] = []
                state.processes[monitor_idx].append(p)
            return True
        else:
            if p and p.pid:
                ProcessManager.graceful_terminate(p.pid)
            return False
        
    except Exception as e:
        state.log(f"Instant switch error: {e}", "ERROR")
        return False

def crossfade_monitor(monitor_idx, new_video_idx):
    """Crossfade transition for a monitor"""
    with state.lock:
        if state.transition_active:
            return False
        state.transition_active = True
    
    try:
        if not state.videos or new_video_idx >= len(state.videos):
            return False
            
        new_video = state.videos[new_video_idx]
        state.log(f"Monitor {monitor_idx}: Crossfading to {os.path.basename(new_video)}")
        
        x, y, w, h = get_monitor_geometry(monitor_idx)
        
        with state.lock:
            old_procs = state.processes.get(monitor_idx, []).copy()
        
        new_p = launch_mpv(new_video, x, y, w, h)
        if not new_p:
            return False
            
        new_hwnd = find_window(new_p.pid, timeout=10)
        if not new_hwnd:
            ProcessManager.graceful_terminate(new_p.pid)
            return False
            
        try:
            win32gui.ShowWindow(new_hwnd, SW_HIDE)
        except win32gui.error as e:
            state.log(f"Error hiding new window: {e}", "ERROR")
            ProcessManager.graceful_terminate(new_p.pid)
            return False
            
        prepare_window_styles(new_hwnd)
        set_window_opacity(new_hwnd, 0)
        
        try:
            win32gui.SetWindowPos(
                new_hwnd, win32con.HWND_BOTTOM, x, y, w, h,
                win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED | 
                0x0200 | win32con.SWP_SHOWWINDOW
            )
        except win32gui.error as e:
            state.log(f"Error positioning new window: {e}", "ERROR")
            ProcessManager.graceful_terminate(new_p.pid)
            return False
        
        with state.lock:
            if monitor_idx not in state.processes:
                state.processes[monitor_idx] = []
            state.processes[monitor_idx].append(new_p)
        
        threading.Thread(target=keep_at_bottom, args=(new_hwnd,), daemon=True).start()
        
        steps = int(state.transition_duration * 60)
        step_duration = state.transition_duration / steps if steps > 0 else 0.01
        
        for i in range(steps + 1):
            if state.shutting_down:
                break
                
            progress = i / steps
            eased = progress * progress * (3 - 2 * progress)
            new_opacity = int(255 * eased)
            old_opacity = int(255 * (1 - eased))
            
            set_window_opacity(new_hwnd, new_opacity)
            
            for old_p in old_procs:
                try:
                    if old_p and old_p.pid:
                        old_hwnd = find_window(old_p.pid, timeout=0.1)
                        if old_hwnd:
                            set_window_opacity(old_hwnd, old_opacity)
                except Exception:
                    pass
                    
            time.sleep(step_duration)
        
        for old_p in old_procs:
            try:
                if old_p and old_p.pid:
                    ProcessManager.graceful_terminate(old_p.pid)
            except Exception as e:
                state.log(f"Error terminating old process: {e}", "ERROR")
        
        with state.lock:
            if monitor_idx in state.processes:
                state.processes[monitor_idx] = [
                    p for p in state.processes[monitor_idx] 
                    if p and p.poll() is None
                ]
        
        return True
        
    except Exception as e:
        state.log(f"Transition error: {e}", "ERROR")
        return False
        
    finally:
        with state.lock:
            state.transition_active = False

def start_wallpaper(video=None):
    """Start wallpaper on all monitors"""
    if not verify_mpv():
        return
        
    if not state.videos:
        state.log("No videos in library", "WARNING")
        return
    
    stop_wallpapers()
    time.sleep(0.2)
    
    if video is None:
        video = state.videos[state.current_index]
    
    if state.current_mode == "span":
        x, y, w, h = get_monitor_geometry()
        p = launch_mpv(video, x, y, w, h)
        if p:
            hwnd, p = setup_wallpaper_window(p, 0)
            if hwnd:
                with state.lock:
                    state.processes = {0: [p]}
                state.log(f"Started wallpaper: {os.path.basename(video)}")
    else:
        for i in range(len(state.monitors)):
            if state.current_mode == "individual":
                video_idx = state.monitor_assignments.get(i, i) % len(state.videos)
            else:
                video_idx = state.current_index
                
            threading.Thread(
                target=instant_switch_monitor, 
                args=(i, video_idx), 
                daemon=True
            ).start()
            time.sleep(0.2)

def next_wallpaper():
    """Switch to next wallpaper"""
    if not state.videos:
        return
        
    with state.lock:
        state.current_index = (state.current_index + 1) % len(state.videos)
        
        if state.current_mode == "individual":
            for i in range(len(state.monitors)):
                new_idx = (state.monitor_assignments.get(i, 0) + 1) % len(state.videos)
                state.monitor_assignments[i] = new_idx
                threading.Thread(
                    target=crossfade_monitor, 
                    args=(i, new_idx), 
                    daemon=True
                ).start()
        else:
            QTimer.singleShot(0, lambda: start_wallpaper())

def prev_wallpaper():
    """Switch to previous wallpaper"""
    if not state.videos:
        return
        
    with state.lock:
        state.current_index = (state.current_index - 1) % len(state.videos)
        
        if state.current_mode == "individual":
            for i in range(len(state.monitors)):
                new_idx = (state.monitor_assignments.get(i, 0) - 1) % len(state.videos)
                state.monitor_assignments[i] = new_idx
                threading.Thread(
                    target=crossfade_monitor, 
                    args=(i, new_idx), 
                    daemon=True
                ).start()
        else:
            QTimer.singleShot(0, lambda: start_wallpaper())

def random_wallpaper():
    """Set random wallpaper (thread-safe)"""
    if not state.videos:
        state.log("No videos in library", "WARNING")
        return
    
    if len(state.videos) == 1:
        state.log("Only one video in library, cannot randomize", "WARNING")
        return
    
    with state.lock:
        new_index = random.randint(0, len(state.videos) - 1)
        while len(state.videos) > 1 and new_index == state.current_index:
            new_index = random.randint(0, len(state.videos) - 1)
            
        state.current_index = new_index
        video_name = os.path.basename(state.videos[new_index])
        state.log(f"Setting random wallpaper: {video_name}")
        
        if state.current_mode == "individual":
            for i in range(len(state.monitors)):
                state.monitor_assignments[i] = new_index
                threading.Thread(
                    target=crossfade_monitor, 
                    args=(i, new_index), 
                    daemon=True
                ).start()
        else:
            QTimer.singleShot(0, lambda: start_wallpaper(state.videos[new_index]))

# ==================== MOEWALLS SCRAPER WITH FORMAT SELECTION ====================
def extract_video_urls(page_url):
    """Extract all video URLs from the page (both MP4 and WebM)"""
    if not page_url:
        return [], []
    
    state.log(f"Extracting video URLs from: {page_url}")
    
    mp4_urls = []
    webm_urls = []
    
    for attempt in range(MAX_RETRIES):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            r = requests.get(page_url, headers=headers, timeout=15)
            r.raise_for_status()
            
            soup = BeautifulSoup(r.text, "html.parser")
            
            # Method 1: Look for video source in video tags
            for video in soup.find_all("video"):
                for source in video.find_all("source", src=True):
                    src = source.get('src', '')
                    if src:
                        if src.startswith('http'):
                            full_url = src
                        else:
                            full_url = urljoin(page_url, src)
                        
                        if '.mp4' in src.lower():
                            mp4_urls.append(full_url)
                        elif '.webm' in src.lower():
                            webm_urls.append(full_url)
            
            # Method 2: Look for direct video links in the page
            for a in soup.find_all("a", href=True):
                href = a.get('href', '')
                if href:
                    if href.startswith('http'):
                        full_url = href
                    else:
                        full_url = urljoin(page_url, href)
                    
                    if '.mp4' in href.lower():
                        mp4_urls.append(full_url)
                    elif '.webm' in href.lower():
                        webm_urls.append(full_url)
            
            # Method 3: Look for resolution page links and follow them
            resolution_links = []
            for a in soup.find_all("a", href=True):
                href = a.get('href', '')
                text = a.text.lower()
                if 'resolution' in href.lower() or any(res in text for res in ['4k', '1080p', '2160p', '1440p']):
                    if href.startswith('http'):
                        resolution_links.append(href)
                    else:
                        resolution_links.append(urljoin(page_url, href))
            
            # Check resolution pages for videos
            if resolution_links:
                state.log(f"Found {len(resolution_links)} resolution pages, checking for videos...")
                for res_link in resolution_links[:3]:
                    res_mp4, res_webm = extract_video_from_resolution_page(res_link)
                    mp4_urls.extend(res_mp4)
                    webm_urls.extend(res_webm)
            
            # Remove duplicates while preserving order
            mp4_urls = list(dict.fromkeys(mp4_urls))
            webm_urls = list(dict.fromkeys(webm_urls))
            
            state.log(f"Found {len(mp4_urls)} MP4 and {len(webm_urls)} WebM links")
            return mp4_urls, webm_urls
            
        except Exception as e:
            state.log(f"Error extracting video URLs (attempt {attempt + 1}): {e}", "WARNING")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                return [], []

def extract_video_from_resolution_page(resolution_url):
    """Extract video URLs from a resolution page"""
    mp4_urls = []
    webm_urls = []
    
    try:
        state.log(f"Checking resolution page: {resolution_url}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(resolution_url, headers=headers, timeout=10)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Look for video sources
        for video in soup.find_all("video"):
            for source in video.find_all("source", src=True):
                src = source.get('src', '')
                if src:
                    if src.startswith('http'):
                        full_url = src
                    else:
                        full_url = urljoin(resolution_url, src)
                    
                    if '.mp4' in src.lower():
                        mp4_urls.append(full_url)
                    elif '.webm' in src.lower():
                        webm_urls.append(full_url)
        
        # Look for direct download links
        for a in soup.find_all("a", href=True):
            href = a.get('href', '')
            if href:
                if href.startswith('http'):
                    full_url = href
                else:
                    full_url = urljoin(resolution_url, href)
                
                if '.mp4' in href.lower():
                    mp4_urls.append(full_url)
                elif '.webm' in href.lower():
                    webm_urls.append(full_url)
        
        return mp4_urls, webm_urls
        
    except Exception as e:
        state.log(f"Error extracting from resolution page: {e}", "DEBUG")
        return [], []

def download_wallpaper(wallpaper_data, preferred_format='mp4', progress_callback=None):
    """Download wallpaper with format selection"""
    page_url = wallpaper_data.get("page")
    if not page_url:
        raise ValueError("No page URL provided")
    
    state.log(f"Processing wallpaper: {wallpaper_data.get('title', 'Unknown')} (preferred format: {preferred_format})")
    
    # Get all available video URLs
    mp4_urls, webm_urls = extract_video_urls(page_url)
    
    # Select URL based on preference
    video_url = None
    actual_format = None
    
    if preferred_format.lower() == 'mp4' and mp4_urls:
        video_url = mp4_urls[0]
        actual_format = 'mp4'
        state.log(f"Found {len(mp4_urls)} MP4 links, using first one")
    elif preferred_format.lower() == 'webm' and webm_urls:
        video_url = webm_urls[0]
        actual_format = 'webm'
        state.log(f"Found {len(webm_urls)} WebM links, using first one")
    elif mp4_urls:
        video_url = mp4_urls[0]
        actual_format = 'mp4'
        state.log(f"Preferred format not available, falling back to MP4")
    elif webm_urls:
        video_url = webm_urls[0]
        actual_format = 'webm'
        state.log(f"Preferred format not available, falling back to WebM")
    
    if not video_url:
        # Try resolution pages directly as last resort
        if 'resolution' in page_url.lower():
            res_mp4, res_webm = extract_video_from_resolution_page(page_url)
            if preferred_format.lower() == 'mp4' and res_mp4:
                video_url = res_mp4[0]
                actual_format = 'mp4'
            elif preferred_format.lower() == 'webm' and res_webm:
                video_url = res_webm[0]
                actual_format = 'webm'
            elif res_mp4:
                video_url = res_mp4[0]
                actual_format = 'mp4'
            elif res_webm:
                video_url = res_webm[0]
                actual_format = 'webm'
    
    if not video_url:
        raise Exception("Could not find any video URL on the page")
    
    state.log(f"Downloading {actual_format.upper()} video from: {video_url}")
    
    # Generate filename
    filename = video_url.split("/")[-1].split("?")[0]
    if not filename or '.' not in filename:
        safe_title = "".join(c for c in wallpaper_data.get('title', 'wallpaper') if c.isalnum() or c in ' ._-')[:50]
        filename = f"{safe_title}.{actual_format}".replace(' ', '_')
    elif not filename.lower().endswith((f'.{actual_format}', '.mp4', '.webm')):
        base = os.path.splitext(filename)[0]
        filename = f"{base}.{actual_format}"
    
    filepath = os.path.join(state.save_dir, filename)
    
    # Handle duplicates
    if os.path.exists(filepath):
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(filepath):
            new_filename = f"{base}_{counter}{ext}"
            filepath = os.path.join(state.save_dir, new_filename)
            counter += 1
    
    temp_path = filepath + ".tmp"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": f"video/{actual_format},video/*;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://moewalls.com/",
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(video_url, headers=headers, stream=True, timeout=30, allow_redirects=True)
            r.raise_for_status()
            
            content_type = r.headers.get('content-type', '')
            if 'text/html' in content_type:
                if attempt < MAX_RETRIES - 1:
                    state.log(f"Got HTML instead of video, retrying... (attempt {attempt + 1})", "WARNING")
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    raise Exception("Server returned HTML instead of video")
            
            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            last_progress = 0
            
            with open(temp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            progress = int(downloaded * 100 / total)
                            if progress != last_progress:
                                progress_callback(progress)
                                last_progress = progress
            
            if os.path.getsize(temp_path) == 0:
                raise Exception("Downloaded file is empty")
            
            os.rename(temp_path, filepath)
            state.log(f"Download complete: {os.path.basename(filepath)}")
            return filepath
            
        except requests.Timeout:
            state.log(f"Download timeout (attempt {attempt + 1})", "WARNING")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except:
                    pass
            else:
                raise Exception("Download timed out after multiple attempts")
                
        except requests.RequestException as e:
            state.log(f"Download error (attempt {attempt + 1}): {e}", "WARNING")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except:
                    pass
            else:
                raise Exception(f"Download failed: {e}")
                
        except Exception as e:
            state.log(f"Unexpected error: {e}", "ERROR")
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass
            if attempt == MAX_RETRIES - 1:
                raise Exception(f"Download failed: {e}")

def search_wallpapers(keyword):
    """Search MoeWalls for wallpapers"""
    if not keyword or not keyword.strip():
        return []
        
    url = f"{BASE_URL}/?s={quote(keyword)}"
    
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.raise_for_status()
            
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            
            for article in soup.find_all("article"):
                try:
                    link = article.find("a", href=True)
                    img = article.find("img")
                    if link and img and link.get('href') and img.get('src'):
                        results.append({
                            "title": img.get("alt", "Wallpaper"),
                            "page": link["href"],
                            "thumbnail": img.get("src")
                        })
                except Exception:
                    continue
                    
            return results
            
        except requests.Timeout as e:
            state.log(f"Search timeout (attempt {attempt + 1}): {e}", "WARNING")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise Exception("Search timed out after multiple attempts")
        except requests.ConnectionError as e:
            state.log(f"Connection error (attempt {attempt + 1}): {e}", "WARNING")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise Exception("Connection failed after multiple attempts")
        except requests.RequestException as e:
            state.log(f"Request error (attempt {attempt + 1}): {e}", "WARNING")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise Exception(f"Search failed: {e}")

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

    def __init__(self, wallpaper_data, preferred_format='mp4'):
        super().__init__()
        self.wallpaper_data = wallpaper_data
        self.preferred_format = preferred_format

    def run(self):
        try:
            state.log(f"Processing wallpaper: {self.wallpaper_data.get('title', 'Unknown')} (format: {self.preferred_format})")
            filepath = download_wallpaper(self.wallpaper_data, self.preferred_format, lambda p: self.progress.emit(p))
            self.finished.emit(filepath)
            
        except Exception as e:
            error_msg = str(e)
            state.log(f"Download error: {error_msg}", "ERROR")
            self.error.emit(error_msg)

# ==================== GUI COMPONENTS ====================
class WallpaperCard(QFrame):
    clicked = pyqtSignal(dict)
    download_clicked = pyqtSignal(dict)
    set_clicked = pyqtSignal(str)
    delete_clicked = pyqtSignal(str)

    def __init__(self, video_path, is_local=True, online_data=None):
        super().__init__()
        self.video_path = video_path
        self.is_local = is_local
        self.online_data = online_data
        self.setup_ui()

    def setup_ui(self):
        try:
            self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            
            layout = QVBoxLayout(self)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)
            
            self.thumb_label = QLabel()
            self.thumb_label.setFixedSize(200, 120)
            self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.thumb_label.setStyleSheet("background-color: #2d2d2d; border-radius: 4px;")
            
            if self.is_local:
                self.thumb_label.setText("🎬")
                font = self.thumb_label.font()
                font.setPointSize(32)
                self.thumb_label.setFont(font)
                
                # Show file format for local files
                ext = os.path.splitext(self.video_path)[1].upper()
                self.setToolTip(f"Format: {ext}")
            else:
                self.thumb_label.setText("⬇")
                font = self.thumb_label.font()
                font.setPointSize(32)
                self.thumb_label.setFont(font)
                self.load_thumbnail()
                
            layout.addWidget(self.thumb_label, alignment=Qt.AlignmentFlag.AlignCenter)
            
            if self.is_local:
                title = os.path.basename(self.video_path)
            else:
                title = self.online_data.get("title", "Unknown") if self.online_data else "Unknown"
                
            display_title = title[:25] + "..." if len(title) > 25 else title
            self.title_label = QLabel(display_title)
            self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.title_label.setWordWrap(True)
            self.title_label.setToolTip(title)
            layout.addWidget(self.title_label)
            
            btn_layout = QHBoxLayout()
            
            if self.is_local:
                set_btn = QPushButton("Set")
                set_btn.clicked.connect(lambda: self.set_clicked.emit(self.video_path))
                set_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_layout.addWidget(set_btn)
                
                delete_btn = QPushButton("🗑️")
                delete_btn.setMaximumWidth(30)
                delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.video_path))
                delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                delete_btn.setToolTip("Delete from library")
                btn_layout.addWidget(delete_btn)
            else:
                dl_btn = QPushButton("Download")
                dl_btn.clicked.connect(lambda: self.download_clicked.emit(self.online_data))
                dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_layout.addWidget(dl_btn)
                
                manual_btn = QPushButton("🌐 Open")
                manual_btn.clicked.connect(lambda: webbrowser.open(self.online_data["page"]))
                manual_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                manual_btn.setMaximumWidth(60)
                btn_layout.addWidget(manual_btn)
            
            layout.addLayout(btn_layout)
            
            self.setFixedWidth(240)
            
        except Exception as e:
            state.log(f"Error setting up wallpaper card: {e}", "ERROR")

    def load_thumbnail(self):
        def fetch():
            try:
                if not self.online_data:
                    return
                    
                url = self.online_data.get("thumbnail")
                if not url:
                    return
                    
                r = requests.get(url, headers=HEADERS, timeout=5)
                r.raise_for_status()
                
                img = Image.open(BytesIO(r.content))
                img = img.resize((200, 120), Image.Resampling.LANCZOS)
                
                img_bytes = BytesIO()
                img.save(img_bytes, format='PNG')
                pixmap = QPixmap()
                pixmap.loadFromData(img_bytes.getvalue())
                
                self.thumb_label.setPixmap(pixmap)
                
            except requests.RequestException:
                pass
            except Exception:
                pass
                
        threading.Thread(target=fetch, daemon=True).start()

    def mousePressEvent(self, event):
        try:
            self.clicked.emit({
                "path": self.video_path, 
                "is_local": self.is_local, 
                "data": self.online_data
            })
        except Exception as e:
            state.log(f"Error in mouse press event: {e}", "ERROR")

class SettingsTab(QWidget):
    """Settings tab for configuring application behavior"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.load_settings()
        state.settings_tab = self
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        
        storage_box = QGroupBox("Video Storage Location")
        storage_layout = QVBoxLayout(storage_box)
        
        self.path_label = QLabel(f"Current: {SAVE_DIR}")
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet("padding: 5px; background-color: #2d2d2d; border-radius: 3px;")
        storage_layout.addWidget(self.path_label)
        
        change_btn = QPushButton("Change Location")
        change_btn.clicked.connect(self.change_location)
        change_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        storage_layout.addWidget(change_btn)
        
        info_label = QLabel(
            "Note: Changing location will:\n"
            "• Move configuration files to new location\n"
            "• Optionally copy existing videos\n"
            "• Require application restart"
        )
        info_label.setStyleSheet("color: #888; font-style: italic; padding: 5px;")
        storage_layout.addWidget(info_label)
        
        layout.addWidget(storage_box)
        
        paths_box = QGroupBox("Additional Library Folders")
        paths_layout = QVBoxLayout(paths_box)
        
        self.paths_list = QListWidget()
        self.paths_list.setMaximumHeight(150)
        paths_layout.addWidget(self.paths_list)
        
        path_buttons = QHBoxLayout()
        
        add_path_btn = QPushButton("Add Folder")
        add_path_btn.clicked.connect(self.add_library_path)
        add_path_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        path_buttons.addWidget(add_path_btn)
        
        remove_path_btn = QPushButton("Remove Selected")
        remove_path_btn.clicked.connect(self.remove_library_path)
        remove_path_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        path_buttons.addWidget(remove_path_btn)
        
        paths_layout.addLayout(path_buttons)
        
        self.subfolders_check = QCheckBox("Include videos from subfolders")
        self.subfolders_check.stateChanged.connect(self.toggle_subfolders)
        paths_layout.addWidget(self.subfolders_check)
        
        layout.addWidget(paths_box)
        
        stats_box = QGroupBox("Library Statistics")
        stats_layout = QVBoxLayout(stats_box)
        
        self.stats_label = QLabel("Loading statistics...")
        stats_layout.addWidget(self.stats_label)
        
        refresh_stats_btn = QPushButton("Refresh Statistics")
        refresh_stats_btn.clicked.connect(self.update_statistics)
        refresh_stats_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stats_layout.addWidget(refresh_stats_btn)
        
        layout.addWidget(stats_box)
        
        about_box = QGroupBox("About")
        about_layout = QVBoxLayout(about_box)
        
        about_text = QLabel(
            "Video Wallpaper Manager v2.3\n"
            "Configurable storage location\n"
            "Supports multiple library folders\n"
            "MP4/WebM format selection\n"
            "MPV player required"
        )
        about_layout.addWidget(about_text)
        
        layout.addWidget(about_box)
        layout.addStretch()
    
    def load_settings(self):
        """Load settings into UI"""
        settings = load_settings()
        
        self.paths_list.clear()
        for path in state.library_paths:
            self.paths_list.addItem(path)
        
        self.subfolders_check.setChecked(settings.get("check_subfolders", False))
        self.update_statistics()
    
    def update_statistics(self):
        """Update library statistics"""
        total_size = 0
        video_count = len(state.videos)
        mp4_count = 0
        webm_count = 0
        other_count = 0
        
        for video in state.videos:
            try:
                total_size += os.path.getsize(video)
                ext = os.path.splitext(video)[1].lower()
                if ext == '.mp4':
                    mp4_count += 1
                elif ext == '.webm':
                    webm_count += 1
                else:
                    other_count += 1
            except:
                pass
        
        if total_size > 1024**3:
            size_str = f"{total_size / (1024**3):.2f} GB"
        elif total_size > 1024**2:
            size_str = f"{total_size / (1024**2):.2f} MB"
        else:
            size_str = f"{total_size / 1024:.2f} KB"
        
        stats_text = (
            f"Total videos: {video_count}\n"
            f"  MP4: {mp4_count}\n"
            f"  WebM: {webm_count}\n"
            f"  Other: {other_count}\n"
            f"Total size: {size_str}\n"
            f"Main folder: {state.save_dir}\n"
            f"Additional folders: {len(state.library_paths)}"
        )
        
        self.stats_label.setText(stats_text)
    
    def change_location(self):
        """Change video storage location"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Videos Folder",
            os.path.expanduser("~\\Videos"),
            QFileDialog.Option.ShowDirsOnly
        )
        
        if folder:
            reply = QMessageBox.question(
                self,
                "Change Storage Location",
                f"Change storage location to:\n{folder}\n\n"
                "This will move configuration files and optionally copy videos.\n"
                "The application will need to restart.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                if change_video_storage_location(folder):
                    QMessageBox.information(
                        self,
                        "Restart Required",
                        "Storage location changed successfully.\nPlease restart the application."
                    )
                    self.path_label.setText(f"Current: {folder}")
                    self.update_statistics()
    
    def add_library_path(self):
        """Add additional library path"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder to Add to Library",
            os.path.expanduser("~"),
            QFileDialog.Option.ShowDirsOnly
        )
        
        if folder:
            if add_library_path(folder):
                self.paths_list.addItem(folder)
                self.update_statistics()
                if state.library_tab:
                    state.library_tab.refresh_library()
                QMessageBox.information(self, "Success", f"Added folder: {folder}")
            else:
                QMessageBox.warning(self, "Error", "Failed to add folder (already exists or invalid)")
    
    def remove_library_path(self):
        """Remove selected library path"""
        current_item = self.paths_list.currentItem()
        if current_item:
            path = current_item.text()
            reply = QMessageBox.question(
                self,
                "Remove Folder",
                f"Remove '{path}' from library?\n\nVideos will not be deleted, just removed from library.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                if remove_library_path(path):
                    self.paths_list.takeItem(self.paths_list.row(current_item))
                    self.update_statistics()
                    if state.library_tab:
                        state.library_tab.refresh_library()
    
    def toggle_subfolders(self, state_val):
        """Toggle subfolder scanning"""
        settings = load_settings()
        settings["check_subfolders"] = bool(state_val)
        save_settings(settings)
        
        load_videos()
        if state.library_tab:
            state.library_tab.refresh_library()
        self.update_statistics()

class MoeWallsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.search_results = []
        self.search_thread = None
        self.download_thread = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Search row
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search anime wallpapers...")
        self.search_input.returnPressed.connect(self.do_search)
        search_layout.addWidget(self.search_input)
        
        self.search_btn = QPushButton("🔍 Search")
        self.search_btn.clicked.connect(self.do_search)
        self.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        search_layout.addWidget(self.search_btn)
        
        layout.addLayout(search_layout)
        
        # Format selection row
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Preferred format:"))
        
        self.format_combo = QComboBox()
        self.format_combo.addItems(["MP4 (Smaller file)", "WebM (Better quality)"])
        self.format_combo.setCurrentIndex(0)
        self.format_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        format_layout.addWidget(self.format_combo)
        
        format_layout.addStretch()
        
        format_info = QLabel("MP4: Smaller size | WebM: Better quality")
        format_info.setStyleSheet("color: #888; font-size: 9pt;")
        format_layout.addWidget(format_info)
        
        layout.addLayout(format_layout)
        
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameStyle(QFrame.Shape.NoFrame)
        
        self.results_container = QWidget()
        self.results_layout = QGridLayout(self.results_container)
        self.results_layout.setSpacing(15)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        
        scroll.setWidget(self.results_container)
        layout.addWidget(scroll)
        
        self.status_label = QLabel("Enter a search term to find wallpapers")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #888; padding: 20px;")
        layout.addWidget(self.status_label)

    def get_preferred_format(self):
        """Get the preferred format from combo box"""
        return 'mp4' if self.format_combo.currentIndex() == 0 else 'webm'

    def do_search(self):
        keyword = self.search_input.text().strip()
        if not keyword:
            return
            
        self.status_label.setText(f"Searching for '{keyword}'...")
        self.search_btn.setEnabled(False)
        
        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.terminate()
            self.search_thread.wait()
        
        self.search_thread = SearchThread(keyword)
        self.search_thread.finished.connect(self.on_search_finished)
        self.search_thread.error.connect(self.on_search_error)
        self.search_thread.start()

    def on_search_finished(self, results):
        self.search_btn.setEnabled(True)
        self.search_results = results
        
        try:
            while self.results_layout.count():
                item = self.results_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
        except Exception as e:
            state.log(f"Error clearing results: {e}", "ERROR")
        
        if not results:
            self.status_label.setText("No results found.")
            return
            
        self.status_label.setText(f"Found {len(results)} wallpapers")
        
        for i, result in enumerate(results):
            try:
                card = WallpaperCard(video_path=result["page"], is_local=False, online_data=result)
                card.download_clicked.connect(self.start_download)
                self.results_layout.addWidget(card, i // 3, i % 3)
            except Exception as e:
                state.log(f"Error creating result card: {e}", "ERROR")

    def on_search_error(self, error):
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"Error: {error}")
        QMessageBox.warning(self, "Search Error", str(error))

    def start_download(self, data):
        self.progress.setVisible(True)
        self.progress.setValue(0)
        
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.terminate()
            self.download_thread.wait()
        
        preferred_format = self.get_preferred_format()
        self.download_thread = DownloadThread(data, preferred_format)
        self.download_thread.progress.connect(self.progress.setValue)
        self.download_thread.finished.connect(self.on_download_finished)
        self.download_thread.error.connect(self.on_download_error)
        self.download_thread.start()

    def on_download_finished(self, filepath):
        self.progress.setVisible(False)
        state.log(f"Downloaded: {os.path.basename(filepath)}")
        load_videos()
        
        if state.library_tab:
            state.library_tab.refresh_library()
        if state.settings_tab:
            state.settings_tab.update_statistics()
            
        QMessageBox.information(self, "Download Complete", 
                               f"Saved to: {os.path.basename(filepath)}")

    def on_download_error(self, error):
        self.progress.setVisible(False)
        preferred_format = self.get_preferred_format()
        
        reply = QMessageBox.question(
            self,
            "Download Failed",
            f"Failed to download {preferred_format.upper()} format: {error}\n\n"
            f"Do you want to try the other format or open the page in browser?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Try the other format
            other_format = 'webm' if preferred_format == 'mp4' else 'mp4'
            self.download_thread = DownloadThread(self.download_thread.wallpaper_data, other_format)
            self.download_thread.progress.connect(self.progress.setValue)
            self.download_thread.finished.connect(self.on_download_finished)
            self.download_thread.error.connect(self.on_download_error)
            self.download_thread.start()
            self.progress.setVisible(True)
            
        elif reply == QMessageBox.StandardButton.No:
            webbrowser.open(self.download_thread.wallpaper_data["page"])

class LibraryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.refresh_library()
        state.library_tab = self

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        controls = QHBoxLayout()
        
        self.info_label = QLabel("0 videos in library")
        self.info_label.setStyleSheet("font-weight: bold;")
        controls.addWidget(self.info_label)
        
        controls.addStretch()
        
        add_btn = QPushButton("+ Add Videos")
        add_btn.clicked.connect(self.add_videos)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        controls.addWidget(add_btn)
        
        open_btn = QPushButton("📁 Open Folder")
        open_btn.clicked.connect(self.open_folder)
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        controls.addWidget(open_btn)
        
        layout.addLayout(controls)
        
        self.paths_info_label = QLabel(f"Main library: {SAVE_DIR}")
        self.paths_info_label.setWordWrap(True)
        self.paths_info_label.setStyleSheet("color: #888; font-size: 10pt; padding: 5px;")
        layout.addWidget(self.paths_info_label)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameStyle(QFrame.Shape.NoFrame)
        
        self.library_container = QWidget()
        self.library_layout = QGridLayout(self.library_container)
        self.library_layout.setSpacing(15)
        self.library_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        
        scroll.setWidget(self.library_container)
        layout.addWidget(scroll)
        
        actions_box = QGroupBox("Quick Actions")
        actions_layout = QHBoxLayout(actions_box)
        
        prev_btn = QPushButton("⏮ Previous")
        prev_btn.clicked.connect(prev_wallpaper)
        prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        actions_layout.addWidget(prev_btn)
        
        next_btn = QPushButton("▶ Next Wallpaper")
        next_btn.clicked.connect(next_wallpaper)
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        actions_layout.addWidget(next_btn)
        
        random_btn = QPushButton("🔀 Random")
        random_btn.clicked.connect(random_wallpaper)
        random_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        actions_layout.addWidget(random_btn)
        
        stop_btn = QPushButton("⏹ Stop All")
        stop_btn.clicked.connect(stop_wallpapers)
        stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        actions_layout.addWidget(stop_btn)
        
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.refresh_library)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        actions_layout.addWidget(refresh_btn)
        
        layout.addWidget(actions_box)

    def refresh_library(self):
        """Refresh library display"""
        try:
            while self.library_layout.count():
                item = self.library_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
        except Exception as e:
            state.log(f"Error clearing library: {e}", "ERROR")
        
        load_videos()
        self.info_label.setText(f"{len(state.videos)} video(s) in library")
        
        paths_text = f"Main library: {SAVE_DIR}"
        if state.library_paths:
            paths_text += f"\nAdditional folders: {len(state.library_paths)}"
        self.paths_info_label.setText(paths_text)
        
        if not state.videos:
            placeholder = QLabel("No videos in library.\nClick 'Add Videos' to add files.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #888; padding: 50px;")
            self.library_layout.addWidget(placeholder, 0, 0)
            return
        
        for i, video_path in enumerate(state.videos):
            try:
                card = WallpaperCard(video_path, is_local=True)
                card.set_clicked.connect(self.set_wallpaper)
                card.delete_clicked.connect(self.delete_video)
                self.library_layout.addWidget(card, i // 3, i % 3)
            except Exception as e:
                state.log(f"Error creating library card: {e}", "ERROR")

    def set_wallpaper(self, video_path):
        """Set selected video as wallpaper"""
        try:
            idx = state.videos.index(video_path)
            state.current_index = idx
            
            if state.current_mode == "individual":
                for i in range(len(state.monitors)):
                    state.monitor_assignments[i] = idx
                    threading.Thread(target=crossfade_monitor, args=(i, idx), daemon=True).start()
            else:
                start_wallpaper(video_path)
                
        except ValueError as e:
            state.log(f"Video not found in library: {e}", "ERROR")
            QMessageBox.warning(self, "Error", "Video not found in library")
        except Exception as e:
            state.log(f"Error setting wallpaper: {e}", "ERROR")
            QMessageBox.warning(self, "Error", f"Failed to set wallpaper: {e}")

    def delete_video(self, video_path):
        """Delete video from library"""
        reply = QMessageBox.question(
            self, 
            "Confirm Delete",
            f"Are you sure you want to delete '{os.path.basename(video_path)}'?\n\nThis will permanently remove the file.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if os.path.exists(video_path):
                    os.remove(video_path)
                    state.log(f"Deleted video: {os.path.basename(video_path)}")
                    self.refresh_library()
                    
                    if state.settings_tab:
                        state.settings_tab.update_statistics()
            except Exception as e:
                state.log(f"Error deleting video: {e}", "ERROR")
                QMessageBox.warning(self, "Error", f"Failed to delete video: {e}")

    def add_videos(self):
        """Add videos to library"""
        files, _ = QFileDialog.getOpenFileNames(
            self, 
            "Select Videos", 
            "", 
            "Videos (*.mp4 *.webm *.mkv)"
        )
        
        if files:
            added = 0
            failed = 0
            
            for f in files:
                result = add_video_to_library(f)
                if result:
                    added += 1
                else:
                    failed += 1
            
            if added > 0:
                self.refresh_library()
                
                if state.settings_tab:
                    state.settings_tab.update_statistics()
                
                msg = f"Added {added} video(s)"
                if failed > 0:
                    msg += f" ({failed} failed)"
                QMessageBox.information(self, "Success", msg)

    def open_folder(self):
        """Open videos folder"""
        try:
            if not os.path.exists(SAVE_DIR):
                os.makedirs(SAVE_DIR)
            os.startfile(SAVE_DIR)
        except Exception as e:
            state.log(f"Error opening folder: {e}", "ERROR")
            QMessageBox.warning(self, "Error", f"Failed to open folder: {e}")

class DisplayTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)

        theme_box = QGroupBox("Interface Theme")
        theme_layout = QHBoxLayout(theme_box)
        
        theme_label = QLabel("Select Theme:")
        theme_layout.addWidget(theme_label)
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light", "Dracula", "Nord", "Midnight"])
        self.theme_combo.currentTextChanged.connect(self.on_theme_changed)
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addStretch()
        
        layout.addWidget(theme_box)

        mode_box = QGroupBox("Display Mode")
        mode_layout = QVBoxLayout(mode_box)
        
        self.mode_group = QButtonGroup(self)
        modes = [
            ("span", "Span", "One video stretched across all monitors"),
            ("duplicate", "Duplicate", "Same video on all monitors"),
            ("individual", "Individual", "Different video per monitor")
        ]
        
        for value, name, desc in modes:
            row = QHBoxLayout()
            rb = QRadioButton(name)
            rb.mode_value = value
            self.mode_group.addButton(rb)
            row.addWidget(rb)
            
            lbl = QLabel(desc)
            lbl.setStyleSheet("color: #888;")
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
        trans_layout = QVBoxLayout(trans_box)
        
        duration_row = QHBoxLayout()
        duration_row.addWidget(QLabel("Duration:"))
        
        self.duration_slider = QSlider(Qt.Orientation.Horizontal)
        self.duration_slider.setRange(5, 30)
        self.duration_slider.setValue(12)
        self.duration_slider.valueChanged.connect(self.on_duration_changed)
        duration_row.addWidget(self.duration_slider)
        
        self.duration_label = QLabel("1.2s")
        self.duration_label.setMinimumWidth(40)
        duration_row.addWidget(self.duration_label)
        
        trans_layout.addLayout(duration_row)
        
        test_btn = QPushButton("▶ Test Transition")
        test_btn.clicked.connect(self.test_transition)
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        trans_layout.addWidget(test_btn)
        
        layout.addWidget(trans_box)

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

        info_box = QGroupBox("Monitor Information")
        info_layout = QVBoxLayout(info_box)
        
        for i, m in enumerate(state.monitors):
            primary = " (Primary)" if m.get('is_primary', False) else ""
            info = f"Monitor {i+1}{primary}: {m['width']}x{m['height']} at ({m['x']}, {m['y']})"
            info_layout.addWidget(QLabel(info))
        
        layout.addWidget(info_box)
        layout.addStretch()

    def load_settings(self):
        """Load settings into UI"""
        try:
            idx = self.theme_combo.findText(state.theme)
            if idx >= 0:
                self.theme_combo.setCurrentIndex(idx)
            
            for btn in self.mode_group.buttons():
                if hasattr(btn, 'mode_value') and btn.mode_value == state.current_mode:
                    btn.setChecked(True)
                    break
            
            self.duration_slider.setValue(int(state.transition_duration * 10))
            
            self.auto_check.setChecked(state.auto_change_enabled)
            self.interval_spin.setValue(state.auto_change_interval // 60)
            
            self.refresh_monitor_assignment()
            
        except Exception as e:
            state.log(f"Error loading settings into UI: {e}", "ERROR")

    def refresh_monitor_assignment(self):
        """Refresh per-monitor assignment UI"""
        try:
            while self.monitor_layout.count():
                item = self.monitor_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
        except Exception as e:
            state.log(f"Error clearing monitor layout: {e}", "ERROR")
        
        if state.current_mode != "individual" or len(state.monitors) <= 1:
            self.monitor_box.setVisible(False)
            return
            
        self.monitor_box.setVisible(True)
        
        for i, m in enumerate(state.monitors):
            try:
                row = QHBoxLayout()
                
                info = f"Monitor {i+1} - {m['width']}x{m['height']}"
                row.addWidget(QLabel(info))
                
                combo = QComboBox()
                for v in state.videos:
                    combo.addItem(os.path.basename(v))
                
                current = state.monitor_assignments.get(i, i) % len(state.videos) if state.videos else 0
                combo.setCurrentIndex(current)
                
                combo.currentIndexChanged.connect(
                    lambda idx, mon=i: self.on_monitor_video_changed(mon, idx)
                )
                
                row.addWidget(combo)
                self.monitor_layout.addLayout(row)
                
            except Exception as e:
                state.log(f"Error creating monitor control for monitor {i}: {e}", "ERROR")

    def on_theme_changed(self, theme_name):
        """Handle theme change"""
        try:
            state.theme = theme_name
            save_config()
            if self.window():
                self.window().apply_theme(theme_name)
        except Exception as e:
            state.log(f"Error changing theme: {e}", "ERROR")

    def on_mode_changed(self, btn):
        """Handle display mode change"""
        try:
            if hasattr(btn, 'mode_value'):
                state.current_mode = btn.mode_value
                save_config()
                self.refresh_monitor_assignment()
                start_wallpaper()
        except Exception as e:
            state.log(f"Error changing mode: {e}", "ERROR")

    def on_duration_changed(self, value):
        """Handle transition duration change"""
        try:
            seconds = value / 10.0
            state.transition_duration = seconds
            self.duration_label.setText(f"{seconds:.1f}s")
            save_config()
        except Exception as e:
            state.log(f"Error changing duration: {e}", "ERROR")

    def on_auto_changed(self, state_val):
        """Handle auto-change toggle"""
        try:
            enabled = bool(state_val)
            state.auto_change_enabled = enabled
            save_config()
            state.log(f"Auto-change {'enabled' if enabled else 'disabled'}")
        except Exception as e:
            state.log(f"Error toggling auto-change: {e}", "ERROR")

    def on_interval_changed(self, value):
        """Handle interval change"""
        try:
            value = max(1, min(120, value))
            state.auto_change_interval = value * 60
            save_config()
            state.log(f"Auto-change interval set to {value} minutes")
        except Exception as e:
            state.log(f"Error changing interval: {e}", "ERROR")

    def on_monitor_video_changed(self, monitor_idx, video_idx):
        """Handle per-monitor video selection"""
        try:
            if 0 <= video_idx < len(state.videos):
                state.monitor_assignments[monitor_idx] = video_idx
                save_config()
                threading.Thread(target=crossfade_monitor, args=(monitor_idx, video_idx), daemon=True).start()
        except Exception as e:
            state.log(f"Error changing monitor video: {e}", "ERROR")

    def test_transition(self):
        """Test transition effect"""
        try:
            if len(state.videos) < 2:
                QMessageBox.warning(
                    self, 
                    "Need More Videos", 
                    "Add at least 2 videos to test transitions"
                )
                return
                
            new_idx = (state.current_index + 1) % len(state.videos)
            threading.Thread(target=crossfade_monitor, args=(0, new_idx), daemon=True).start()
                
        except Exception as e:
            state.log(f"Error testing transition: {e}", "ERROR")

# ==================== MAIN WINDOW ====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Wallpaper Manager")
        self.resize(900, 750)
        
        self.setup_icon()
        
        load_config()
        detect_monitors()
        load_videos()
        
        state.process_monitor = ProcessMonitorThread()
        state.process_monitor.start()
        
        state.auto_change_thread = AutoChangeThread()
        state.auto_change_thread.start()
        
        self.tabs = QTabWidget()
        self.tabs.addTab(LibraryTab(self), "📁 Library")
        self.tabs.addTab(MoeWallsTab(self), "🌐 MoeWalls")
        self.tabs.addTab(DisplayTab(self), "🖥 Display")
        self.tabs.addTab(SettingsTab(self), "⚙️ Settings")
        self.setCentralWidget(self.tabs)

        self.setup_tray()
        QTimer.singleShot(1000, self.check_mpv)

    def setup_icon(self):
        """Setup window icon"""
        try:
            icon = QIcon()
            
            icon_paths = [
                os.path.join(os.path.dirname(sys.executable), 'icon.ico'),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.ico'),
                os.path.join(os.getcwd(), 'icon.ico'),
            ]
            
            for icon_path in icon_paths:
                if os.path.exists(icon_path):
                    icon = QIcon(icon_path)
                    break
            
            if icon.isNull():
                pixmap = QPixmap(64, 64)
                pixmap.fill(QColor('#00d4aa'))
                icon = QIcon(pixmap)
            
            self.setWindowIcon(icon)
            
        except Exception as e:
            state.log(f"Error setting up icon: {e}", "ERROR")

    def setup_tray(self):
        """Setup system tray icon and menu"""
        try:
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
            
            stop_action = QAction("Stop Wallpapers", self)
            stop_action.triggered.connect(stop_wallpapers)
            tray_menu.addAction(stop_action)
            
            tray_menu.addSeparator()
            
            show_action = QAction("Show Window", self)
            show_action.triggered.connect(self.show)
            show_action.triggered.connect(self.activateWindow)
            tray_menu.addAction(show_action)
            
            hide_action = QAction("Hide to Tray", self)
            hide_action.triggered.connect(self.hide)
            tray_menu.addAction(hide_action)
            
            tray_menu.addSeparator()
            
            quit_action = QAction("Quit", self)
            quit_action.triggered.connect(self.quit_application)
            tray_menu.addAction(quit_action)
            
            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.show()
            
        except Exception as e:
            state.log(f"Error setting up tray: {e}", "ERROR")

    def check_mpv(self):
        """Check if mpv is available"""
        try:
            if not find_mpv():
                QMessageBox.warning(
                    self,
                    "MPV Not Found",
                    "MPV player is not installed or not in PATH.\n\n"
                    "Please install mpv to use this application.\n"
                    "Download from: https://mpv.io/installation/"
                )
        except Exception as e:
            state.log(f"Error checking mpv: {e}", "ERROR")

    def quit_application(self):
        """Clean quit application"""
        try:
            state.log("Quitting application...")
            
            if state.auto_change_thread:
                state.auto_change_thread.stop()
                state.auto_change_thread.wait(2000)
            
            cleanup_handler()
            
            QApplication.quit()
            
        except Exception as e:
            state.log(f"Error during quit: {e}", "ERROR")
            QApplication.quit()

    def closeEvent(self, event):
        """Override close event to hide to tray"""
        try:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "Video Wallpaper Manager",
                "Application minimized to system tray",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        except Exception as e:
            state.log(f"Error in close event: {e}", "ERROR")

    def apply_theme(self, theme_name):
        """Apply theme"""
        try:
            if theme_name == "Dark":
                self.setStyleSheet("""
                    QMainWindow { background-color: #1e1e1e; color: #ffffff; }
                    QGroupBox { color: #00d4aa; border: 1px solid #3d3d3d; }
                    QPushButton { background-color: #2d2d2d; color: #ffffff; border: 1px solid #3d3d3d; padding: 8px; border-radius: 4px; }
                    QPushButton:hover { background-color: #3d3d3d; }
                """)
            elif theme_name == "Light":
                self.setStyleSheet("""
                    QMainWindow { background-color: #f0f0f0; color: #000000; }
                    QGroupBox { color: #0078d4; border: 1px solid #d0d0d0; }
                    QPushButton { background-color: #ffffff; color: #000000; border: 1px solid #d0d0d0; padding: 8px; border-radius: 4px; }
                    QPushButton:hover { background-color: #e0e0e0; }
                """)
            elif theme_name == "Dracula":
                self.setStyleSheet("""
                    QMainWindow { background-color: #282a36; color: #f8f8f2; }
                    QGroupBox { color: #bd93f9; border: 1px solid #6272a4; }
                    QPushButton { background-color: #44475a; color: #f8f8f2; border: 1px solid #6272a4; padding: 8px; border-radius: 4px; }
                    QPushButton:hover { background-color: #6272a4; }
                """)
            elif theme_name == "Nord":
                self.setStyleSheet("""
                    QMainWindow { background-color: #2e3440; color: #eceff4; }
                    QGroupBox { color: #88c0d0; border: 1px solid #4c566a; }
                    QPushButton { background-color: #3b4252; color: #eceff4; border: 1px solid #4c566a; padding: 8px; border-radius: 4px; }
                    QPushButton:hover { background-color: #434c5e; }
                """)
            elif theme_name == "Midnight":
                self.setStyleSheet("""
                    QMainWindow { background-color: #0a0a0a; color: #e0e0e0; }
                    QGroupBox { color: #bb86fc; border: 1px solid #2e2e2e; }
                    QPushButton { background-color: #1e1e1e; color: #e0e0e0; border: 1px solid #2e2e2e; padding: 8px; border-radius: 4px; }
                    QPushButton:hover { background-color: #2e2e2e; }
                """)
        except Exception as e:
            state.log(f"Error applying theme: {e}", "ERROR")

# ==================== MAIN ====================
if __name__ == "__main__":
    try:
        if getattr(sys, 'frozen', False):
            myappid = 'VideoWallpaperManager.MainApp.2.3'
        else:
            myappid = 'com.videowallpaper.app.script.2.3'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception as e:
        print(f"Failed to set AppUserModelID: {e}")

    app = QApplication(sys.argv)
    
    app.setApplicationName("Video Wallpaper Manager")
    app.setApplicationVersion("2.3")
    app.setOrganizationName("VideoWallpaper")
    
    try:
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
