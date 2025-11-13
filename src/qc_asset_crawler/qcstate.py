from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from qc_asset_crawler import sidecar
from qc_asset_crawler import config


def now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def uuid7() -> str:
    """
    Generate a time-ordered UUID.

    Use uuid.uuid7() when available (py>=3.12), otherwise fall back to a
    ULID-like construction based on current milliseconds + random bytes.
    """
    if hasattr(uuid, "uuid7"):
        return str(uuid.uuid7())  # py>=3.12

    # Fallback: time-ordered-ish UUID
    t_ms = int(time.time() * 1000).to_bytes(6, "big")
    rand = os.urandom(10)
    return str(uuid.UUID(bytes=t_ms + rand))


def make_qc_signature(
    asset_path: Path,
    content_hash: str,
    asset_id: Optional[str],
    operator: str,
    result: str = "pass",
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the core QC signature dict for a single asset or sequence.

    This mirrors the original implementation from qc_crawl.py, including:
    - qc_id / qc_time
    - operator / tool_version / policy_version
    - asset_path / asset_id / content_hash
    - qc_result / notes
    """
    return {
        "qc_id": uuid7(),
        "qc_time": now_iso(),
        "operator": operator,
        "tool_version": config.get_tool_version(),
        "policy_version": sidecar.get_qc_policy_version(),
        "asset_path": asset_path.as_posix(),
        "asset_id": asset_id,
        "content_hash": content_hash,
        "qc_result": result,
        "notes": note or "",
    }
