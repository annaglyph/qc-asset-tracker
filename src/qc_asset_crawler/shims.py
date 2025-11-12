from __future__ import annotations

import runpy
import sys
from pathlib import Path

# Resolve repo root regardless of site-packages install
PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parent.parent  # points to repo root when installed in editable mode


def _run_script(relpath: str) -> int:
    script_path = (REPO_ROOT / relpath).resolve()
    if not script_path.exists():
        print(f"[shim] Script not found: {script_path}", file=sys.stderr)
        return 2
    # Execute the script as __main__ with current argv untouched
    runpy.run_path(str(script_path), run_name="__main__")
    # If the script does sys.exit(code), it will exit before returning here.
    return 0


def crawl(argv: list[str] | None = None) -> int:
    return _run_script("qc_crawl.py")


def clean(argv: list[str] | None = None) -> int:
    return _run_script("qc_cleanup.py")


def fake_seq(argv: list[str] | None = None) -> int:
    return _run_script("make_fake_seq.py")
