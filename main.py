"""Photo Manager V1 - CLI Entry Point

Standard CLI interface for the photo deduplication tool.

Commands:
    python main.py run --input <folder>   # Run dedup scan
    python main.py reset                  # Clear history
    python main.py status                 # Show status
"""

import sys
import os
import argparse
import json

# Ensure project root is in path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core.scanner import scan_folder
from core.index_builder import build_index
from core.group_engine import group_by_md5
from core.deduper import HistoryDB, process_groups


# Default paths
DEFAULT_INPUT = r"E:\photo_manager\input_photos"
HISTORY_DB_PATH = os.path.join(BASE_DIR, "storage", "history_db.json")


def cli_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="photo_manager",
        description="Photo Manager V1 - MD5-based photo deduplication tool",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command
    run_parser = subparsers.add_parser("run", help="Run deduplication scan")
    run_parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        help=f"Input folder to scan (default: {DEFAULT_INPUT})",
    )

    # reset command
    subparsers.add_parser("reset", help="Clear history database")

    # status command
    subparsers.add_parser("status", help="Show system status")

    return parser


def run_command(input_folder: str) -> None:
    """Execute the full deduplication pipeline.

    Args:
        input_folder: Path to the folder to scan
    """
    # Validate input folder
    if not os.path.isdir(input_folder):
        print(f"Error: folder not found - {input_folder}")
        sys.exit(1)

    duplicates_dir = os.path.join(input_folder, "Duplicates")
    scanned_dir = os.path.join(input_folder, "Scanned")

    print(f"Scanning folder: {input_folder}")
    print("-" * 50)

    # STEP 1: Scan
    print("\n[1/5] Scanning image files...")
    try:
        images = scan_folder(input_folder)
    except Exception as e:
        print(f"Scan failed: {e}")
        sys.exit(1)

    total_scanned = len(images)
    print(f"  Found {total_scanned} image files")

    if total_scanned == 0:
        print("\nNo images found. Exiting.")
        sys.exit(0)

    # STEP 2: Index (size pruning + MD5)
    print("\n[2/5] Building index (size pruning + MD5)...")
    try:
        candidates = build_index(images)
    except Exception as e:
        print(f"Index build failed: {e}")
        sys.exit(1)

    print(f"  {len(candidates)} files need MD5 comparison")

    # STEP 3: Group by MD5
    print("\n[3/5] Grouping by MD5...")
    try:
        groups = group_by_md5(candidates)
    except Exception as e:
        print(f"Grouping failed: {e}")
        sys.exit(1)

    dup_groups = [g for g in groups if len(g.images) >= 2]
    print(f"  {len(groups)} groups total, {len(dup_groups)} with duplicates")

    # STEP 4: Process with history
    print("\n[4/5] Running deduplication (with history)...")
    history = HistoryDB(HISTORY_DB_PATH)

    try:
        moved_dup, moved_scan, error_files = process_groups(
            groups, history, duplicates_dir, scanned_dir
        )
    except Exception as e:
        print(f"Dedup processing failed: {e}")
        sys.exit(1)

    # STEP 5: Commit history (batch write)
    print("\n[5/5] Committing history...")
    if history.commit():
        print("  History saved.")
    else:
        print("  Warning: history save failed!")

    # Final report
    print("\n" + "=" * 50)
    print("Deduplication complete!")
    print("=" * 50)
    print(f"  Total scanned:       {total_scanned}")
    print(f"  Duplicate groups:    {len(dup_groups)}")
    print(f"  Moved to Duplicates: {moved_dup}")
    print(f"  Moved to Scanned:    {moved_scan}")

    if error_files:
        print(f"\n  Error files ({len(error_files)}):")
        for f in error_files:
            print(f"    - {f}")
    else:
        print("\n  No error files.")

    print("=" * 50)


def reset_command() -> None:
    """Clear the history database."""
    try:
        # Delete and recreate as empty
        if os.path.exists(HISTORY_DB_PATH):
            os.remove(HISTORY_DB_PATH)

        # Ensure storage directory exists
        os.makedirs(os.path.dirname(HISTORY_DB_PATH), exist_ok=True)

        with open(HISTORY_DB_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)

        print("History reset completed.")
    except Exception as e:
        print(f"Reset failed: {e}")
        sys.exit(1)


def _count_images(folder: str) -> int:
    """Count image files in a folder (non-recursive for status dirs)."""
    if not os.path.isdir(folder):
        return 0
    count = 0
    try:
        for entry in os.listdir(folder):
            path = os.path.join(folder, entry)
            if os.path.isfile(path):
                ext = os.path.splitext(entry)[1].lower()
                if ext in {".jpg", ".jpeg", ".png", ".webp", ".heic"}:
                    count += 1
    except Exception:
        pass
    return count


def status_command() -> None:
    """Display system status: hash count, file counts per directory."""
    # History hash count
    hash_count = 0
    try:
        if os.path.exists(HISTORY_DB_PATH):
            with open(HISTORY_DB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                hash_count = len(data)
    except Exception:
        pass

    # Count images in each directory
    input_count = _count_images(DEFAULT_INPUT)
    scanned_count = _count_images(os.path.join(DEFAULT_INPUT, "Scanned"))
    duplicates_count = _count_images(os.path.join(DEFAULT_INPUT, "Duplicates"))

    print(f"History hashes: {hash_count}")
    print(f"Input images: {input_count}")
    print(f"Scanned: {scanned_count}")
    print(f"Duplicates: {duplicates_count}")


def main() -> None:
    """CLI entry point - parse args and route to command handler."""
    parser = cli_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "run":
        run_command(args.input)
    elif args.command == "reset":
        reset_command()
    elif args.command == "status":
        status_command()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
