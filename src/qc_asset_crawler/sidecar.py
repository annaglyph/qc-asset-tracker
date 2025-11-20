from __future__ import annotations

import json
import os
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


# ---------------- Schema metadata & migrations ---------------- #

SCHEMA_NAME = os.environ.get("QC_SCHEMA_NAME", "qc-asset-crawler.sidecar")

# IMPORTANT: default is still v1 until v2 is agreed.
SCHEMA_VERSION = os.environ.get(
    "QC_SCHEMA_VERSION", "1"
)  # current supported sidecar schema version

# Define the known schema versions as integers for easy comparison
CURRENT_SCHEMA_VERSION = int(SCHEMA_VERSION)

# Keep this central for future schema handling
MIN_SUPPORTED_SCHEMA_VERSION = 1
MAX_SUPPORTED_SCHEMA_VERSION = CURRENT_SCHEMA_VERSION


# Migration function: takes a sidecar dict at version N and returns a dict
# at version N+1.
MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]

# Map: from_version -> migration_fn that upgrades to from_version+1
MIGRATIONS: dict[int, MigrationFn] = {}


V1_REQUIRED_FIELDS = {
    "schema_name",
    "schema_version",
    "asset_path",
    "asset_hash",
}

V1_OPTIONAL_FIELDS = {
    "asset_id",
    "last_seen",
    "policy_version",
    "notes",
    # add or remove as appropriate
}


def validate_v1_sidecar(data: dict[str, Any], *, strict: bool = False) -> None:
    """
    Validate a v1 sidecar structure.

    Raises ValueError if required fields are missing or types look wrong.
    """
    missing = [field for field in V1_REQUIRED_FIELDS if field not in data]
    if missing:
        raise ValueError(f"v1 sidecar missing required fields: {', '.join(missing)}")

    if data.get("schema_name") != SCHEMA_NAME:
        logging.warning(
            "Sidecar schema_name '%s' does not match expected '%s'",
            data.get("schema_name"),
            SCHEMA_NAME,
        )

    # Basic type checks (tune these based on real schema)
    if not isinstance(data.get("asset_path"), str):
        raise ValueError("v1 sidecar 'asset_path' must be a string")

    if not isinstance(data.get("asset_hash"), str):
        raise ValueError("v1 sidecar 'asset_hash' must be a string")

    if (
        "asset_id" in data
        and data["asset_id"] is not None
        and not isinstance(data["asset_id"], (str, int))
    ):
        raise ValueError("v1 sidecar 'asset_id' must be string, int or null")

    if strict:
        allowed_fields = V1_REQUIRED_FIELDS | V1_OPTIONAL_FIELDS
        extra = [field for field in data.keys() if field not in allowed_fields]
        if extra:
            logging.warning(
                "v1 sidecar has unexpected extra fields: %s", ", ".join(extra)
            )


def migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """
    Placeholder for future v1 -> v2 migration.

    Currently not implemented because v2 has not been agreed with the
    wider teams. When v2 is defined, implement the field transformations here.

    NOTE: this function is *not* wired into MIGRATIONS yet. Once the v2 schema
    is signed off, add an entry to MIGRATIONS, for example:

        MIGRATIONS[1] = migrate_v1_to_v2
    """
    raise NotImplementedError(
        "v2 schema is not yet defined. "
        "Do not set QC_SCHEMA_VERSION=2 until migration is implemented."
    )


def _coerce_schema_version(value: Any) -> int:
    """
    Best-effort conversion of a stored schema_version field to an int.

    Accepts:
      - int (returned as-is)
      - "1", "2", "v1", "V2" -> 1, 2

    Falls back to 1 if it can't be interpreted, defaulting to 1.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip().lstrip("vV")
        try:
            return int(s)
        except ValueError:
            logging.warning(
                "Unable to parse schema_version value %r; defaulting to 1",
                value,
            )
            return 1

    logging.warning(
        "Unexpected type for schema_version (%s); defaulting to 1",
        type(value).__name__,
    )
    return 1


def get_side_suffix_file() -> str:
    return os.environ.get("QC_SIDE_SUFFIX_FILE", ".qc.json")


def get_side_name_sequence() -> str:
    # Default to "sequence.qc.json" to match current sequence sidecar naming
    return os.environ.get("QC_SIDE_NAME_SEQUENCE", "sequence.qc.json")


def get_qc_policy_version() -> str:
    return os.environ.get("QC_POLICY_VERSION", "2025.11.0")


def get_schema_name() -> str:
    """
    Return the canonical schema_name that should be written into sidecars.

    Environment variable QC_SCHEMA_NAME can override the built-in default.
    """
    return os.environ.get("QC_SCHEMA_NAME", SCHEMA_NAME)


def get_schema_version() -> int:
    """
    Return the *target* schema version we want to write sidecars in.

    Environment variable QC_SCHEMA_VERSION can override the default to help
    with testing or staged rollouts, but must remain compatible with the
    MIGRATIONS table.

    NOTE: in production we expect schema bumps to be done via code changes,
    not via environment tweaks.
    """
    env = os.environ.get("QC_SCHEMA_VERSION")
    if env is not None:
        version = _coerce_schema_version(env)
    else:
        version = _coerce_schema_version(SCHEMA_VERSION)

    # Clamp to the supported range so we never "target" an unsupported version.
    if version < MIN_SUPPORTED_SCHEMA_VERSION:
        logging.warning(
            "Configured target schema_version %s is below minimum supported %s; "
            "using minimum.",
            version,
            MIN_SUPPORTED_SCHEMA_VERSION,
        )
        return MIN_SUPPORTED_SCHEMA_VERSION

    if version > MAX_SUPPORTED_SCHEMA_VERSION:
        logging.warning(
            "Configured target schema_version %s is above maximum supported %s; "
            "using maximum.",
            version,
            MAX_SUPPORTED_SCHEMA_VERSION,
        )
        return MAX_SUPPORTED_SCHEMA_VERSION

    return version


def _get_payload_schema_version(data: dict[str, Any]) -> int:
    """Read the schema_version field from a payload, with sane defaults."""
    return _coerce_schema_version(data.get("schema_version", 1))


def ensure_schema_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure schema_name and schema_version fields are present and up to date
    on a sidecar payload. Returns a shallow copy of the input dict.
    """
    out = dict(data)
    out["schema_name"] = get_schema_name()
    out["schema_version"] = get_schema_version()
    return out


def migrate_sidecar_if_needed(data: dict[str, Any]) -> dict[str, Any]:
    """
    Backwards-compatible helper to migrate a sidecar payload to the latest
    supported schema version, using the MIGRATIONS table.

    At the moment we only have v1, so this function is effectively a no-op,
    but the structure is in place for future v2+ upgrades.
    """
    return migrate_to_latest(data)


def migrate_to_latest(data: dict[str, Any]) -> dict[str, Any]:
    """
    Upgrade a sidecar payload dict to the current schema version.

    Applies MIGRATIONS[v] sequentially: v -> v+1 -> ... until get_schema_version()
    or until a gap is found.

    If the payload version is newer than we support, the payload is returned
    unchanged but a warning is logged.
    """
    current = _get_payload_schema_version(data)
    target = get_schema_version()

    if current == target:
        return data

    # Older -> try to migrate forward
    if current < target:
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

        return data

    # Newer -> warn but still return the data unchanged
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
        # Best-effort; failure to hide the file is not fatal
        logging.debug("Failed to set hidden attribute for %s", path)


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
