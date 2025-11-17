from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple


STATUS_ICONS: Mapping[str, str] = {
    "pass": "✅",
    "fail": "❌",
    "pending": "⏳",
}


def get_status(data: dict) -> str:
    """Normalise qc_result to a simple lowercase status string."""
    return (data.get("qc_result") or "pending").lower()


def find_sidecars(paths: Sequence[str]) -> List[Path]:
    """Yield sidecar paths from the given paths (files or dirs).

    - Files: treated as candidate sidecars if they end with '.qc.json' or 'sequence.qc.json'
      (or whatever your convention is, if you tweak this).
    - Dirs: scanned recursively for '*.qc.json'.
    """
    found: List[Path] = []

    for raw in paths:
        path = Path(raw)

        if path.is_file():
            if path.name.endswith(".qc.json"):
                found.append(path)
            else:
                print(
                    f"[WARN] File does not look like a sidecar (expected '*.qc.json'): {raw}",
                    file=sys.stderr,
                )
        elif path.is_dir():
            for sidecar in path.rglob("*.qc.json"):
                found.append(sidecar)
        else:
            print(f"[WARN] Not found or unsupported path: {raw}", file=sys.stderr)

    # De-duplicate and sort
    return sorted(set(found))


def load_json(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[ERROR] Failed to read {path}: {exc}", file=sys.stderr)
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Failed to parse JSON {path}: {exc}", file=sys.stderr)
        return None


def summarise_sidecar(data: dict, path: Path, max_note_len: int | None = 160) -> str:
    qc_result = get_status(data)
    operator = data.get("operator") or "Unknown"
    qc_time = data.get("qc_time") or "Unknown time"
    asset_path = data.get("asset_path") or str(path)
    asset_id = data.get("asset_id") or None
    policy_version = data.get("policy_version") or "n/a"
    tool_version = data.get("tool_version") or "n/a"
    note = (
        data.get("notes")
        or data.get("note")  # in case earlier schema used singular
        or ""
    )
    sequence = data.get("sequence") or None

    icon = STATUS_ICONS.get(qc_result, "❓")
    lines: List[str] = []

    # Header line
    lines.append(f"{icon} {qc_result.upper()} – {asset_path}")

    # Basic metadata
    lines.append(f"   Sidecar:      {path}")
    if asset_id:
        lines.append(f"   Trak asset:   {asset_id}")
    lines.append(f"   Operator:     {operator}")
    lines.append(f"   QC time:      {qc_time}")
    lines.append(f"   Policy/tool:  {policy_version} / {tool_version}")

    # Sequence info (if present)
    if sequence:
        base = sequence.get("base") or "<unknown>"
        ext = sequence.get("ext") or ""
        frame_min = sequence.get("frame_min")
        frame_max = sequence.get("frame_max")
        frame_count = sequence.get("frame_count")
        holes = sequence.get("holes")
        pad = sequence.get("pad")

        range_str_parts: List[str] = []
        if frame_min is not None and frame_max is not None:
            range_str_parts.append(f"{frame_min}–{frame_max}")
        if frame_count is not None:
            range_str_parts.append(f"{frame_count} frames")
        if holes is not None:
            range_str_parts.append(f"{holes} holes")
        if pad is not None:
            range_str_parts.append(f"pad={pad}")

        range_str = ", ".join(range_str_parts)

        lines.append("   Sequence:")
        lines.append(f"      {base}.{ext}  ({range_str})")

    # Note
    if note:
        if max_note_len is not None and len(note) > max_note_len:
            note = note[: max_note_len - 1].rstrip() + "…"
        lines.append(f"   Note:         {note}")

    return "\n".join(lines)


def choose_overall_status(counter: Counter) -> str:
    """Pick an overall status for a group of items.

    Priority: FAIL > PENDING > PASS > anything else.
    """
    if counter.get("fail"):
        return "fail"
    if counter.get("pending"):
        return "pending"
    if counter.get("pass"):
        return "pass"
    # Fall back to whatever we have
    return next(iter(counter.keys()), "pending")


def format_rollup(counter: Counter, prefix: str = "Summary: ") -> str:
    """Format a roll-up line like 'Summary: 4 items – 0 PASS, 1 FAIL, 3 PENDING'."""
    total = sum(counter.values())
    if not total:
        return prefix + "no items."

    parts: List[str] = []
    parts.append(f"{total} item{'s' if total != 1 else ''}")

    # Deterministic order for statuses
    order = ["pass", "fail", "pending"]
    others = [s for s in counter.keys() if s not in order]
    order.extend(sorted(others))

    detail_bits: List[str] = []
    for status in order:
        count = counter.get(status, 0)
        if not count:
            continue
        detail_bits.append(f"{count} {status.upper()}")

    if detail_bits:
        parts.append("– " + ", ".join(detail_bits))

    return prefix + " ".join(parts)


def group_key_for_sidecar(path: Path) -> Path:
    """Return the directory we consider the 'asset directory' for grouping.

    If the sidecar lives in a '.qc' dir, group by the parent of that dir.
    Otherwise, group by the sidecar's own parent directory.
    """
    parent = path.parent
    if parent.name == ".qc":
        return parent.parent
    return parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qc-summary",
        description=(
            "Print a human-readable summary of one or more QC sidecar JSON files. "
            "Pass files or directories; directories are scanned recursively "
            "for '*.qc.json' files."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Sidecar file(s) or directory/directories to scan for sidecars.",
    )
    parser.add_argument(
        "--max-note-len",
        type=int,
        default=160,
        help="Maximum length of note to show before truncating (default: 160, 0 = no limit).",
    )
    parser.add_argument(
        "--by-dir",
        "-d",
        action="store_true",
        help=(
            "Show a compact per-directory summary instead of one entry per sidecar. "
            "Directories are derived from the parent of the '.qc' folder."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    max_note_len: int | None
    if args.max_note_len <= 0:
        max_note_len = None
    else:
        max_note_len = args.max_note_len

    sidecars = find_sidecars(args.paths)
    if not sidecars:
        print("[INFO] No sidecars found.", file=sys.stderr)
        return 1

    # Overall status counter
    overall_counter: Counter = Counter()

    if not args.by_dir:
        # Full, per-sidecar output (current behaviour), plus a final roll-up line.
        for idx, path in enumerate(sidecars, start=1):
            data = load_json(path)
            if data is None:
                continue

            status = get_status(data)
            overall_counter[status] += 1

            if idx > 1:
                print()  # blank line between summaries

            print(summarise_sidecar(data, path, max_note_len=max_note_len))

    else:
        # Compact per-directory view.
        groups: Dict[Path, List[Tuple[Path, dict]]] = defaultdict(list)

        for path in sidecars:
            data = load_json(path)
            if data is None:
                continue
            status = get_status(data)
            overall_counter[status] += 1

            key = group_key_for_sidecar(path)
            groups[key].append((path, data))

        first = True
        for key in sorted(groups.keys(), key=lambda p: str(p).lower()):
            group_counter: Counter = Counter()
            representative_data: dict | None = None

            for path, data in groups[key]:
                status = get_status(data)
                group_counter[status] += 1
                if representative_data is None:
                    representative_data = data

            overall_status = choose_overall_status(group_counter)
            icon = STATUS_ICONS.get(overall_status, "❓")

            # Decide what to show as the header path
            if representative_data is not None:
                raw_asset_path = representative_data.get("asset_path")
            else:
                raw_asset_path = None

            if raw_asset_path:
                ap = Path(raw_asset_path)
                # Case 1: sequence-style, asset_path already points at the dir
                if ap.name == key.name:
                    display_path = raw_asset_path
                # Case 2: file-based, asset_path is a file inside the dir
                elif ap.parent.name == key.name:
                    display_path = str(ap.parent)
                else:
                    # Fallback: just show whatever we were given
                    display_path = raw_asset_path
            else:
                display_path = str(key)

            if not first:
                print()
            first = False

            print(f"{icon} {display_path}")
            rollup_line = format_rollup(group_counter, prefix="   ")
            print(rollup_line)

    # Final overall roll-up
    print()
    print(format_rollup(overall_counter))

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
