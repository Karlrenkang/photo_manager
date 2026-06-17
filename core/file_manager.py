"""File manager - handles moving files to duplicates/scanned directories."""

import os
import shutil
from typing import Optional

from utils.file_utils import ensure_dir, generate_unique_path


def move_file(src: str, dest_dir: str) -> Optional[str]:
    """Move a file to destination directory with unique name handling.

    Args:
        src: Source file path
        dest_dir: Destination directory

    Returns:
        Destination path if successful, None on error
    """
    try:
        if not ensure_dir(dest_dir):
            return None

        filename = os.path.basename(src)
        dest = generate_unique_path(dest_dir, filename)

        shutil.move(src, dest)
        return dest
    except PermissionError:
        return None
    except FileNotFoundError:
        return None
    except Exception:
        return None
