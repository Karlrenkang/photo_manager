"""
Path utilities for Photo Manager V1.1

Handles path resolution for both development and PyInstaller frozen environments.
"""

import os
import sys


def get_base_dir() -> str:
    """Get the base directory of the application.

    Works correctly in both:
    - Development: returns the directory containing this file
    - Frozen (PyInstaller): returns the temp extraction dir (_MEIPASS)
    """
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_app_data_dir() -> str:
    """Get the user-writable app data directory.

    Returns:
        %APPDATA%/PhotoManager/ on Windows
        ~/.config/PhotoManager/ on other platforms
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(appdata, "PhotoManager")
    else:
        return os.path.join(os.path.expanduser("~"), ".config", "PhotoManager")


def get_history_db_path() -> str:
    """Get the full path to history_db.json in the user data directory."""
    return os.path.join(get_app_data_dir(), "history_db.json")
