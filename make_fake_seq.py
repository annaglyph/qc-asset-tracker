#!/usr/bin/env python3
import argparse
from pathlib import Path


def infer_from_sample(sample: str):
    """
    Infer base, padding, and extension from a filename like:
    'conjuring-last-rites_tlr-f1_dcin_las.087469.tif'
    -> base='conjuring-last-rites_tlr-f1_dcin_las', pad=6, ext='tif'
    """
    p = Path(sample)
    name = p.name
    parts = name.split(".")
    if len(parts) < 3:
        raise ValueError("Sample must look like <base>.<frame>.<ext>")
    frame = parts[-2]
    ext = parts[-1]
    if not frame.isdigit():
        raise ValueError("Sample frame segment must be all digits")
    base = ".".join(parts[:-2])
    return base, len(frame), ext


def build_filename(base: str, frame: int, pad: int, ext: str):
    return f"{base}.{str(frame).zfill(pad)}.{ext}"


def make_sequence(
    out_dir: Path,
    base: str,
    start: int,
    end: int,
    pad: int,
    ext: str,
    step: int = 1,
    dry_run: bool = False,
    touch_existing: bool = False,
):
    out_dir.mkdir(parents=True, exist_ok=True)
    created, skipped = 0, 0
    for f in range(start, end + 1, step):
        fname = build_filename(base, f, pad, ext)
        path = out_dir / fname
        if dry_run:
            print("[DRY] ", path)
            continue
        if path.exists():
            if touch_existing:
                path.touch()  # update mtime
            skipped += 1
            continue
        # Create a 0-byte file
        path.touch()
        created += 1
    return created, skipped


def main():
    ap = argparse.ArgumentParser(description="Create zero-byte fake image sequences.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--like",
        help="Sample filename to infer base/padding/ext (e.g. batman_tlr-f1_dcin_las.087469.tif)",
    )
    g.add_argument("--base", help="Base name (e.g. batman_tlr-f1_dcin_las)")

    ap.add_argument(
        "--ext",
        default="tif",
        help="Extension without dot (default: tif). Ignored if --like used.",
    )
    ap.add_argument(
        "--pad",
        type=int,
        default=6,
        help="Frame padding width (default: 6). Ignored if --like used.",
    )
    ap.add_argument("--start", type=int, required=True, help="Start frame (inclusive)")
    ap.add_argument("--end", type=int, required=True, help="End frame (inclusive)")
    ap.add_argument("--step", type=int, default=1, help="Frame step (default: 1)")
    ap.add_argument(
        "--out", default=".", help="Output directory (default: current dir)"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Print what would be created"
    )
    ap.add_argument(
        "--touch-existing",
        action="store_true",
        help="If file exists, just update mtime (otherwise skip)",
    )

    args = ap.parse_args()

    if args.like:
        base, pad, ext = infer_from_sample(args.like)
    else:
        base, pad, ext = args.base, args.pad, args.ext

    created, skipped = make_sequence(
        out_dir=Path(args.out),
        base=base,
        start=args.start,
        end=args.end,
        pad=pad,
        ext=ext,
        step=args.step,
        dry_run=args.dry_run,
        touch_existing=args.touch_existing,
    )

    if not args.dry_run:
        print(f"Created: {created}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
