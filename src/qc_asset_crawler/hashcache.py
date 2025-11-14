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
    Persist the hash cache JSON for a directory atomically.

    Best-effort only — failures should never kill the crawl.
    """
    path = Path(dir_path) / get_hashcache_name()
    tmp = path.with_suffix(path.suffix + ".tmp")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass

        # Atomic promotion
        os.replace(tmp, path)

    except Exception:
        # Best-effort: if anything goes wrong, just abandon
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return
