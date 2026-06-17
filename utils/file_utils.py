"""Common utility functions for file operations."""

import os
import hashlib
from pathlib import Path
from typing import Optional

# Supported image extensions
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.heic'}


def is_image_file(path: str) -> bool:
    """Check if a file is a supported image type."""
    try:
        ext = Path(path).suffix.lower()
        return ext in IMAGE_EXTENSIONS
    except Exception:
        return False


def compute_md5(path: str, chunk_size: int = 8192) -> Optional[str]:
    """Compute MD5 hash of a file.

    Args:
        path: Path to the file
        chunk_size: Size of chunks to read at a time

    Returns:
        MD5 hex digest string, or None if error
    """
    try:
        md5 = hashlib.md5()
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                md5.update(chunk)
        return md5.hexdigest()
    except Exception:
        return None


def get_file_size(path: str) -> Optional[int]:
    """Get file size in bytes.

    Returns:
        File size, or None if error
    """
    try:
        return os.path.getsize(path)
    except Exception:
        return None


def ensure_dir(path: str) -> bool:
    """Ensure a directory exists, creating it if necessary.

    Returns:
        True if directory exists/was created, False on error
    """
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception:
        return False


def generate_unique_path(dest_dir: str, filename: str) -> str:
    """Generate a unique file path, handling name collisions.

    If file.jpg exists, returns file_1.jpg, file_2.jpg, etc.

    Args:
        dest_dir: Destination directory
        filename: Original filename

    Returns:
        Unique full path for the file
    """
    dest = os.path.join(dest_dir, filename)
    if not os.path.exists(dest):
        return dest

    name, ext = os.path.splitext(filename)
    counter = 1
    while True:
        new_name = f"{name}_{counter}{ext}"
        dest = os.path.join(dest_dir, new_name)
        if not os.path.exists(dest):
            return dest
        counter += 1
