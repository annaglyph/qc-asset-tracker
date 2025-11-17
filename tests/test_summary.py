from __future__ import annotations

import json
from pathlib import Path

import pytest

from qc_asset_crawler import summary


def test_summarise_sidecar_sequence_basic(
    tmp_path: Path,
    make_sidecar,
) -> None:
    sidecar_path = tmp_path / ".qc" / "sequence.qc.json"
    # make_sidecar will create parent dirs for us
    seq = {
        "base": "ann_lee_r2_german",
        "ext": "tif",
        "frame_min": 177267,
        "frame_max": 198920,
        "frame_count": 1033,
        "holes": 20621,
        "pad": 6,
    }
    make_sidecar(
        sidecar_path,
        qc_result="pending",
        asset_path="/jobs/ann_lee/vfx/renders/feature/german/r2/dcin/xyz/2d/inserts/mono/4096x1716",
        sequence=seq,
        notes="Looks good",
    )

    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    text = summary.summarise_sidecar(data, sidecar_path, max_note_len=160)

    lines = text.splitlines()

    # Header line
    assert lines[0].startswith(
        "⏳ PENDING – /jobs/ann_lee/vfx/renders/feature/german/r2/dcin/xyz/2d/inserts/mono/4096x1716"
    )

    # Sidecar path line
    assert f"Sidecar:      {sidecar_path}" in text

    # Sequence line includes frame range, count, holes, pad
    assert "ann_lee_r2_german.tif" in text
    assert "(177267–198920, 1033 frames, 20621 holes, pad=6)" in text

    # Note appears and is not truncated
    assert "Note:         Looks good" in text


def test_summarise_sidecar_truncates_long_note(
    tmp_path: Path,
    make_sidecar,
) -> None:
    sidecar_path = tmp_path / "file.exr.qc.json"
    long_note = "x" * 500

    make_sidecar(sidecar_path, qc_result="pass", notes=long_note)

    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    text = summary.summarise_sidecar(data, sidecar_path, max_note_len=40)

    assert "✅ PASS –" in text

    # Truncated with ellipsis
    note_lines = [
        line for line in text.splitlines() if line.strip().startswith("Note:")
    ]
    assert note_lines, "Expected a Note line in the summary output"
    note_line = note_lines[0]
    assert note_line.endswith("…")
    assert len(note_line) < 80  # sanity check it's actually shorter


def test_find_sidecars_from_dir_and_file(tmp_path: Path) -> None:
    # Layout:
    #   root/
    #     a.exr.qc.json
    #     ignore.txt
    #     sub/.qc/b.exr.qc.json
    root = tmp_path

    inline = root / "a.exr.qc.json"
    inline.write_text("{}", encoding="utf-8")

    ignore = root / "ignore.txt"
    ignore.write_text("not json", encoding="utf-8")

    sub_qc = root / "sub" / ".qc"
    sub_qc.mkdir(parents=True, exist_ok=True)
    sub_sidecar = sub_qc / "b.exr.qc.json"
    sub_sidecar.write_text("{}", encoding="utf-8")

    result = summary.find_sidecars([str(root), str(inline)])

    # Should find both sidecars exactly once
    assert set(result) == {inline, sub_sidecar}


def test_main_default_mode_with_rollup(
    tmp_path: Path,
    make_sidecar,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Create two sidecars with different statuses
    qc_dir = tmp_path / ".qc"
    qc_dir.mkdir(parents=True, exist_ok=True)

    sc1 = qc_dir / "a.mxf.qc.json"
    sc2 = qc_dir / "b.mxf.qc.json"

    make_sidecar(sc1, qc_result="pass")
    make_sidecar(sc2, qc_result="fail")

    code = summary.main([str(tmp_path)])
    assert code == 0

    captured = capsys.readouterr()
    out = captured.out

    # We should have one PASS and one FAIL block
    assert "✅ PASS –" in out
    assert "❌ FAIL –" in out

    # Final roll-up line
    assert "Summary:" in out
    assert "2 items" in out
    assert "1 PASS" in out
    assert "1 FAIL" in out


def test_main_by_dir_grouping_and_rollup(
    tmp_path: Path,
    make_sidecar,
    normalise_output,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Layout:
    #   root/
    #     shot_a/.qc/a.mxf.qc.json  (pass)
    #     shot_b/.qc/b1.mxf.qc.json (pending)
    #     shot_b/.qc/b2.mxf.qc.json (fail)
    shot_a = tmp_path / "shot_a" / ".qc"
    shot_b = tmp_path / "shot_b" / ".qc"
    shot_a.mkdir(parents=True, exist_ok=True)
    shot_b.mkdir(parents=True, exist_ok=True)

    make_sidecar(
        shot_a / "a.mxf.qc.json",
        qc_result="pass",
        asset_path="/SAN/show/shot_a/file.mxf",
    )
    make_sidecar(
        shot_b / "b1.mxf.qc.json",
        qc_result="pending",
        asset_path="/SAN/show/shot_b/file1.mxf",
    )
    make_sidecar(
        shot_b / "b2.mxf.qc.json",
        qc_result="fail",
        asset_path="/SAN/show/shot_b/file2.mxf",
    )

    code = summary.main(["--by-dir", str(tmp_path)])
    assert code == 0

    captured = capsys.readouterr()
    out = normalise_output(captured.out)

    # shot_a group: all PASS -> header icon should be ✅
    assert "✅ /SAN/show/shot_a" in out
    assert "1 item – 1 PASS" in out

    # shot_b group: contains FAIL -> header icon should be ❌ and summarise counts
    assert "❌ /SAN/show/shot_b" in out
    assert "2 items – 1 FAIL" in out
    assert "1 PENDING" in out

    # Overall roll-up at the end
    assert "Summary:" in out
    assert "3 items – 1 PASS" in out
    assert "1 FAIL" in out
    assert "1 PENDING" in out


def test_main_no_sidecars_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Empty directory: no sidecars should be found
    code = summary.main([str(tmp_path)])
    assert code == 1

    captured = capsys.readouterr()
    # Message goes to stderr
    assert "[INFO] No sidecars found." in captured.err


def test_find_sidecars_warns_on_non_sidecar_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A file that doesn't look like a sidecar should trigger a warning
    non_sidecar = tmp_path / "not_a_sidecar.txt"
    non_sidecar.write_text("hello", encoding="utf-8")

    result = summary.find_sidecars([str(non_sidecar)])

    assert result == []
    captured = capsys.readouterr()
    assert "File does not look like a sidecar" in captured.err
    assert str(non_sidecar) in captured.err
