from __future__ import annotations

import json
from pathlib import Path
import pytest


@pytest.fixture
def make_sidecar():
    """
    Fixture that returns a helper to create a valid minimal QC sidecar JSON file.

    Usage:
        sidecar_path = make_sidecar(path, qc_result="pass", notes="Hello")
    """

    def _make(
        path: Path,
        *,
        qc_result: str = "pending",
        asset_path: str | None = None,
        sequence: dict | None = None,
        notes: str | None = "",
        operator: str = "rus",
    ) -> Path:
        data = {
            "qc_id": "018e711a-5c5d-7e2c-b3f1-7b4f0ffb4a91",
            "qc_time": "2025-11-13T10:21:55.123456Z",
            "qc_result": qc_result,
            "notes": notes or "",
            "operator": operator,
            "tool_version": "eikon-qc-marker/1.1.0",
            "policy_version": "2025.11.0",
            "schema_version": "1.0.0",
            "asset_id": None,
            "asset_path": asset_path or str(path),
            "content_hash": "blake3:deadbeef",
            "sequence": sequence,
            "tracker_status": {"http_code": 200, "status": "ok"},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return _make


@pytest.fixture
def normalise_output():
    """
    Fixture that returns a helper to normalise Windows/POSIX paths in output.

    Usage:
        out = normalise_output(raw_output)
    """

    def _norm(s: str) -> str:
        return s.replace("\\", "/")

    return _norm


@pytest.fixture
def make_fake_sequence_tree(tmp_path: Path):
    """
    Create a realistic fake image-sequence directory structure.

    Returns a helper:

        root, frames = make_fake_sequence_tree(base="shot01", ext="dpx", count=10)

    Produces something like:

        tmp/shot01/0001.dpx
        tmp/shot01/0002.dpx
        ...
        tmp/shot01/0010.dpx
    """

    def _make_sequence(
        *,
        base: str = "shot",
        ext: str = "dpx",
        count: int = 12,
        pad: int = 4,
        start: int = 1,
        holes: list[int] = (),
    ):
        root = tmp_path / base
        root.mkdir(exist_ok=True)

        frames = []
        end = start + count - 1
        for frame in range(start, end + 1):
            if frame in holes:
                continue
            filename = f"{frame:0{pad}d}.{ext}"
            p = root / filename
            p.write_text("dummy", encoding="utf-8")
            frames.append(p)

        return root, frames

    return _make_sequence
