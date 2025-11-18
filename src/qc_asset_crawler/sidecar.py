from __future__ import annotations

from pathlib import Path
import sys
import json
import os
import logging
from typing import Any, Callable


# ---------------- Schema metadata & migrations ---------------- #

SCHEMA_NAME = os.environ.get("QC_SCHEMA_NAME", "qc-asset-crawler.sidecar")
SCHEMA_VERSION: int = 2  # current supported sidecar schema version


# Migration function: takes a sidecar dict at version N and returns a dict
# at version N+1.
MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]

# Map: from_version -> migration_fn that upgrades to from_version+1
MIGRATIONS: dict[int, MigrationFn] = {}


def migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    # Start from a fresh dict so we don't leak old top-level keys
    out: dict[str, Any] = {}

    # Required schema metadata
    out["schema_name"] = SCHEMA_NAME
    out["schema_version"] = 2

    # Identity / timing
    out["id"] = data.get("qc_id")
    out["timestamp"] = data.get("qc_time")
    out["operator"] = data.get("operator")

    # Tool / policy
    out["tool"] = {
        "version": data.get("tool_version"),
        "policy_version": data.get("policy_version"),
    }

    # Asset info
    seq = data.get("sequence")
    is_sequence = bool(seq)

    out["asset"] = {
        "id": str(data.get("asset_id")) if data.get("asset_id") is not None else None,
        "path": data.get("asset_path"),
        "type": "sequence" if is_sequence else "file",
        # if you want to keep the raw sequence block as-is:
        "sequence": seq if is_sequence else None,
    }

    # Content info (hash + state + sequence metrics if present)
    content: dict[str, Any] = {
        "hash": data.get("content_hash"),
        "state": data.get("content_state"),
    }

    if isinstance(seq, dict):
        content.update(
            {
                "base": seq.get("base"),
                "ext": seq.get("ext"),
                "pad": seq.get("pad"),
                "frame_count": seq.get("frame_count"),
                "frame_min": seq.get("frame_min"),
                "frame_max": seq.get("frame_max"),
                "first": seq.get("first"),
                "last": seq.get("last"),
                "holes": seq.get("holes"),
                "range_count": seq.get("range_count"),
                "cheap_fp": seq.get("cheap_fp"),
            }
        )

    out["content"] = content

    # QC info (current + last_valid)
    out["qc"] = {
        "status": data.get("qc_result"),
        "notes": data.get("notes"),
        "current": {
            "id": data.get("qc_id"),
            "time": data.get("qc_time"),
        },
        "last_valid": {
            "id": data.get("last_valid_qc_id"),
            "time": data.get("last_valid_qc_time"),
        },
        "checks": [],
        "errors": [],
    }

    return out


# -------------------------------------------------------------------
# ----------- TODO: Future schema upgrades when ratified ------------
# -------------------------------------------------------------------

# MIGRATIONS = {1: migrate_v1_to_v2}

# -------------------------------------------------------------------
# -------------------------------------------------------------------


def get_side_suffix_file() -> str:
    return os.environ.get("QC_SIDE_SUFFIX_FILE", ".qc.json")


def get_side_name_sequence() -> str:
    # Default to "sequence.qc.json" to match current sequence sidecar naming
    return os.environ.get("QC_SIDE_NAME_SEQUENCE", "sequence.qc.json")


def get_qc_policy_version() -> str:
    return os.environ.get("QC_POLICY_VERSION", "2025.11.0")


def _coerce_schema_version(value: Any) -> int:
    """
    Best-effort conversion of a stored schema_version field to an int.

    Accepts:
      - int (returned as-is)
      - "1", "2", "v1", "V2" -> 1, 2
    Falls back to 1 if it can't be interpreted.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip().lstrip("vV")
        try:
            return int(s)
        except ValueError:
            pass
    return 1


def get_schema_name() -> str:
    """
    Name/identifier of the sidecar schema. Environment override is optional
    but handy if we ever fork the format.
    """
    return os.environ.get("QC_SCHEMA_NAME", SCHEMA_NAME)


def get_schema_version() -> int:
    """
    Return the *target* schema version we want to write sidecars in.

    Environment variable QC_SCHEMA_VERSION can override the default to help
    with testing or staged rollouts, but must remain compatible with the
    MIGRATIONS table.

    # NOTE: QC_SCHEMA_VERSION from environment is for development/testing only.
    # In production, schema version must be controlled by code.
    """
    env = os.environ.get("QC_SCHEMA_VERSION")
    if env:
        return _coerce_schema_version(env)
    return SCHEMA_VERSION


def _get_payload_schema_version(data: dict[str, Any]) -> int:
    """Read the schema_version field from a payload, with sane defaults."""
    return _coerce_schema_version(data.get("schema_version", 1))


def ensure_schema_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure schema_name and schema_version fields are present and up to date
    on a sidecar payload. Returns a shallow copy.
    """
    out = dict(data)
    out["schema_name"] = get_schema_name()
    out["schema_version"] = get_schema_version()
    return out


def migrate_to_latest(data: dict[str, Any]) -> dict[str, Any]:
    """
    Upgrade a sidecar payload dict to the current SCHEMA_VERSION.

    Applies MIGRATIONS[v] sequentially: v -> v+1 -> ... until SCHEMA_VERSION
    or until a gap is found.
    """
    current = _get_payload_schema_version(data)
    target = get_schema_version()

    # Older -> try to migrate forward
    while current < target:
        fn = MIGRATIONS.get(current)
        if fn is None:
            logging.warning(
                "No migration path from schema v%s to v%s; leaving sidecar as-is",
                current,
                target,
            )
            break
        data = fn(data)
        current = _get_payload_schema_version(data)

    # Newer -> warn but still return the data
    if current > target:
        logging.warning(
            "Sidecar schema v%s is newer than supported v%s",
            current,
            target,
        )

    return data


# ----------------- Sidecars -----------------


def sidecar_path_for_file(p: Path) -> Path:
    mode = globals().get("G_SIDECAR_MODE", "inline")
    name = f"{p.name}{get_side_suffix_file()}"
    if mode == "inline":
        return p.with_suffix(p.suffix + get_side_suffix_file())
    if mode == "dot":
        return p.parent / f".{name}"
    return p.parent / ".qc" / name


def sequence_sidecar_path(dir_path: Path) -> Path:
    mode = globals().get("G_SIDECAR_MODE", "inline")
    if mode == "inline":
        return dir_path / get_side_name_sequence()
    if mode == "dot":
        return dir_path / f".{get_side_name_sequence()}"
    return dir_path / ".qc" / get_side_name_sequence()


def set_hidden_attribute(path: Path) -> None:
    mode = globals().get("G_SIDECAR_MODE", "inline")
    if mode not in ("dot", "subdir"):
        return
    try:
        if sys.platform.startswith("win"):
            import ctypes

            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
        elif sys.platform == "darwin":
            import subprocess

            subprocess.run(["chflags", "hidden", str(path)], check=False)
    except Exception:
        # Best-effort; failure to hide is non-fatal
        pass


def read_sidecar(path: Path) -> dict[str, Any] | None:
    """
    Read a sidecar file from disk and return its JSON payload as a dict.

    - Returns None on I/O or JSON errors (missing file is treated as normal).
    - Applies schema migrations if defined.
    - Ensures schema_name/schema_version fields are present and normalised.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Normal case: no sidecar yet for this asset/sequence
        return None
    except OSError as e:
        # Real I/O problem (permissions, network, etc.)
        logging.warning("Failed to read sidecar %s: %s", path, e)
        return None

    try:
        data: dict[str, Any] = json.loads(raw)
    except ValueError as e:
        logging.warning("Invalid JSON in sidecar %s: %s", path, e)
        return None

    # Upgrade older payloads if we know how
    data = migrate_to_latest(data)

    # Ensure schema metadata is present/updated
    data = ensure_schema_metadata(data)

    return data


def write_sidecar(path: Path, data: dict[str, Any]) -> None:
    """
    Write a sidecar JSON file atomically, ensuring schema metadata is present.
    """
    # Attach/update schema_name + schema_version
    payload = ensure_schema_metadata(data)

    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temporary file first for atomic replace
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # Atomic replace
    os.replace(tmp, path)

    # Reapply hidden flag
    set_hidden_attribute(path)


def needs_reqc(existing: dict[str, Any] | None, new_content_hash: str) -> bool:
    """
    Decide whether an asset needs (re)QC based on existing sidecar data
    and the new content hash.
    """
    if not existing:
        return True
    if existing.get("policy_version") != get_qc_policy_version():
        return True
    return existing.get("content_hash") != new_content_hash
