"""Scanner module - recursively scans a folder for image files."""

import os
from dataclasses import dataclass
from typing import List, Optional

from utils.file_utils import is_image_file, get_file_size


@dataclass
class ImageFile:
    """Represents a scanned image file."""
    path: str
    size: int
    name: str
    md5: str = ""


def scan_folder(folder_path: str) -> List[ImageFile]:
    """Recursively scan a folder for supported image files.

    Excludes files inside 'duplicates' and 'scanned' subdirectories.

    Args:
        folder_path: Root folder to scan

    Returns:
        List of ImageFile objects found
    """
    results: List[ImageFile] = []

    try:
        for root, dirs, files in os.walk(folder_path):
            # Skip duplicates and scanned directories
            rel = os.path.relpath(root, folder_path)
            parts = rel.lower().split(os.sep)
            if 'duplicates' in parts or 'scanned' in parts:
                continue

            for filename in files:
                filepath = os.path.join(root, filename)
                try:
                    if not is_image_file(filepath):
                        continue

                    size = get_file_size(filepath)
                    if size is None:
                        continue

                    img = ImageFile(
                        path=filepath,
                        size=size,
                        name=filename,
                    )
                    results.append(img)
                except Exception:
                    # Skip files that cause errors
                    continue
    except PermissionError:
        pass
    except FileNotFoundError:
        pass
    except Exception:
        pass

    return results
