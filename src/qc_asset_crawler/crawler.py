from __future__ import annotations

import concurrent.futures
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from qc_asset_crawler.sequences import (
    iter_media,
    group_sequences,
    summarize_frames,
)
from qc_asset_crawler import hashing, trak_client, sidecar, hashcache, qcstate, config


# Globals set from CLI
G_SIDECAR_MODE: str = "subdir"
G_FORCED_RESULT: Optional[str] = None
G_NOTE: Optional[str] = None


# ----------------- Helpers -----------------
def normalize_base_ext(base: str, ext: str) -> Tuple[str, str]:
    # base: strip trailing '.' ; ext: strip leading '.'
    return base[:-1] if base.endswith(".") else base, (
        ext[1:] if ext.startswith(".") else ext
    )


def safe_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return path.as_posix()


def set_xattr(path: Path, value: str) -> None:
    try:
        if sys.platform.startswith("linux"):
            os.setxattr(path.as_posix(), config.get_xattr_key(), value.encode("utf-8"))
        elif sys.platform == "darwin":
            import xattr

            xattr.setxattr(
                path.as_posix(), config.get_xattr_key(), value.encode("utf-8")
            )
    except Exception:
        pass


# ----------------- Processing -----------------
def process_single_file(
    p: Path,
    operator: str,
    asset_id: Optional[str] = None,
):
    sc = sidecar.sidecar_path_for_file(p)
    existing = sidecar.read_sidecar(sc)
    ch = hashing.blake3_or_sha256_file(p)
    if not sidecar.needs_reqc(existing, ch):
        return ("skip", p)
    # prefer explicit asset_id from CLI, otherwise fall back to Trak lookup
    lookup = {}
    effective_asset_id = asset_id  # function parameter

    if not effective_asset_id:
        lookup = trak_client.tracker_lookup_asset_by_path(p)
        effective_asset_id = lookup.get("asset_id")

    result = G_FORCED_RESULT or ("pass" if effective_asset_id else "pending")

    sig = qcstate.make_qc_signature(
        p,
        ch,
        effective_asset_id,
        operator,
        result=result,
        note=G_NOTE,
    )

    if result == "pending":
        sig["tracker_status"] = {k: lookup.get(k) for k in ("status", "http_code")}
    sidecar.write_sidecar(sc, sig)
    set_xattr(p, sig["qc_id"])
    trak_client.tracker_set_qc(asset_id, sig)
    return ("marked", p)


def process_sequence(
    dir_path: Path,
    base: str,
    ext: str,
    files: List[Path],
    operator: str,
    asset_id: Optional[str] = None,
):
    sc = sidecar.sequence_sidecar_path(dir_path)
    cache = hashcache.load_hashcache(dir_path)

    # Reuse cheap fingerprint to avoid rehashing needlessly
    cheap_fp = hashing.cheap_fingerprint(files)
    existing = sidecar.read_sidecar(sc)

    # If cheap fingerprint hasn't changed and policy unchanged, we can skip deep hashing & QC
    if existing and existing.get("policy_version") == sidecar.get_qc_policy_version():
        seq = existing.get("sequence", {})
        if seq.get("cheap_fp") == cheap_fp:
            return ("skip", dir_path / f"{base}*.{ext}")

    # Deep hashing with cache
    seq_hash = hashing.manifest_hash_for_files(files, cache)
    hashcache.save_hashcache(dir_path, cache)
    if existing and not sidecar.needs_reqc(existing, seq_hash):
        # But update cheap_fp if missing
        if existing.get("sequence", {}).get("cheap_fp") != cheap_fp:
            existing.setdefault("sequence", {})["cheap_fp"] = cheap_fp
            sidecar.write_sidecar(sc, existing)
        return ("skip", dir_path / f"{base}*.{ext}")

    # Normalize base/ext for storage
    nbase, next_ = normalize_base_ext(base, ext)

    # Decide which asset_id to use:
    #  - prefer explicit asset_id from CLI
    #  - otherwise fall back to Trak lookup (dir, then first file)
    effective_asset_id = asset_id
    lookup_used = None

    if not effective_asset_id:
        # Try the directory path first
        lookup_dir = trak_client.tracker_lookup_asset_by_path(dir_path)
        effective_asset_id = lookup_dir.get("asset_id")
        lookup_used = lookup_dir

        # If that failed, try the first file in the sequence
        if not effective_asset_id and files:
            lookup_file = trak_client.tracker_lookup_asset_by_path(files[0])
            effective_asset_id = lookup_file.get("asset_id")
            lookup_used = lookup_file

    result = G_FORCED_RESULT or ("pass" if effective_asset_id else "pending")

    sig = qcstate.make_qc_signature(
        dir_path,
        seq_hash,
        effective_asset_id,
        operator,
        result=result,
        note=G_NOTE,
    )

    # Lightweight sequence summary
    names = [p.name for p in files]
    summary = summarize_frames(names) or {}
    sig["sequence"] = {
        "base": nbase,
        "ext": next_,
        "first": names[0],
        "last": names[-1],
        "frame_count": len(names),
        **summary,
        "cheap_fp": cheap_fp,
    }

    if result == "pending":
        sig["tracker_status"] = {k: lookup_used.get(k) for k in ("status", "http_code")}
    sidecar.write_sidecar(sc, sig)

    try:
        set_xattr(dir_path, sig["qc_id"])
    except Exception:
        pass

    trak_client.tracker_set_qc(asset_id, sig)
    return ("marked", dir_path / f"{nbase}*.{next_}")


def run(
    root: Path,
    operator: str,
    workers: int,
    min_seq: int,
    asset_id: Optional[str] = None,
) -> int:
    files = list(iter_media(root))
    sequences_map, singles = group_sequences(files, min_seq=min_seq)
    logging.info("Found %d sequences and %d singles", len(sequences_map), len(singles))

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [
            ex.submit(
                process_sequence,
                d,
                base,
                ext,
                members,
                operator,
                asset_id,
            )
            for (d, base, ext), members in sequences_map.items()
        ]
        futs += [
            ex.submit(
                process_single_file,
                p,
                operator,
                asset_id,
            )
            for p in singles
        ]
        for f in concurrent.futures.as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:
                logging.error("Worker error: %s", e)

    marked = [p for (s, p) in results if s == "marked"]
    skipped = [p for (s, p) in results if s == "skip"]
    logging.info("Marked: %d, Skipped: %d", len(marked), len(skipped))
    return 0
