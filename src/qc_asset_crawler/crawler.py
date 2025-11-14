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
        # best-effort only
        pass


# ----------------- Processing -----------------


def process_single_file(
    p: Path,
    operator: str,
    asset_id: Optional[str] = None,
):
    """
    Process a single media file.

    Option A semantics:
    - If G_FORCED_RESULT is None (nightly/autonomous): only re-QC when content/policy changed.
      New/changed assets are always set to qc_result="pending".
    - If G_FORCED_RESULT is set (operator run): always rewrite the sidecar, even if bytes/policy
      are unchanged, so operators can change pass/fail/notes.
    """
    sc = sidecar.sidecar_path_for_file(p)
    existing = sidecar.read_sidecar(sc)

    # Always hash the single file – there's no cheap_fp here.
    ch = hashing.blake3_or_sha256_file(p)

    # Detect whether content has actually changed vs stored sidecar
    existing_content_hash = existing.get("content_hash") if existing else None
    content_changed = existing_content_hash is None or existing_content_hash != ch

    # For automated runs (no explicit result), skip if content & policy unchanged.
    if G_FORCED_RESULT is None and not sidecar.needs_reqc(existing, ch):
        return ("skip", p)

    # Prefer explicit asset_id from CLI, otherwise fall back to Trak lookup
    lookup = {}
    effective_asset_id = asset_id  # function parameter wins if provided

    if not effective_asset_id:
        lookup = trak_client.tracker_lookup_asset_by_path(p)
        effective_asset_id = lookup.get("asset_id")

    # Default behaviour for Option A:
    # - No forced result: always "pending" when we (re)write a sidecar.
    # - Forced result: use operator's override.
    result = G_FORCED_RESULT if G_FORCED_RESULT is not None else "pending"

    sig = qcstate.make_qc_signature(
        p,
        ch,
        effective_asset_id,
        operator,
        result=result,
        note=G_NOTE,
    )

    # --- Preserve qc_id for non-operator (nightly/bot) runs ---
    # Nightly content-change detection should NOT create a new QC event ID.
    if existing and G_FORCED_RESULT is None and existing.get("qc_id"):
        sig["qc_id"] = existing["qc_id"]

    # --- content_state + prev_content_hash ---
    if content_changed:
        sig["content_state"] = "modified"
        if existing_content_hash is not None:
            sig["prev_content_hash"] = existing_content_hash
    else:
        sig["content_state"] = "unchanged"
        # carry forward previous prev_content_hash if present
        if existing and existing.get("prev_content_hash"):
            sig["prev_content_hash"] = existing["prev_content_hash"]

    # --- last_valid_qc_id / last_valid_qc_time ---
    if existing:
        prev_last_valid_qc_id = existing.get("last_valid_qc_id")
        prev_last_valid_qc_time = existing.get("last_valid_qc_time")
    else:
        prev_last_valid_qc_id = None
        prev_last_valid_qc_time = None

    if G_FORCED_RESULT is not None and sig.get("qc_result") != "pending":
        # New explicit QC event (operator result pass/fail/etc.)
        sig["last_valid_qc_id"] = sig["qc_id"]
        sig["last_valid_qc_time"] = sig["qc_time"]
    else:
        # No new valid QC; carry forward last_valid_* if they exist
        if prev_last_valid_qc_id is not None:
            sig["last_valid_qc_id"] = prev_last_valid_qc_id
        if prev_last_valid_qc_time is not None:
            sig["last_valid_qc_time"] = prev_last_valid_qc_time

    if result == "pending":
        # Record tracker lookup status if we actually did a lookup; otherwise, just None/None.
        sig["tracker_status"] = {
            "status": lookup.get("status"),
            "http_code": lookup.get("http_code"),
        }

    sidecar.write_sidecar(sc, sig)
    set_xattr(p, sig["qc_id"])

    # Use the effective asset id (CLI override or lookup) when posting to Trak
    trak_client.tracker_set_qc(effective_asset_id, sig)

    return ("marked", p)


def process_sequence(
    dir_path: Path,
    base: str,
    ext: str,
    files: List[Path],
    operator: str,
    asset_id: Optional[str] = None,
):
    """
    Process an image sequence under dir_path.

    Option A semantics mirror process_single_file:
    - Automated runs (no G_FORCED_RESULT):
        * Use cheap_fp + policy to skip unchanged sequences without hashing.
        * On change, reset qc_result to "pending".
    - Operator runs (G_FORCED_RESULT set):
        * Always rewrite the sidecar so qc_result/notes can change, even if bytes unchanged.
        * Reuse existing content_hash when cheap_fp+policy match to avoid rehashing.
    """
    sc = sidecar.sequence_sidecar_path(dir_path)

    cache = hashcache.load_hashcache(dir_path)
    cheap_fp = hashing.cheap_fingerprint(files)
    existing = sidecar.read_sidecar(sc)

    existing_content_hash = existing.get("content_hash") if existing else None

    operator_forced = G_FORCED_RESULT is not None

    # ---------- Fast-path skip for automated runs ----------
    # If cheap fingerprint hasn't changed and policy unchanged, we can skip deep hashing & QC
    if (
        not operator_forced
        and existing
        and existing.get("policy_version") == sidecar.get_qc_policy_version()
    ):
        seq = existing.get("sequence", {}) or {}
        if seq.get("cheap_fp") == cheap_fp:
            return ("skip", dir_path / f"{base}*.{ext}")

    # ---------- Deep hashing / manifest hash ----------
    # For automated runs, we want full content-hash based re-QC decisions.
    # For operator runs, we still need a content_hash, but can reuse the existing one
    # if we can confidently say content didn't change (cheap_fp + policy).
    if (
        operator_forced
        and existing
        and existing.get("policy_version") == sidecar.get_qc_policy_version()
        and (existing.get("sequence") or {}).get("cheap_fp") == cheap_fp
        and existing.get("content_hash")
    ):
        # Content appears unchanged; reuse previous manifest hash.
        seq_hash = existing["content_hash"]
    else:
        # Deep hashing with cache
        seq_hash = hashing.manifest_hash_for_files(files, cache)
        hashcache.save_hashcache(dir_path, cache)

    # Determine if the content has actually changed vs what was stored
    content_changed = existing_content_hash is None or existing_content_hash != seq_hash

    # For automated runs (no forced result), we can still early-out if content & policy
    # are unchanged (needs_reqc returns False). We may still update cheap_fp if missing.
    if not operator_forced and existing and not sidecar.needs_reqc(existing, seq_hash):
        # But update cheap_fp if missing or changed
        existing_seq = existing.setdefault("sequence", {}) or {}
        if existing_seq.get("cheap_fp") != cheap_fp:
            existing_seq["cheap_fp"] = cheap_fp
            sidecar.write_sidecar(sc, existing)
        return ("skip", dir_path / f"{base}*.{ext}")

    # ---------- Build new signature ----------

    # Normalize base/ext for storage
    nbase, next_ = normalize_base_ext(base, ext)

    # Decide which asset_id to use:
    # - prefer explicit asset_id from CLI
    # - otherwise fall back to Trak lookup (dir, then first file)
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

    # Same result semantics as single files
    result = G_FORCED_RESULT if G_FORCED_RESULT is not None else "pending"

    sig = qcstate.make_qc_signature(
        dir_path,
        seq_hash,
        effective_asset_id,
        operator,
        result=result,
        note=G_NOTE,
    )

    # --- Preserve qc_id for non-operator (nightly/bot) runs ---
    # When content changes but QC is not yet redone, we keep the existing qc_id
    # and simply reset qc_result to "pending".
    if existing and G_FORCED_RESULT is None and existing.get("qc_id"):
        sig["qc_id"] = existing["qc_id"]

    # --- content_state + prev_content_hash for sequences ---
    if content_changed:
        sig["content_state"] = "modified"
        if existing_content_hash is not None:
            sig["prev_content_hash"] = existing_content_hash
    else:
        sig["content_state"] = "unchanged"
        if existing and existing.get("prev_content_hash"):
            sig["prev_content_hash"] = existing["prev_content_hash"]

    # --- last_valid_qc_id / last_valid_qc_time for sequences ---
    if existing:
        prev_last_valid_qc_id = existing.get("last_valid_qc_id")
        prev_last_valid_qc_time = existing.get("last_valid_qc_time")
    else:
        prev_last_valid_qc_id = None
        prev_last_valid_qc_time = None

    if G_FORCED_RESULT is not None and sig.get("qc_result") != "pending":
        sig["last_valid_qc_id"] = sig["qc_id"]
        sig["last_valid_qc_time"] = sig["qc_time"]
    else:
        if prev_last_valid_qc_id is not None:
            sig["last_valid_qc_id"] = prev_last_valid_qc_id
        if prev_last_valid_qc_time is not None:
            sig["last_valid_qc_time"] = prev_last_valid_qc_time

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
        # Protect against operator_forced="pending" with no lookup performed
        if lookup_used is not None:
            sig["tracker_status"] = {
                "status": lookup_used.get("status"),
                "http_code": lookup_used.get("http_code"),
            }
        else:
            sig["tracker_status"] = {"status": None, "http_code": None}

    sidecar.write_sidecar(sc, sig)

    try:
        set_xattr(dir_path, sig["qc_id"])
    except Exception:
        pass

    # Use effective_asset_id here, same as in single-file path
    trak_client.tracker_set_qc(effective_asset_id, sig)

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
