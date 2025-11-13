from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


def get_hashcache_name() -> str:
    """Return the per-directory hash cache filename."""
    return os.environ.get("QC_HASHCACHE_NAME", ".qc.hashcache.json")


def load_hashcache(dir_path: Path) -> dict[str, Any]:
    """
    Load the hash cache JSON for a directory.

    Returns an empty dict on any error or if the cache file does not exist.
    """
    f = dir_path / get_hashcache_name()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_hashcache(dir_path: Path, cache: Mapping[str, Any]) -> None:
    """
    Persist the hash cache JSON for a directory.

    Silently ignores I/O errors to keep the crawler non-fatal.
    """
    f = dir_path / get_hashcache_name()
    try:
        f.write_text(
            json.dumps(cache, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception:
        # Best-effort only; don't kill the crawl if cache can't be written
        pass
