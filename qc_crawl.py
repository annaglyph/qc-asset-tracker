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
import json
import logging
import os
import sys
from datetime import datetime, timezone

import dotenv
from pathlib import Path
from qc_asset_crawler import crawler, sidecar
from qc_asset_crawler.mutation import SequenceMutationConfig

try:
    # Optional: nicer colours on Windows
    import colorama

    colorama.init()
except Exception:
    colorama = None


def find_data_file(filename: str) -> str:
    if getattr(sys, "frozen", False):
        datadir = os.path.dirname(sys.executable)
    else:
        datadir = os.path.dirname(__file__)
    return os.path.join(datadir, filename)


dotenv.load_dotenv(find_data_file(".env"))


# ----------------- Logging helpers -----------------


class IgnoreEmptyMessageFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return bool(record.getMessage().strip())


class ColourFormatter(logging.Formatter):
    """
    Simple ANSI colour formatter for console logs.

    Colours:
      DEBUG   -> cyan
      INFO    -> green
      WARNING -> yellow
      ERROR   -> red
      CRITICAL-> red background
    """

    COLOURS = {
        logging.DEBUG: "\033[96m",  # bright cyan
        logging.INFO: "\033[92m",  # bright green
        logging.WARNING: "\033[93m",  # bright yellow
        logging.ERROR: "\033[91m",  # bright red
        logging.CRITICAL: "\033[41m",  # red background
    }

    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        colour = self.COLOURS.get(record.levelno)
        if not colour:
            return base
        return f"{colour}{base}{self.RESET}"


class JsonFormatter(logging.Formatter):
    """
    Emit one JSON object per log line, suitable for ingestion by log tools.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    level_name: str,
    *,
    quiet: bool = False,
    json_logs: bool = False,
) -> None:
    """
    Configure global logging.

    Args
    ----
    level_name:
        Base log level name from CLI (--log), e.g. "INFO", "DEBUG".
    quiet:
        If True, bump the level to WARNING for console output.
    json_logs:
        If True, emit machine-readable JSON log lines instead of coloured text.
    """
    # Clear any existing handlers (important if main() is called more than once)
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    level = getattr(logging, level_name.upper(), logging.INFO)
    if quiet and level < logging.WARNING:
        level = logging.WARNING

    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)

    if json_logs:
        fmt: logging.Formatter = JsonFormatter()
    else:
        # Use ANSI colours for human-readable console logs
        fmt = ColourFormatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        fmt.datefmt = "%Y-%m-%d %H:%M:%S"

    handler.addFilter(IgnoreEmptyMessageFilter())

    handler.setFormatter(fmt)
    root.addHandler(handler)

    # Reduce noise from common libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


# ----------------- CLI -----------------


def main() -> int:
    ap = argparse.ArgumentParser(description="QC marker for media on a SAN.")
    ap.add_argument(
        "root",
        nargs="+",
        help="Root path(s) to crawl. Provide one or more paths.",
    )
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
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    ap.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce log output (at least WARNING, regardless of --log).",
    )
    ap.add_argument(
        "--json-logs",
        action="store_true",
        help="Emit machine-readable JSON log lines instead of human-readable text.",
    )
    ap.add_argument(
        "--min-seq",
        type=int,
        default=3,
        help="Minimum files to treat as a sequence",
    )
    ap.add_argument(
        "--asset-id",
        dest="asset_ids",
        action="append",
        help=(
            "Optional Trak asset_id(s). "
            "If specified once, it is applied to all roots. "
            "If specified multiple times, the number of values must match "
            "the number of roots."
        ),
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
    ap.add_argument(
        "--enable-mutation-detection",
        action="store_true",
        help="Enable sequence-level partial-frame mutation detection.",
    )
    ap.add_argument(
        "--mutation-threshold-frames",
        type=int,
        default=None,
        help="Trigger mutation if N or more frames changed.",
    )
    ap.add_argument(
        "--mutation-threshold-percent",
        type=float,
        default=None,
        help="Trigger mutation if >= P percent of frames changed.",
    )
    ap.add_argument(
        "--mutation-count-removed",
        action="store_true",
        help="Count removed frames as mutations.",
    )
    ap.add_argument(
        "--show-diff",
        action="store_true",
        help="If mutation detected, show frame change ranges.",
    )
    args = ap.parse_args()

    # Initialise logging using module-level configure_logging (no nested def!)
    configure_logging(
        level_name=args.log,
        quiet=args.quiet,
        json_logs=args.json_logs,
    )

    # Set the globals in the crawler module
    crawler.G_SIDECAR_MODE = args.sidecar_mode
    crawler.G_FORCED_RESULT = args.result
    crawler.G_NOTE = args.note

    if args.enable_mutation_detection:
        crawler.G_MUTATION_CONFIG = SequenceMutationConfig(
            threshold_frames=args.mutation_threshold_frames or 1,
            threshold_percent=args.mutation_threshold_percent,
            count_removed_frames=args.mutation_count_removed,
            treat_added_frames_as_mutation=True,
        )
    else:
        crawler.G_MUTATION_CONFIG = None

    crawler.G_SHOW_MUTATION_DIFF = args.show_diff

    # keep sidecar module in sync so it knows where to write
    sidecar.G_SIDECAR_MODE = args.sidecar_mode

    roots = [Path(r).resolve() for r in args.root]
    asset_ids = args.asset_ids  # may be None or a list of strings

    # Delegate to the multi-root runner. It gracefully handles:
    # - single root + no asset_ids
    # - single root + one asset_id
    # - multi-root + one asset_id (reused for all roots)
    # - multi-root + N asset_ids (must match number of roots)
    return crawler.run_many(
        roots=roots,
        operator=args.operator,
        workers=args.workers,
        min_seq=args.min_seq,
        asset_ids=asset_ids,
    )


if __name__ == "__main__":
    raise SystemExit(main())
