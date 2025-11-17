from __future__ import annotations

from pathlib import Path

import pytest


def test_single_file_preserves_existing_asset_id_when_trak_returns_no_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Nightly run, content changed, Trak returns no asset_id (401/404/etc).

    Expected:
      - qc_result reset to 'pending'
      - content_state set to 'modified'
      - existing asset_id is kept and used when posting to Trak
    """
    from qc_asset_crawler import crawler

    # Fake media file
    p = tmp_path / "clip.mxf"
    p.write_bytes(b"dummy")

    # Existing sidecar with an asset_id and old content hash
    existing_sidecar = {
        "asset_id": "ASSET-123",
        "content_hash": "old-hash",
        "policy_version": "2025.11.0",
        "qc_id": "QC-EXISTING",
    }

    # ---- Monkeypatch sidecar helpers ----
    def fake_sidecar_path_for_file(path: Path) -> Path:
        # Just return a sensible path; write_sidecar is stubbed anyway
        return tmp_path / ".qc" / f"{path.name}.qc.json"

    monkeypatch.setattr(
        crawler.sidecar, "sidecar_path_for_file", fake_sidecar_path_for_file
    )
    monkeypatch.setattr(crawler.sidecar, "read_sidecar", lambda sc: existing_sidecar)
    # Force re-QC so we don't hit the early "skip" path
    monkeypatch.setattr(crawler.sidecar, "needs_reqc", lambda existing, ch: True)
    # Don't actually write anything to disk in this test
    monkeypatch.setattr(crawler.sidecar, "write_sidecar", lambda sc, sig: None)

    # ---- Hashing: pretend content changed ----
    monkeypatch.setattr(
        crawler.hashing, "blake3_or_sha256_file", lambda path: "new-hash"
    )

    # ---- qcstate: keep it very simple and record what we build ----
    made_signatures = []

    def fake_make_qc_signature(path, content_hash, asset_id, operator, result, note):
        sig = {
            "path": str(path),
            "content_hash": content_hash,
            "asset_id": asset_id,
            "operator": operator,
            "result": result,
            "note": note,
            "qc_id": "QC-NEW",
        }
        made_signatures.append(sig)
        return sig

    monkeypatch.setattr(crawler.qcstate, "make_qc_signature", fake_make_qc_signature)

    # ---- Trak: lookup returns no asset_id (e.g. 401) ----
    def fake_lookup(path: Path):
        return {"status": "unauthorized", "http_code": 401}

    monkeypatch.setattr(
        crawler.trak_client, "tracker_lookup_asset_by_path", fake_lookup
    )

    set_qc_calls = []

    def fake_set_qc(asset_id, sig):
        set_qc_calls.append((asset_id, sig))

    monkeypatch.setattr(crawler.trak_client, "tracker_set_qc", fake_set_qc)

    # ---- Avoid OS-specific xattr writes during tests ----
    monkeypatch.setattr(crawler, "set_xattr", lambda path, value: None)

    # Nightly / autonomous mode
    crawler.G_FORCED_RESULT = None
    crawler.G_NOTE = None

    status, out_path = crawler.process_single_file(p, operator="rus", asset_id=None)

    assert status == "marked"
    assert out_path == p

    # We should have posted exactly once to Trak
    assert set_qc_calls
    asset_id_posted, sig = set_qc_calls[-1]

    # Core expectation: existing asset_id is preserved and used
    assert asset_id_posted == "ASSET-123"
    assert sig["asset_id"] == "ASSET-123"

    # And content was recognised as modified
    assert sig.get("content_state") == "modified"


def test_sequence_preserves_existing_asset_id_when_trak_returns_no_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Same scenario as above, but for image sequences.

    Nightly run, content changed, Trak returns no asset_id.

    Expected:
      - qc_result reset to 'pending'
      - content_state set to 'modified'
      - existing asset_id kept and used when posting to Trak
    """
    from qc_asset_crawler import crawler

    # Fake sequence directory with a few frames
    dir_path = tmp_path / "shotA"
    dir_path.mkdir()
    files = []
    for frame in range(1001, 1004):
        f = dir_path / f"shotA.{frame:04d}.exr"
        f.write_bytes(b"dummy")
        files.append(f)

    # Existing sequence sidecar
    existing_sidecar = {
        "asset_id": "ASSET-SEQ-1",
        "content_hash": "old-seq-hash",
        "policy_version": "OLD-POLICY",
        "qc_id": "QC-SEQ-EXISTING",
        "sequence": {"cheap_fp": "old-fp"},
    }

    # ---- Monkeypatch sidecar helpers ----
    def fake_sequence_sidecar_path(d: Path) -> Path:
        return d / ".qc" / "sequence.qc.json"

    monkeypatch.setattr(
        crawler.sidecar, "sequence_sidecar_path", fake_sequence_sidecar_path
    )
    monkeypatch.setattr(crawler.sidecar, "read_sidecar", lambda sc: existing_sidecar)
    monkeypatch.setattr(crawler.sidecar, "needs_reqc", lambda existing, h: True)
    monkeypatch.setattr(crawler.sidecar, "write_sidecar", lambda sc, sig: None)

    # ---- Hashing / cache: pretend content changed ----
    monkeypatch.setattr(crawler.hashing, "cheap_fingerprint", lambda fs: "new-fp")
    monkeypatch.setattr(
        crawler.hashing, "manifest_hash_for_files", lambda fs, cache: "new-seq-hash"
    )
    monkeypatch.setattr(crawler.hashcache, "load_hashcache", lambda d: {})
    monkeypatch.setattr(crawler.hashcache, "save_hashcache", lambda d, cache: None)

    # Avoid the cheap-fp+policy fast-skip by making policy differ
    monkeypatch.setattr(crawler.sidecar, "get_qc_policy_version", lambda: "NEW-POLICY")

    # Summarise frames: stub out real logic
    fake_seq_info = {
        "base": "shotA",
        "ext": "exr",
        "frame_min": 1001,
        "frame_max": 1003,
        "frame_count": 3,
        "holes": 0,
        "pad": 4,
        "range_count": 1,
    }
    monkeypatch.setattr(crawler, "summarize_frames", lambda names: fake_seq_info)

    # ---- qcstate: same simple signature capture ----
    made_signatures = []

    def fake_make_qc_signature(path, content_hash, asset_id, operator, result, note):
        sig = {
            "path": str(path),
            "content_hash": content_hash,
            "asset_id": asset_id,
            "operator": operator,
            "result": result,
            "note": note,
            "qc_id": "QC-SEQ-NEW",
        }
        made_signatures.append(sig)
        return sig

    monkeypatch.setattr(crawler.qcstate, "make_qc_signature", fake_make_qc_signature)

    # ---- Trak: lookup returns nothing useful ----
    def fake_lookup(path: Path):
        return {"status": "unauthorized", "http_code": 401}

    monkeypatch.setattr(
        crawler.trak_client, "tracker_lookup_asset_by_path", fake_lookup
    )

    set_qc_calls = []

    def fake_set_qc(asset_id, sig):
        set_qc_calls.append((asset_id, sig))

    monkeypatch.setattr(crawler.trak_client, "tracker_set_qc", fake_set_qc)

    # Avoid xattr in tests
    monkeypatch.setattr(crawler, "set_xattr", lambda path, value: None)

    crawler.G_FORCED_RESULT = None
    crawler.G_NOTE = None

    status, marked_path = crawler.process_sequence(
        dir_path=dir_path,
        base="shotA",
        ext="exr",
        files=files,
        operator="rus",
        asset_id=None,
    )

    assert status == "marked"

    # We should have posted exactly once to Trak
    assert set_qc_calls
    asset_id_posted, sig = set_qc_calls[-1]

    # Again: existing asset_id must be preserved and used
    assert asset_id_posted == "ASSET-SEQ-1"
    assert sig["asset_id"] == "ASSET-SEQ-1"

    # And content recognised as modified
    assert sig.get("content_state") == "modified"
