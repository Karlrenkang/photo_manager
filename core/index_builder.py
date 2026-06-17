"""Index builder - groups by size, computes MD5 only when needed."""

from typing import Dict, List

from core.scanner import ImageFile
from utils.file_utils import compute_md5


def build_index(images: List[ImageFile]) -> List[ImageFile]:
    """Build MD5 index using size-based pruning.

    Steps:
    1. Group images by file size
    2. Only compute MD5 for groups with 2+ files (potential duplicates)
    3. Single-file size groups are skipped (cannot be duplicates)

    Args:
        images: List of scanned ImageFile objects

    Returns:
        List of ImageFile objects with MD5 computed (only potential duplicates)
    """
    # Step 1: Group by size
    size_map: Dict[int, List[ImageFile]] = {}
    for img in images:
        if img.size not in size_map:
            size_map[img.size] = []
        size_map[img.size].append(img)

    # Step 2: Only process size groups with 2+ files
    candidates: List[ImageFile] = []
    for size, group in size_map.items():
        if len(group) < 2:
            # Size unique - cannot be duplicate, skip entirely
            continue
        candidates.extend(group)

    # Step 3: Compute MD5 for candidates
    for img in candidates:
        md5 = compute_md5(img.path)
        if md5 is not None:
            img.md5 = md5

    return candidates
