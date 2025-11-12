#!/usr/bin/env python3
"""
QC Cleanup Utility
------------------
Removes all QC-generated artifacts from a given path so you can re-test
the crawler as if it were a fresh environment.

Deletes:
  - `.qc/` folders (recursively)
  - `*.qc.json` sidecars
  - `qc.sequence.json` files
  - `.qc.hashcache.json` files
  - dot-prefixed `.something.qc.json` files

Usage examples:
# Preview what would be deleted
python qc-cleanup.py /SAN/jobs --dry-run

# Actually delete
python qc-cleanup.py /SAN/jobs

"""

import os
from pathlib import Path
import argparse

TARGET_FILENAMES = {
    "qc.sequence.json",
    ".qc.hashcache.json",
}


def cleanup(root: Path, dry_run: bool = False) -> int:
    removed = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        p = Path(dirpath)

        # 1. Remove known sidecar files
        for f in filenames:
            if (
                f.endswith(".qc.json")
                or f in TARGET_FILENAMES
                or f.startswith(".")
                and f.endswith(".qc.json")
            ):
                file_path = p / f
                if dry_run:
                    print(f"[DRY-RUN] Would remove: {file_path}")
                else:
                    try:
                        file_path.unlink()
                        print(f"Removed: {file_path}")
                        removed += 1
                    except Exception as e:
                        print(f"Failed to remove {file_path}: {e}")

        # 2. Remove entire `.qc` subdirectories
        for d in dirnames:
            if d == ".qc":
                qc_dir = p / d
                if dry_run:
                    print(f"[DRY-RUN] Would remove directory: {qc_dir}")
                else:
                    try:
                        for sub in qc_dir.rglob("*"):
                            try:
                                sub.unlink()
                            except IsADirectoryError:
                                pass
                        qc_dir.rmdir()
                        print(f"Removed directory: {qc_dir}")
                        removed += 1
                    except Exception as e:
                        print(f"Failed to remove {qc_dir}: {e}")
    return removed


def main():
    ap = argparse.ArgumentParser(description="Clean up QC sidecar and cache files.")
    ap.add_argument("root", help="Root folder to clean")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without deleting anything",
    )
    args = ap.parse_args()

    root = Path(args.root).resolve()
    print(f"Cleaning QC artifacts under: {root}")
    removed = cleanup(root, dry_run=args.dry_run)
    print(
        f"Done. {'Would have removed' if args.dry_run else 'Removed'} {removed} items."
    )


if __name__ == "__main__":
    main()
