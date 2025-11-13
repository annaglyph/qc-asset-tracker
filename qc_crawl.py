#!/usr/bin/env python3
"""
qc-asset-crawler
- Requests-based tracker calls
- Image-sequence aware (gappy sequences OK)
- Fast re-runs via cheap fingerprint + optional hash cache
- Small qc.sidecars with manifest hash (no giant manifests)
- Consistent JSON schema + validation
"""
import argparse
import logging
import os
import sys
import dotenv
from pathlib import Path
from qc_asset_crawler import crawler


def find_data_file(filename):
    if getattr(sys, "frozen", False):
        datadir = os.path.dirname(sys.executable)
    else:
        datadir = os.path.dirname(__file__)
    return os.path.join(datadir, filename)


dotenv.load_dotenv(find_data_file(".env"))


# ----------------- CLI -----------------
def main():
    ap = argparse.ArgumentParser(description="QC marker for media on a SAN.")
    ap.add_argument("root", help="Root path to crawl")
    ap.add_argument(
        "--operator",
        default=os.environ.get("USER") or os.environ.get("USERNAME") or "system",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=max(os.cpu_count() or 4, 4),
    )
    ap.add_argument(
        "--log",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    ap.add_argument(
        "--min-seq",
        type=int,
        default=3,
        help="Minimum files to treat as a sequence",
    )
    ap.add_argument(
        "--sidecar-mode",
        choices=["inline", "dot", "subdir"],
        default="subdir",
        help=(
            "Where/how to store sidecars: inline, dot, or subdir (.qc/). "
            "Default: subdir"
        ),
    )
    ap.add_argument(
        "--result",
        choices=["pass", "fail", "pending"],
        help="Force QC result override for all assets processed",
    )
    ap.add_argument(
        "--note",
        help="Optional operator note to store in the sidecar",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log.upper(), logging.DEBUG),
        format="%(levelname)s %(message)s",
    )

    # Set the globals in the crawler module
    crawler.G_SIDECAR_MODE = args.sidecar_mode
    crawler.G_FORCED_RESULT = args.result
    crawler.G_NOTE = args.note

    root = Path(args.root).resolve()
    return crawler.run(
        root=root,
        operator=args.operator,
        workers=args.workers,
        min_seq=args.min_seq,
    )


if __name__ == "__main__":
    raise SystemExit(main())
