🎬 Video Wallpaper Manager


A unified Windows application for managing video wallpapers with online discovery, smooth transitions, and global keyboard shortcuts.
 Python 



 Platform 
✨ Features
🔍 Discover
Search and download wallpapers from MoeWalls.com
Live preview thumbnails
One-click download with progress bar
Auto-import to library
📁 Library
Grid view of all local wallpapers
Set wallpaper directly from library
Add videos from file dialog
Quick actions: Previous, Next, Random
🖥️ Display
Multi-monitor support: Span, Duplicate, or Individual modes
Smooth crossfade transitions (configurable duration)
Per-monitor assignment (Individual mode)
Auto-change timer with interval setting
⌨️ Keyboard Shortcuts
Global hotkeys that work even when minimized
Customizable shortcuts in Settings
Default shortcuts:
Ctrl+Shift+N - Next wallpaper
Ctrl+Shift+P - Previous wallpaper
Ctrl+Shift+R - Random wallpaper
Ctrl+Shift+T - Pause/Resume
🔔 System Tray
Minimize to system tray
Tray menu with quick actions
Custom application icon
🚀 Installation
Prerequisites
Windows 10/11
MPV installed and in PATH
Python 3.8+ (for running from source)
Option 1: Download Pre-built EXE
Download the latest release from Releases
Extract the ZIP file
Run VideoWallpaperManager.exe
Option 2: Run from Source
bash
Copy
# Clone the repository
git clone https://github.com/avraniel/video-wallpaper-manager.git
cd video-wallpaper-manager

# Install dependencies
pip install -r requirements.txt

# Run the application
python video_wallpaper_manager.py
📦 Building from Source
To create a standalone EXE:
bash
Copy
# Install PyInstaller
pip install pyinstaller

# Build the executable
python -m PyInstaller --windowed --name "VideoWallpaperManager" video_wallpaper_manager.py

# Or use the build script
python build.py
The executable will be created in dist/VideoWallpaperManager/.


🎯 Usage
First Launch: The app will create a wallpapers folder in the same directory
Discover Tab: Search and download wallpapers from MoeWalls
Library Tab: Manage your local collection and set wallpapers
Display Tab: Configure multi-monitor settings and transitions
Settings Tab: Customize keyboard shortcuts and general settings


🛠️ Configuration
Settings are stored in config.json:
JSON
Copy
{
  "mode": "individual",
  "transition_duration": 1.2,
  "auto_change_enabled": false,
  "auto_change_interval": 300,
  "shortcuts_enabled": true,
  "shortcuts": {
    "next": "<ctrl>+<shift>+n",
    "prev": "<ctrl>+<shift>+p",
    "random": "<ctrl>+<shift>+r",
    "toggle": "<ctrl>+<shift>+t"
  }
}

📋 Requirements
Windows 10/11
MPV media player
Python 3.8+ (for source)
Dependencies (see requirements.txt):
PyQt6
requests
beautifulsoup4
pillow
screeninfo
pywin32
pynput (optional, for keyboard shortcuts)

🤝 Contributing
Contributions are welcome! Please feel free to submit a Pull Request.
📝 License
This project is licensed under the MIT License - see the LICENSE file for details.

🙏 Acknowledgments
MoeWalls for the wallpaper source
MPV for the video playback engine


Made with ❤️ by Raniel
