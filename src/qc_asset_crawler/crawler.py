from __future__ import annotations

import concurrent.futures
import logging
import os
import sys
from pathlib import Path
from collections.abc import Iterable

from qc_asset_crawler.sequences import (
    iter_media,
    group_sequences,
    summarize_frames,
)
from qc_asset_crawler import hashing, trak_client, sidecar, hashcache, qcstate, config
from qc_asset_crawler.mutation import (
    SequenceMutationConfig,
    detect_sequence_mutation,
    summarize_frame_spans,
)


# Globals set from CLI
G_SIDECAR_MODE: str = "subdir"
G_FORCED_RESULT: str | None = None
G_NOTE: str | None = None
G_MUTATION_CONFIG: SequenceMutationConfig | None = None
G_SHOW_MUTATION_DIFF: bool = False


# ----------------- Helpers -----------------


def build_mutation_config(args) -> SequenceMutationConfig | None:
    """
    Build mutation config from CLI args.
    Returns None if mutation detection is disabled.
    """
    if not getattr(args, "enable_mutation_detection", False):
        return None

    return SequenceMutationConfig(
        threshold_frames=args.mutation_threshold_frames or 1,
        threshold_percent=args.mutation_threshold_percent,
        count_removed_frames=args.mutation_count_removed,
        treat_added_frames_as_mutation=True,
    )


def normalize_base_ext(base: str, ext: str) -> tuple[str, str]:
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


def _sequence_media_exists(seq_root: Path, seq_info: dict) -> bool:
    """
    Return True if there appear to be any media frames left for this sequence.

    We use the sequence metadata:
      - base: filename prefix (without trailing dot)
      - ext: extension without leading dot (e.g. 'tif')
    and look for files in seq_root that match that (loosely).
    """
    if not seq_root.exists() or not seq_root.is_dir():
        return False

    base = (seq_info.get("base") or "").strip()
    ext = (seq_info.get("ext") or "").lstrip(".").lower()

    expected_suffix = f".{ext}" if ext else None

    try:
        for child in seq_root.iterdir():
            if not child.is_file():
                continue

            if expected_suffix and child.suffix.lower() != expected_suffix:
                continue

            if base and not child.name.startswith(base):
                continue

            # Found at least one plausible frame
            return True
    except FileNotFoundError:
        return False

    return False


def _iter_sidecars_under_root(root: Path):
    """
    Yield all known QC sidecar paths under root.

    We mirror qc_cleanup.py / README patterns:
      - Inline & dot file sidecars: *.qc.json, .*.qc.json
      - Subdir sidecars: .qc/file.ext.qc.json  (also match *.qc.json)
      - Sequence sidecars: e.g. sequence.qc.json, .sequence.qc.json
        (name comes from sidecar.get_side_name_sequence()).
    """
    seen = set()

    # All per-file sidecars (inline, dot, subdir) end with .qc.json
    for p in root.rglob("*.qc.json"):
        if p not in seen:
            seen.add(p)
            yield p

    # Sequence sidecars: sequence.qc.json / .sequence.qc.json (plus subdir variants)
    seq_name = sidecar.get_side_name_sequence()
    for name in (seq_name, f".{seq_name}"):
        for p in root.rglob(name):
            if p not in seen:
                seen.add(p)
                yield p


def mark_missing_content(root: Path) -> int:
    """
    For any sidecar under `root` whose media no longer exists on disk,
    set content_state = "missing" (without changing qc_id / qc_result /
    last_valid_qc_*).

    Singles:
      - asset_path points to the media file; we mark missing when the file is gone.

    Sequences:
      - asset_path points to the sequence directory; we mark missing when there
        are no frames left in that directory matching the recorded base/ext.
    """
    missing_count = 0
    root = root.resolve()

    for sc in _iter_sidecars_under_root(root):
        data = sidecar.read_sidecar(sc)
        if not data:
            continue

        asset_path_str = data.get("asset_path")
        if not asset_path_str:
            continue

        ap = Path(asset_path_str)

        # If the asset_path is relative, treat it as relative to the crawl root.
        if not ap.is_absolute():
            ap = (root / ap).resolve()
        else:
            ap = ap.resolve()

        # Optionally ignore stuff clearly outside the root, to be safe.
        try:
            _ = ap.relative_to(root)
        except Exception:
            continue

        seq_info = data.get("sequence")

        # --- Sequence sidecars: asset_path is the sequence directory ---
        if isinstance(seq_info, dict) and seq_info:
            seq_root = ap if ap.is_dir() else ap.parent

            media_exists = _sequence_media_exists(seq_root, seq_info)

            if media_exists:
                # There are still frames; nothing to do.
                continue

            # Already marked as missing? No need to rewrite.
            if data.get("content_state") == "missing":
                continue

            data["content_state"] = "missing"
            sidecar.write_sidecar(sc, data)
            missing_count += 1
            continue

        # --- Single-file sidecars: asset_path is the media file ---
        if ap.exists():
            continue

        if data.get("content_state") == "missing":
            continue

        data["content_state"] = "missing"
        sidecar.write_sidecar(sc, data)
        missing_count += 1

    return missing_count


# ----------------- Processing -----------------


def process_single_file(
    p: Path,
    operator: str,
    asset_id: str | None = None,
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

    # Prefer explicit asset_id from CLI, then Trak lookup, then existing sidecar
    existing_asset_id = existing.get("asset_id") if existing else None
    lookup: dict = {}
    effective_asset_id = asset_id  # CLI parameter wins if provided

    if not effective_asset_id:
        lookup = trak_client.tracker_lookup_asset_by_path(p)
        trak_asset_id = lookup.get("asset_id")
        if trak_asset_id:
            # Trak gave us something – treat that as canonical
            effective_asset_id = trak_asset_id
        else:
            # Trak had no idea (e.g. 401/404) – keep whatever we had before
            effective_asset_id = existing_asset_id

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
    is_new_asset = existing is None

    if content_changed:
        # First time we've ever seen this path → mark as "new"
        # Otherwise, it's a genuine modification of previously-seen content.
        sig["content_state"] = "new" if is_new_asset else "modified"

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
    files: list[Path],
    operator: str,
    asset_id: str | None = None,
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

    With mutation detection enabled (G_MUTATION_CONFIG not None):
    - For automated runs, we treat a sequence as "changed enough to require QC"
      based on the configured thresholds and hashcache-derived per-frame hashes,
      rather than simply any change in the manifest content_hash.
    """
    sc = sidecar.sequence_sidecar_path(dir_path)

    cache = hashcache.load_hashcache(dir_path)

    # Snapshot previous per-file hashes for mutation detection, if enabled.
    # We use file names as identifiers within the sequence directory.
    previous_hashes: dict[str, str] = {}
    if G_MUTATION_CONFIG is not None:
        for p in files:
            entry = cache.get(p.name)
            if isinstance(entry, dict) and "hash" in entry:
                previous_hashes[p.name] = entry["hash"]

    cheap_fp = hashing.cheap_fingerprint(files)
    existing = sidecar.read_sidecar(sc)

    existing_content_hash = existing.get("content_hash") if existing else None
    operator_forced = G_FORCED_RESULT is not None

    # ---------- Fast-path skip for automated runs ----------
    # If cheap fingerprint hasn't changed and policy unchanged, we can skip deep hashing & QC
    # if (
    #    not operator_forced
    #    and existing
    #    and existing.get("policy_version") == sidecar.get_qc_policy_version()
    # ):
    #    seq = existing.get("sequence", {}) or {}
    #    if seq.get("cheap_fp") == cheap_fp:
    #        return ("skip", dir_path / f"{base}*.{ext}")

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

    # ---------- Optional sequence-level mutation detection ----------
    mutation_result = None
    if G_MUTATION_CONFIG is not None:
        # Build current per-file hashes from the (now updated) cache.
        current_hashes: dict[str, str] = {}
        for p in files:
            entry = cache.get(p.name)
            if isinstance(entry, dict) and "hash" in entry:
                current_hashes[p.name] = entry["hash"]

        mutation_result = detect_sequence_mutation(
            previous_hashes=previous_hashes,
            current_hashes=current_hashes,
            config=G_MUTATION_CONFIG,
        )

        if existing and G_SHOW_MUTATION_DIFF:
            changed = summarize_frame_spans(sorted(mutation_result.changed_frames))
            added = summarize_frame_spans(sorted(mutation_result.added_frames))
            removed = summarize_frame_spans(sorted(mutation_result.removed_frames))

            if changed:
                logging.info(
                    "Sequence %s: changed frames: %s",
                    dir_path / f"{base}*.{ext}",
                    changed,
                )
            if added:
                logging.info(
                    "Sequence %s: added frames: %s",
                    dir_path / f"{base}*.{ext}",
                    added,
                )
            if removed and G_MUTATION_CONFIG.count_removed_frames:
                logging.info(
                    "Sequence %s: removed frames: %s",
                    dir_path / f"{base}*.{ext}",
                    removed,
                )

    # For automated runs (no forced result), we can still early-out if QC is not needed.
    # When mutation detection is enabled, we use its result instead of a simple
    # "content hash changed" check; otherwise we fall back to the original needs_reqc.
    if not operator_forced and existing:
        policy_changed = (
            existing.get("policy_version") != sidecar.get_qc_policy_version()
        )

        if G_MUTATION_CONFIG is not None and mutation_result is not None:
            # Policy changes always require QC, regardless of content.
            if policy_changed:
                needs_qc = True
            else:
                # Use mutation logic to decide if content changed "enough".
                needs_qc = mutation_result.mutated
        else:
            # Original behaviour: policy or content hash change triggers QC.
            needs_qc = sidecar.needs_reqc(existing, seq_hash)

        if not needs_qc:
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
    existing = sidecar.read_sidecar(sc)
    existing_content_hash = existing.get("content_hash") if existing else None

    operator_forced = G_FORCED_RESULT is not None

    # Prefer explicit asset_id from CLI, then Trak directory/file lookup, then existing
    existing_asset_id = existing.get("asset_id") if existing else None
    effective_asset_id = asset_id
    lookup_used = None

    if not effective_asset_id:
        # Try the directory path first
        lookup_dir = trak_client.tracker_lookup_asset_by_path(dir_path)
        trak_asset_id = lookup_dir.get("asset_id")
        lookup_used = lookup_dir

        if trak_asset_id:
            effective_asset_id = trak_asset_id
        else:
            # If that failed, try the first file in the sequence
            if files:
                lookup_file = trak_client.tracker_lookup_asset_by_path(files[0])
                trak_asset_id = lookup_file.get("asset_id")
                lookup_used = lookup_file
                if trak_asset_id:
                    effective_asset_id = trak_asset_id

    # Final fallback: keep existing asset_id if Trak gave us nothing new
    if not effective_asset_id and existing_asset_id:
        effective_asset_id = existing_asset_id

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
    is_new_sequence = existing is None

    if content_changed:
        sig["content_state"] = "new" if is_new_sequence else "modified"

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
        # this is a new human QC event
        sig["last_valid_qc_id"] = sig["qc_id"]
        sig["last_valid_qc_time"] = sig["qc_time"]
    else:
        # carry forward from existing
        if prev_last_valid_qc_id is not None:
            sig["last_valid_qc_id"] = prev_last_valid_qc_id
        if prev_last_valid_qc_time is not None:
            sig["last_valid_qc_time"] = prev_last_valid_qc_time

        # Lightweight sequence summary
        names = [p.name for p in files]
    summary = summarize_frames(names) or {}
    frame_count = len(names)

    sig["sequence"] = {
        "base": nbase,
        "ext": next_,
        "first": names[0],
        "last": names[-1],
        "frame_count": frame_count,
        **summary,
        "cheap_fp": cheap_fp,
        # Compact per-sequence fingerprint; currently just the manifest hash.
        # In schema v2 we can evolve this into a richer structure without
        # changing callers that read sequence["fingerprint"].
        "fingerprint": sig.get("content_hash"),
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
    asset_id: str | None = None,
) -> int:
    """Run the crawler for a single root and log a concise summary."""
    files = list(iter_media(root))
    sequences_map, singles = group_sequences(files, min_seq=min_seq)

    logging.info(
        "QC crawl starting for %s: %d media files (%d sequences, %d singles)",
        root,
        len(files),
        len(sequences_map),
        len(singles),
    )

    results: list[tuple[str, Path]] = []
    worker_errors = 0

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
            except Exception as e:  # pragma: no cover - defensive logging
                worker_errors += 1
                logging.error("Worker error: %s", e, exc_info=True)

    marked = [p for (s, p) in results if s == "marked"]
    skipped = [p for (s, p) in results if s == "skip"]

    marked_count = len(marked)
    skipped_count = len(skipped)

    logging.info("Marked: %d, Skipped: %d", marked_count, skipped_count)

    # Second pass: mark sidecars whose media has gone missing
    missing = mark_missing_content(root)
    if missing:
        logging.info("Marked missing: %d", missing)

    # Final summary line for this root
    logging.info(
        "QC crawl summary for %s: sequences=%d, singles=%d, "
        "marked=%d, skipped=%d, missing_marked=%d, worker_errors=%d",
        root,
        len(sequences_map),
        len(singles),
        marked_count,
        skipped_count,
        missing,
        worker_errors,
    )

    return 0


def run_many(
    roots: Iterable[Path],
    operator: str,
    workers: int,
    min_seq: int,
    asset_ids: Iterable[str | None] | None = None,
) -> int:
    """
    Run the crawler over multiple roots in a single invocation.

    Parameters
    ----------
    roots:
        One or more root directories to crawl.
    operator:
        Operator name / identifier to embed in sidecars.
    workers:
        Max worker threads per root (passed through to `run`).
    min_seq:
        Minimum sequence length for grouping frames (passed through to `run`).
    asset_ids:
        Optional iterable of asset IDs. Semantics:

        - If None: no explicit asset_id is passed; `run` will use Trak lookup
          and/or any existing sidecar `asset_id`.
        - If length == 1: the same asset_id is used for all roots.
        - If length == len(roots): each root is paired with the corresponding
          asset_id.
        - Any other length pairing is treated as a configuration error and the
          function returns a non-zero exit code.

    Returns
    -------
    int
        0 if all roots completed successfully, otherwise the first non-zero
        exit code returned by `run`.
    """
    roots = [Path(r).resolve() for r in roots]
    if not roots:
        logging.warning("No roots provided to run_many; nothing to do.")
        return 0

    # Normalise asset_ids into a list aligned with roots
    normalised_asset_ids: list[str | None] = [None] * len(roots)
    if asset_ids is not None:
        asset_ids = list(asset_ids)
        if len(asset_ids) == 1 and len(roots) >= 1:
            normalised_asset_ids = [asset_ids[0]] * len(roots)
        elif len(asset_ids) == len(roots):
            normalised_asset_ids = list(asset_ids)
        else:
            logging.error(
                "asset_ids length (%d) must be 1 or match roots length (%d)",
                len(asset_ids),
                len(roots),
            )
            return 1

    exit_code = 0

    for idx, (root, asset_id) in enumerate(zip(roots, normalised_asset_ids), start=1):
        logging.info(
            "=== CRAWL %d/%d: root=%s asset_id=%s ===",
            idx,
            len(roots),
            root,
            asset_id or "<auto>",
        )
        code = run(
            root=root,
            operator=operator,
            workers=workers,
            min_seq=min_seq,
            asset_id=asset_id,
        )
        # Preserve the first non-zero exit code, but still process all roots
        if code != 0 and exit_code == 0:
            exit_code = code

    return exit_code
