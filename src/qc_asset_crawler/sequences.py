from __future__ import annotations

import os
import re
from pathlib import Path
from collections.abc import Iterable

# Media handling
MEDIA_EXTS = {
    ".mxf",
    ".wav",
    ".aif",
    ".aiff",
    ".mov",
    ".mp4",
    ".exr",
    ".dpx",
    ".tif",
    ".tiff",
    ".jpg",
    ".png",
}

SEQ_EXTS = {".exr", ".dpx", ".tif", ".tiff", ".jpg", ".png"}

# filename pattern:
#   base + frame + "." + ext
# e.g. conjuring-last-rites_tlr-f1_dcin_las.087469.tif
_seq_re = re.compile(r"^(?P<base>.*?)(?P<frame>\d+)(?P<dot>\.)(?P<ext>[^.]+)$")


def is_sequence_candidate(p: Path) -> bool:
    """Return True if path *could* be part of an image sequence."""
    return p.suffix.lower() in SEQ_EXTS


def iter_media(root: Path) -> Iterable[Path]:
    """
    Walk root recursively, yielding files that look like media
    based on extension, skipping hidden dirs/files.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        # skip hidden directories
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if f.startswith("."):
                continue
            p = Path(dirpath) / f
            if p.suffix.lower() in MEDIA_EXTS:
                yield p


def seq_key(p: Path):
    """
    Grouping key for sequences:
    (parent directory, base, extension) or None if not a frame.
    """
    m = _seq_re.match(p.name)
    if not m:
        return None
    return (p.parent, m.group("base"), m.group("ext"))


def group_sequences(files: Iterable[Path], min_seq: int = 3):
    """
    Split files into:

      - sequences: {(dir, base, ext): [frames...]}
      - singles: [paths not in a long-enough sequence]

    A 'sequence' must have at least `min_seq` frames.
    """
    groups: dict[tuple[Path, str, str], list[Path]] = {}
    singles: list[Path] = []

    # First pass: try to group all sequence-capable files
    for p in files:
        if is_sequence_candidate(p):
            k = seq_key(p)
            if k:
                groups.setdefault(k, []).append(p)
                continue
        singles.append(p)

    # Keep only groups with >= min_seq frames
    sequences = {k: sorted(v) for k, v in groups.items() if len(v) >= min_seq}
    seq_members = {p for vs in sequences.values() for p in vs}

    # Any file not in a sequence (or already in singles) is a single
    singles.extend([p for p in files if p not in seq_members and p not in singles])

    return sequences, singles


def summarize_frames(file_names: list[str]) -> dict[str, int] | None:
    """
    Summarise frame range, holes, and padding from a list of filenames
    that follow the pattern base.frame.ext.
    """
    frames: list[int] = []
    pad: int | None = None

    for n in file_names:
        m = _seq_re.match(n)
        if not m:
            continue
        s = m.group("frame")
        frames.append(int(s))
        pad = pad or len(s)

    if not frames:
        return None

    frames.sort()
    pad = pad or 0

    ranges = 0
    holes = 0
    prev = frames[0]

    for f in frames[1:]:
        if f == prev + 1:
            prev = f
        else:
            ranges += 1
            holes += f - prev - 1
            prev = f

    ranges += 1  # last range

    return {
        "frame_min": frames[0],
        "frame_max": frames[-1],
        "pad": pad,
        "frame_count": len(frames),
        "range_count": ranges,
        "holes": holes,
    }
