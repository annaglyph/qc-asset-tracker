from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass
class SequenceMutationConfig:
    """Configuration for detecting mutations within a sequence of frames."""

    # Minimum number of changed frames to trigger a mutation.
    # None means "do not consider absolute frame count".
    threshold_frames: int | None = None

    # Minimum percentage (0–100) of frames changed to trigger a mutation.
    # None means "do not consider percentage threshold".
    threshold_percent: float | None = None

    # Whether removed frames should count towards the change threshold.
    count_removed_frames: bool = False

    # Whether the presence of any added frames should *always* be a mutation.
    treat_added_frames_as_mutation: bool = True

    def __post_init__(self) -> None:
        if self.threshold_frames is not None and self.threshold_frames < 0:
            raise ValueError("threshold_frames must be >= 0 or None")
        if self.threshold_percent is not None and self.threshold_percent < 0:
            raise ValueError("threshold_percent must be >= 0 or None")


@dataclass
class SequenceMutationResult:
    """Outcome of comparing previous and current frame states for a sequence."""

    changed_frames: list[str]
    added_frames: list[str]
    removed_frames: list[str]
    total_before: int
    total_after: int
    mutated: bool

    @property
    def total_changes(self) -> int:
        return (
            len(self.changed_frames) + len(self.added_frames) + len(self.removed_frames)
        )


def detect_sequence_mutation(
    previous_hashes: Mapping[str, str] | None,
    current_hashes: Mapping[str, str],
    config: SequenceMutationConfig,
) -> SequenceMutationResult:
    """Compare previous and current frame hashes and decide if a mutation occurred.

    Parameters
    ----------
    previous_hashes:
        Mapping of frame identifier -> content hash from a previous QC run.
        May be None if no prior state exists.
    current_hashes:
        Mapping of frame identifier -> current content hash.
    config:
        Thresholds and behavioural flags that control mutation detection.

    Returns
    -------
    SequenceMutationResult
        Lists of changed/added/removed frames and a boolean flag indicating
        whether the sequence should be treated as mutated.
    """
    prev = dict(previous_hashes or {})
    curr = dict(current_hashes)

    prev_keys = set(prev)
    curr_keys = set(curr)

    added = sorted(curr_keys - prev_keys)
    removed = sorted(prev_keys - curr_keys)
    common = prev_keys & curr_keys

    changed = sorted(k for k in common if prev[k] != curr[k])

    total_before = len(prev_keys)
    total_after = len(curr_keys)

    # How many changes should be counted toward thresholds?
    threshold_changes = len(changed) + len(added)
    if config.count_removed_frames:
        threshold_changes += len(removed)

    baseline = max(total_before, total_after)

    mutated = False

    # 1) Added frames are always a mutation if configured so.
    if config.treat_added_frames_as_mutation and added:
        mutated = True

    # 2) Absolute frame-count threshold.
    if not mutated and config.threshold_frames is not None:
        if threshold_changes >= config.threshold_frames:
            mutated = True

    # 3) Percentage threshold.
    if not mutated and config.threshold_percent is not None and baseline > 0:
        percent = (threshold_changes / baseline) * 100.0
        if percent >= config.threshold_percent:
            mutated = True

    return SequenceMutationResult(
        changed_frames=changed,
        added_frames=added,
        removed_frames=removed,
        total_before=total_before,
        total_after=total_after,
        mutated=mutated,
    )


def summarize_frame_spans(frame_ids: Sequence[str]) -> str:
    """Summarise a list of frame identifiers into compact span notation.

    The input is expected to be sorted in ascending order so that lexicographic
    order also reflects numeric order (for example zero-padded numbers like
    "0001", "0002", ...).

    Example
    -------
    >>> summarize_frame_spans(["0001", "0002", "0003", "0010"])
    '0001–0003, 0010'
    """
    if not frame_ids:
        return ""

    # Convert to numeric for contiguity checks but keep original strings.
    parsed: list[tuple[int | None, str]] = []
    for fid in frame_ids:
        try:
            n = int(fid)
        except ValueError:
            n = None
        parsed.append((n, fid))

    spans: list[str] = []
    i = 0

    while i < len(parsed):
        n, label = parsed[i]

        # Non-numeric identifiers: each gets its own span.
        if n is None:
            spans.append(label)
            i += 1
            continue

        # Start a numeric span.
        start_label = label
        end_label = label
        last_n = n

        j = i + 1
        while j < len(parsed):
            n2, label2 = parsed[j]
            if n2 is None or n2 != last_n + 1:
                break
            end_label = label2
            last_n = n2
            j += 1

        if start_label == end_label:
            spans.append(start_label)
        else:
            spans.append(f"{start_label}–{end_label}")

        i = j

    return ", ".join(spans)
