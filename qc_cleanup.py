#!/usr/bin/env python3
"""
QC Cleanup Utility
------------------

Removes all QC-generated artifacts from a given path so you can re-test the
crawler as if it were a fresh environment.

Deletes:
- `.qc/` folders (recursively)
- inline `*.qc.json` sidecars
- sequence sidecars (inline, subdir, and dot modes)
- hash cache files (e.g. .qc.hashcache.json)

Usage examples:
    # Preview what would be deleted
    python qc-cleanup.py /SAN/jobs --dry-run

    # Actually delete
    python qc-cleanup.py /SAN/jobs
"""

import os
from pathlib import Path
import argparse

from qc_asset_crawler import sidecar, hashcache


SIDE_SUFFIX_FILE = sidecar.get_side_suffix_file()  # e.g. ".qc.json"
SEQ_NAME = sidecar.get_side_name_sequence()  # e.g. "qc.sequence.json"
HASHCACHE_NAME = hashcache.get_hashcache_name()  # e.g. ".qc.hashcache.json"

# Dot-variant of the sequence name, used in --sidecar-mode dot, e.g. ".qc.sequence.json"
SEQ_DOT_NAME = SEQ_NAME if SEQ_NAME.startswith(".") else f".{SEQ_NAME}"


def should_remove_file(name: str) -> bool:
    """
    Decide whether a file should be removed as a QC artifact.
    """
    # Inline sidecars (applies to inline mode + dot-prefixed inline files)
    if name.endswith(SIDE_SUFFIX_FILE):
        return True

    # Sequence sidecars (inline/subdir + dot variants)
    if name == SEQ_NAME or name == SEQ_DOT_NAME:
        return True

    # Hash cache
    if name == HASHCACHE_NAME:
        return True

    return False


def cleanup(root: Path, dry_run: bool = False) -> int:
    removed = 0

    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        p = Path(dirpath)

        # 1. Remove known sidecar / cache files
        for f in filenames:
            file_path = p / f
            if should_remove_file(f):
                if dry_run:
                    print(f"[DRY-RUN] Would remove: {file_path}")
                else:
                    try:
                        file_path.unlink()
                        print(f"Removed: {file_path}")
                        removed += 1
                    except Exception as e:
                        print(f"Failed to remove {file_path}: {e}")

        # 2. Remove entire `.qc` subdirectories (subdir mode)
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


def main() -> None:
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
