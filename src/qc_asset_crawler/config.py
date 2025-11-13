from __future__ import annotations

import os


# Tool identity / version (semver-compatible string)
TOOL_VERSION = "eikon-qc-marker/1.1.0"


def get_tool_version() -> str:
    """Return the tool version string used in sidecars and logs."""
    return TOOL_VERSION


def get_xattr_key() -> str:
    """
    Return the extended-attribute key used to tag files with QC IDs.

    Allows override via QC_XATTR_KEY in the environment.
    """
    return os.environ.get("QC_XATTR_KEY", "user.eikon.qc")
