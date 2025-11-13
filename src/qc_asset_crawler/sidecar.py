from __future__ import annotations

from pathlib import Path
import sys
import json
import os


def get_side_suffix_file() -> str:
    return os.environ.get("QC_SIDE_SUFFIX_FILE", ".qc.json")


def get_side_name_sequence() -> str:
    return os.environ.get("QC_SIDE_NAME_SEQUENCE", "qc.sequence.json")


def get_qc_policy_version() -> str:
    return os.environ.get("QC_POLICY_VERSION", "2025.11.0")


def get_schema_version() -> str:
    """
    Return the sidecar schema version.

    This is separate from QC_POLICY_VERSION (which controls re-QC policy).
    Bump this when you change the JSON shape in a non-trivial way.
    """
    return os.environ.get("QC_SCHEMA_VERSION", "1.0.0")


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
        pass


def read_sidecar(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_sidecar(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    set_hidden_attribute(path)


def needs_reqc(existing, new_content_hash: str) -> bool:
    if not existing:
        return True
    if existing.get("policy_version") != get_qc_policy_version():
        return True
    return existing.get("content_hash") != new_content_hash
