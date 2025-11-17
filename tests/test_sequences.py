from __future__ import annotations

from pathlib import Path

from qc_asset_crawler import sequences


def test_is_sequence_candidate_respects_exts() -> None:
    assert sequences.is_sequence_candidate(Path("frame.0001.exr")) is True
    assert sequences.is_sequence_candidate(Path("frame.0001.dpx")) is True
    assert sequences.is_sequence_candidate(Path("frame.0001.tif")) is True

    # Non-image media extensions should NOT be treated as sequence candidates
    assert sequences.is_sequence_candidate(Path("clip.mxf")) is False
    assert sequences.is_sequence_candidate(Path("audio.wav")) is False
    assert sequences.is_sequence_candidate(Path("movie.mov")) is False


def test_seq_key_matches_frame_pattern() -> None:
    p = Path("/show/plates") / "shotA.000123.exr"
    key = sequences.seq_key(p)
    assert key is not None
    parent, base, ext = key
    assert parent == p.parent
    # Base should be everything before the frame number; we don't care exactly,
    # only that the extension is extracted correctly.
    assert ext == "exr"

    # Non-matching name should return None
    assert sequences.seq_key(Path("/show/plates/not_a_frame.exr")) is None
    assert sequences.seq_key(Path("/show/plates/.hidden")) is None


def test_group_sequences_basic(make_fake_sequence_tree, tmp_path: Path) -> None:
    # Create a simple sequence and a non-sequence single
    root, frames = make_fake_sequence_tree(
        base="plates01",
        ext="tif",
        count=10,
        pad=4,
        start=1,
    )

    single = root / "single.mov"
    single.write_text("dummy", encoding="utf-8")

    all_files = frames + [single]

    sequences_map, singles = sequences.group_sequences(all_files, min_seq=3)

    # One sequence group
    assert len(sequences_map) == 1
    (key,) = sequences_map.keys()
    parent, base, ext = key
    assert parent == root
    assert ext == "tif"

    seq_files = sequences_map[key]
    assert sorted(seq_files) == sorted(frames)

    # Single non-sequence file should be in singles
    assert single in singles
    # No sequence frames should appear in singles
    for f in frames:
        assert f not in singles


def test_group_sequences_respects_min_seq(make_fake_sequence_tree) -> None:
    # Only 3 frames; with min_seq=5 this should NOT form a sequence group
    root, frames = make_fake_sequence_tree(
        base="short_seq",
        ext="exr",
        count=3,
        pad=4,
        start=1,
    )

    sequences_map, singles = sequences.group_sequences(frames, min_seq=5)

    # No sequences; all frames should be singles
    assert sequences_map == {}
    assert sorted(singles) == sorted(frames)


def test_summarize_frames_contiguous_range() -> None:
    names = [
        "shotA.0001.exr",
        "shotA.0002.exr",
        "shotA.0003.exr",
    ]
    info = sequences.summarize_frames(names)
    assert info is not None

    assert info["frame_min"] == 1
    assert info["frame_max"] == 3
    assert info["frame_count"] == 3
    assert info["pad"] == 4
    assert info["range_count"] == 1
    assert info["holes"] == 0


def test_summarize_frames_with_holes_and_multiple_ranges() -> None:
    # Two ranges with a gap: 1001-1004 and 1007-1010
    names = [
        "shotA.01001.dpx",
        "shotA.01002.dpx",
        "shotA.01003.dpx",
        "shotA.01004.dpx",
        "shotA.01007.dpx",
        "shotA.01008.dpx",
        "shotA.01009.dpx",
        "shotA.01010.dpx",
    ]
    info = sequences.summarize_frames(names)
    assert info is not None

    assert info["frame_min"] == 1001
    assert info["frame_max"] == 1010
    # 8 physical frames
    assert info["frame_count"] == 8
    # Pad inferred from "01001" -> 5 digits
    assert info["pad"] == 5
    # One gap between 1004 and 1007 -> 2 holes (1005, 1006)
    assert info["holes"] == 2
    # 2 contiguous ranges (1001–1004, 1007–1010)
    assert info["range_count"] == 2


def test_summarize_frames_ignores_non_matching_names() -> None:
    # No names match the base.frame.ext pattern -> should return None
    names = ["not_a_frame.mov", "another_file.exr"]  # second one missing frame number
    info = sequences.summarize_frames(names)
    assert info is None


def test_group_sequences_and_summarize_integration(make_fake_sequence_tree) -> None:
    """
    End-to-end style test:
    - create a sequence with a hole
    - group_sequences finds the sequence group
    - summarize_frames correctly reports min/max/holes/etc.
    """
    root, frames = make_fake_sequence_tree(
        base="shotA",
        ext="exr",
        count=12,
        pad=4,
        start=1001,
        holes=[1005, 1006],
    )
    # frames on disk correspond to all numbers except 1005 and 1006

    # Group into sequences
    seq_map, singles = sequences.group_sequences(frames, min_seq=3)
    assert not singles
    assert len(seq_map) == 1

    (key,) = seq_map.keys()
    seq_files = seq_map[key]

    # Run summarize_frames on the *filenames* in that group
    names = [p.name for p in seq_files]
    info = sequences.summarize_frames(names)
    assert info is not None

    assert info["frame_min"] == 1001
    assert info["frame_max"] == 1012
    # 12 total possible frame numbers, 2 missing -> 10 physical frames
    assert info["frame_count"] == 10
    # Two missing frames 1005, 1006 -> 2 holes
    assert info["holes"] == 2
    # Two contiguous ranges: 1001–1004 and 1007–1012
    assert info["range_count"] == 2
    # Padding from filenames, e.g. "1001" -> 4 digits
    assert info["pad"] == 4
