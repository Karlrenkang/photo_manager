"""Deduper - core deduplication logic with history management."""

import json
import os
from typing import Dict, List, Set, Tuple

from core.scanner import ImageFile
from core.group_engine import Group, split_groups
from core.file_manager import move_file


class HistoryDB:
    """Manages the hash-based history database."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db: Dict[str, bool] = {}
        self.new_hashes: Set[str] = set()
        self._load()

    def _load(self):
        """Load history from JSON file."""
        try:
            if os.path.exists(self.db_path):
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    self.db = json.load(f)
        except Exception:
            self.db = {}

    def contains(self, md5: str) -> bool:
        """Check if hash exists in history."""
        return md5 in self.db

    def add_new_hash(self, md5: str):
        """Add hash to pending new hashes (in memory only)."""
        self.new_hashes.add(md5)

    def commit(self) -> bool:
        """Batch write all new hashes to disk.

        Returns:
            True if successful, False on error
        """
        try:
            self.db.update({h: True for h in self.new_hashes})
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(self.db, f, indent=2)
            self.new_hashes.clear()
            return True
        except Exception:
            return False

    def reset(self) -> bool:
        """Clear all history."""
        try:
            self.db = {}
            self.new_hashes.clear()
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(self.db, f, indent=2)
            return True
        except Exception:
            return False


def dedup_sort_key(img: ImageFile) -> str:
    """Sort key for images: filename ascending."""
    return img.name.lower()


def process_groups(
    groups: List[Group],
    history: HistoryDB,
    duplicates_dir: str,
    scanned_dir: str,
) -> Tuple[int, int, List[str]]:
    """Process groups and move files according to history rules.

    Rules:
    - History MISS + single: do nothing, add hash to cache
    - History MISS + multi: sort, keep first, move rest to duplicates
    - History HIT + single: move to scanned
    - History HIT + multi: keep first -> scanned, rest -> duplicates

    Args:
        groups: List of Group objects
        history: HistoryDB instance
        duplicates_dir: Path to duplicates directory
        scanned_dir: Path to scanned directory

    Returns:
        Tuple of (moved_to_duplicates, moved_to_scanned, error_files)
    """
    single_groups, multi_groups = split_groups(groups)

    moved_dup = 0
    moved_scan = 0
    errors: List[str] = []

    # Process single groups
    for group in single_groups:
        img = group.images[0]
        if not img.md5:
            continue

        if history.contains(img.md5):
            # HIT: move to scanned
            dest = move_file(img.path, scanned_dir)
            if dest:
                moved_scan += 1
            else:
                errors.append(img.path)
        else:
            # MISS: just add to cache
            history.add_new_hash(img.md5)

    # Process multi groups
    for group in multi_groups:
        # Sort by filename ascending
        sorted_images = sorted(group.images, key=dedup_sort_key)
        keep = sorted_images[0]
        duplicates = sorted_images[1:]

        group.keep = keep
        group.duplicates = duplicates

        if history.contains(keep.md5):
            # HIT: keep -> scanned, duplicates -> duplicates
            dest = move_file(keep.path, scanned_dir)
            if dest:
                moved_scan += 1
            else:
                errors.append(keep.path)

            for img in duplicates:
                dest = move_file(img.path, duplicates_dir)
                if dest:
                    moved_dup += 1
                else:
                    errors.append(img.path)
        else:
            # MISS: keep stays, duplicates -> duplicates, add hash
            for img in duplicates:
                dest = move_file(img.path, duplicates_dir)
                if dest:
                    moved_dup += 1
                else:
                    errors.append(img.path)

            history.add_new_hash(keep.md5)

    return moved_dup, moved_scan, errors
