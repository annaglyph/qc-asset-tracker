from qc_asset_crawler.mutation import (
    SequenceMutationConfig,
    detect_sequence_mutation,
    summarize_frame_spans,
)


def test_no_previous_all_frames_treated_as_added_and_mutated():
    config = SequenceMutationConfig(
        threshold_frames=None,
        threshold_percent=None,
        count_removed_frames=False,
        treat_added_frames_as_mutation=True,
    )

    prev = None
    curr = {"0001": "a", "0002": "b"}

    result = detect_sequence_mutation(prev, curr, config)

    assert result.mutated is True
    assert result.changed_frames == []
    assert result.added_frames == ["0001", "0002"]
    assert result.removed_frames == []
    assert result.total_before == 0
    assert result.total_after == 2


def test_added_frames_do_not_auto_mutate_when_disabled():
    config = SequenceMutationConfig(
        threshold_frames=10,
        threshold_percent=None,
        count_removed_frames=False,
        treat_added_frames_as_mutation=False,
    )

    prev = {"0001": "a"}
    curr = {"0001": "a", "0002": "b"}  # one added frame

    result = detect_sequence_mutation(prev, curr, config)

    # Only one change, below threshold, and added frames not special.
    assert result.mutated is False
    assert result.added_frames == ["0002"]
    assert result.changed_frames == []
    assert result.removed_frames == []


def test_threshold_frames_triggers_mutation():
    config = SequenceMutationConfig(
        threshold_frames=2,
        threshold_percent=None,
        count_removed_frames=False,
        treat_added_frames_as_mutation=False,
    )

    prev = {"0001": "a", "0002": "b", "0003": "c"}
    curr = {"0001": "x", "0002": "y", "0003": "c"}  # two changed frames

    result = detect_sequence_mutation(prev, curr, config)

    assert result.mutated is True
    assert result.changed_frames == ["0001", "0002"]
    assert result.added_frames == []
    assert result.removed_frames == []


def test_percentage_threshold_triggers_mutation():
    config = SequenceMutationConfig(
        threshold_frames=None,
        threshold_percent=10.0,
        count_removed_frames=False,
        treat_added_frames_as_mutation=False,
    )

    # 10 frames, 2 changed -> 20% changed
    prev = {f"{i:04d}": "a" for i in range(1, 11)}
    curr = prev.copy()
    curr["0003"] = "b"
    curr["0007"] = "c"

    result = detect_sequence_mutation(prev, curr, config)

    assert result.mutated is True
    assert result.changed_frames == ["0003", "0007"]


def test_removed_frames_ignored_by_default():
    config = SequenceMutationConfig(
        threshold_frames=None,
        threshold_percent=None,
        count_removed_frames=False,
        treat_added_frames_as_mutation=False,
    )

    prev = {"0001": "a", "0002": "b"}
    curr = {"0001": "a"}  # one removed frame

    result = detect_sequence_mutation(prev, curr, config)

    assert result.mutated is False
    assert result.added_frames == []
    assert result.changed_frames == []
    assert result.removed_frames == ["0002"]


def test_removed_frames_counted_when_enabled():
    config = SequenceMutationConfig(
        threshold_frames=1,
        threshold_percent=None,
        count_removed_frames=True,
        treat_added_frames_as_mutation=False,
    )

    prev = {"0001": "a", "0002": "b"}
    curr = {"0001": "a"}  # one removed frame

    result = detect_sequence_mutation(prev, curr, config)

    assert result.mutated is True
    assert result.removed_frames == ["0002"]


def test_summarize_frame_spans_basic_ranges():
    frames = ["0001", "0002", "0003", "0005", "0007", "0008"]
    summary = summarize_frame_spans(frames)
    assert summary == "0001–0003, 0005, 0007–0008"


def test_summarize_frame_spans_handles_non_numeric():
    frames = ["0001", "A", "0002", "0003"]
    summary = summarize_frame_spans(frames)
    # "A" breaks numeric contiguity and is treated as its own span.
    assert summary == "0001, A, 0002–0003"


def test_summarize_frame_spans_empty():
    assert summarize_frame_spans([]) == ""
