from __future__ import annotations

from pathlib import Path

import pytest


def test_run_processes_sequences_and_singles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Integration-ish test for crawler.run():

    - Build a fake tree with one image sequence and one single media file.
    - Stub out hashing, Trak, sidecar I/O, xattrs and mark_missing_content.
    - Verify that:
        * both the sequence and single are processed
        * tracker_set_qc is invoked for each
        * sidecars are written
        * content_state is set for these new assets ('new' or 'modified')
    """
    from qc_asset_crawler import crawler

    # ------------------------------------------------------------
    # 1. Build a tiny fake show tree
    # ------------------------------------------------------------
    root = tmp_path / "show"
    seq_dir = root / "shotA"
    seq_dir.mkdir(parents=True, exist_ok=True)

    # Sequence frames
    seq_files = []
    for frame in range(1, 5):  # 4 frames: 0001–0004
        f = seq_dir / f"shotA.{frame:04d}.exr"
        f.write_bytes(b"frame")
        seq_files.append(f)

    # Single file at show root
    single = root / "clip.mxf"
    single.write_bytes(b"clip")

    # ------------------------------------------------------------
    # 2. Monkeypatch dependencies used by crawler.run()
    # ------------------------------------------------------------

    # iter_media: don't rely on real scanning, just return our files
    def fake_iter_media(r: Path):
        assert r == root
        return seq_files + [single]

    monkeypatch.setattr(crawler, "iter_media", fake_iter_media)

    # Sidecar paths: send them to a .qc folder under the root/shot
    def fake_sidecar_path_for_file(path: Path) -> Path:
        return root / ".qc" / f"{path.name}.qc.json"

    def fake_sequence_sidecar_path(dir_path: Path) -> Path:
        return dir_path / ".qc" / "sequence.qc.json"

    monkeypatch.setattr(
        crawler.sidecar, "sidecar_path_for_file", fake_sidecar_path_for_file
    )
    monkeypatch.setattr(
        crawler.sidecar, "sequence_sidecar_path", fake_sequence_sidecar_path
    )

    # Existing sidecars: none for this first crawl
    monkeypatch.setattr(crawler.sidecar, "read_sidecar", lambda sc: None)
    # Always require QC (avoid skip path)
    monkeypatch.setattr(crawler.sidecar, "needs_reqc", lambda existing, ch: True)

    # Capture written sidecars instead of writing to disk
    written_sidecars: dict[Path, dict] = {}

    def fake_write_sidecar(sc: Path, sig: dict) -> None:
        written_sidecars[sc] = sig

    monkeypatch.setattr(crawler.sidecar, "write_sidecar", fake_write_sidecar)

    # Hashing: pretend we hash files but return stable fake values
    monkeypatch.setattr(
        crawler.hashing,
        "blake3_or_sha256_file",
        lambda path: f"hash-{path.name}",
    )
    monkeypatch.setattr(
        crawler.hashing,
        "cheap_fingerprint",
        lambda files: "cheap-fp",
    )
    monkeypatch.setattr(
        crawler.hashing,
        "manifest_hash_for_files",
        lambda files, cache: "manifest-hash",
    )

    # Hashcache: disable persistence
    monkeypatch.setattr(crawler.hashcache, "load_hashcache", lambda d: {})
    monkeypatch.setattr(crawler.hashcache, "save_hashcache", lambda d, cache: None)

    # Summarise frames: we already test summarize_frames elsewhere, so here we
    # can stub it to a fixed structure to keep this integration test simple.
    fake_seq_info = {
        "base": "shotA",
        "ext": "exr",
        "frame_min": 1,
        "frame_max": 4,
        "frame_count": 4,
        "holes": 0,
        "pad": 4,
        "range_count": 1,
    }
    monkeypatch.setattr(crawler, "summarize_frames", lambda names: fake_seq_info)

    # qcstate: capture signatures that the crawler builds
    made_signatures: list[dict] = []

    def fake_make_qc_signature(path, content_hash, asset_id, operator, result, note):
        sig = {
            "path": str(path),
            "content_hash": content_hash,
            "asset_id": asset_id,
            "operator": operator,
            "qc_result": result,
            "note": note,
            # Include qc_id because crawler accesses sig["qc_id"]
            "qc_id": f"QC-{len(made_signatures) + 1}",
        }
        made_signatures.append(sig)
        return sig

    monkeypatch.setattr(crawler.qcstate, "make_qc_signature", fake_make_qc_signature)

    # Trak: lookup returns an asset_id based on the path name
    def fake_lookup(path: Path):
        # We don't care about status codes here, just that an asset_id is provided.
        return {
            "status": "ok",
            "http_code": 200,
            "asset_id": f"ASSET-{path.name}",
        }

    monkeypatch.setattr(
        crawler.trak_client, "tracker_lookup_asset_by_path", fake_lookup
    )

    set_qc_calls: list[tuple[str, dict]] = []

    def fake_set_qc(asset_id: str, sig: dict) -> None:
        set_qc_calls.append((asset_id, sig))

    monkeypatch.setattr(crawler.trak_client, "tracker_set_qc", fake_set_qc)

    # Avoid xattr on files
    monkeypatch.setattr(crawler, "set_xattr", lambda path, value: None)

    # We don't care whether mark_missing_content is called or not in this test.
    monkeypatch.setattr(crawler, "mark_missing_content", lambda root_arg: 0)

    # Ensure we're in nightly/autonomous mode
    crawler.G_FORCED_RESULT = None
    crawler.G_NOTE = None

    # ------------------------------------------------------------
    # 3. Run the crawler
    # ------------------------------------------------------------
    rc = crawler.run(root=root, operator="rus", workers=1, min_seq=3, asset_id=None)
    assert rc == 0

    # ------------------------------------------------------------
    # 4. Assertions: sequences, singles, sidecars, Trak
    # ------------------------------------------------------------

    # We expect one QC event for the sequence (directory) and one for the single file
    assert len(set_qc_calls) == 2

    asset_ids = {aid for (aid, _sig) in set_qc_calls}
    # One asset per path, based on our fake_lookup
    assert any(aid.startswith("ASSET-shotA") for aid in asset_ids)
    assert any(aid.startswith("ASSET-clip.mxf") for aid in asset_ids)

    # Sidecars written: one for the sequence, one for the single
    assert len(written_sidecars) == 2

    # All signatures created should be pending
    assert made_signatures, "Expected at least one QC signature to be created"
    for sig in made_signatures:
        assert sig["qc_result"] == "pending"

    # And sidecars should have some content_state set ('new' or 'modified')
    for sc_path, sidecar_sig in written_sidecars.items():
        assert sidecar_sig.get("content_state") in {"new", "modified"}
