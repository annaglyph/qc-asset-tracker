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
import concurrent.futures
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
import requests
import dotenv
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import blake3  # type: ignore
except Exception:
    blake3 = None


def find_data_file(filename):
    if getattr(sys, "frozen", False):
        datadir = os.path.dirname(sys.executable)
    else:
        datadir = os.path.dirname(__file__)
    return os.path.join(datadir, filename)


dotenv.load_dotenv(find_data_file(".env"))


# Globals set from CLI
G_SIDECAR_MODE: str = "subdir"
G_FORCED_RESULT: Optional[str] = None
G_NOTE: Optional[str] = None

# ----------------- Config -----------------
TOOL_VERSION = "eikon-qc-marker/1.1.0"
QC_POLICY_VERSION = "2025.11.0"

# Environment-configurable
TRAK_BASE_URL = os.environ.get("TRAK_BASE_URL", None)
X_API_KEY = os.environ.get("TRAK_ASSET_TRACKER_API_KEY", None)
XATTR_KEY = os.environ.get("QC_XATTR_KEY", "user.eikon.qc")
HASHCACHE_NAME = os.environ.get("QC_HASHCACHE_NAME", ".qc.hashcache.json")
SIDE_SUFFIX_FILE = os.environ.get("QC_SIDE_SUFFIX_FILE", ".qc.json")
SIDE_NAME_SEQUENCE = os.environ.get("QC_SIDE_NAME_SEQUENCE", "qc.sequence.json")

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


# ----------------- Utils -----------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def uuid7() -> str:
    if hasattr(uuid, "uuid7"):
        return str(uuid.uuid7())  # py>=3.12
    # Fallback: time-ordered-ish UUID (ULID-like)
    t_ms = int(time.time() * 1000).to_bytes(6, "big")
    rand = os.urandom(10)
    return str(uuid.UUID(bytes=t_ms + rand))


def headers_json() -> Dict[str, str]:
    header = {
        "content-type": "application/json",
        "cache-control": "no-cache",
        "accept": "text/plain",
    }
    if X_API_KEY:
        header["x-api-key"] = X_API_KEY
    return header


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


# ----------------- Filesystem walk & grouping -----------------
_seq_re = re.compile(r"^(?P<base>.*?)(?P<frame>\d+)(?P<dot>\.)(?P<ext>[^.]+)$")


def is_sequence_candidate(p: Path) -> bool:
    return p.suffix.lower() in SEQ_EXTS


def iter_media(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if f.startswith("."):
                continue
            p = Path(dirpath) / f
            if p.suffix.lower() in MEDIA_EXTS:
                yield p


def seq_key(p: Path):
    m = _seq_re.match(p.name)
    if not m:
        return None
    return (p.parent, m.group("base"), m.group("ext"))


def group_sequences(files: Iterable[Path]):
    groups = {}
    singles = []
    for p in files:
        if is_sequence_candidate(p):
            k = seq_key(p)
            if k:
                groups.setdefault(k, []).append(p)
                continue
        singles.append(p)
    # Keep groups with >=3 frames (tunable)
    sequences = {k: sorted(v) for k, v in groups.items() if len(v) >= 3}
    seq_members = {p for vs in sequences.values() for p in vs}
    singles.extend([p for p in files if p not in seq_members and p not in singles])
    return sequences, singles


# ----------------- Hashing -----------------
def blake3_or_sha256_file(path: Path, chunk=4 * 1024 * 1024) -> str:
    if blake3 is not None:
        h = blake3.blake3()
        with path.open("rb") as f:
            for b in iter(lambda: f.read(chunk), b""):
                h.update(b)
        return "blake3:" + h.hexdigest()
    # Fallback
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return "sha256:" + h.hexdigest()


def cheap_fingerprint(paths: List[Path]) -> Dict[str, int]:
    total_files, total_bytes, newest_mtime = 0, 0, 0
    for p in paths:
        st = p.stat()
        total_files += 1
        total_bytes += int(st.st_size)
        if int(st.st_mtime) > newest_mtime:
            newest_mtime = int(st.st_mtime)
    return {"files": total_files, "bytes": total_bytes, "newest_mtime": newest_mtime}


def load_hashcache(dir_path: Path):
    f = dir_path / HASHCACHE_NAME
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_hashcache(dir_path: Path, cache):
    f = dir_path / HASHCACHE_NAME
    try:
        f.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def content_hash_with_cache(p: Path, cache):
    key = p.name
    st = p.stat()
    meta = {"size": int(st.st_size), "mtime": int(st.st_mtime)}
    entry = cache.get(key)
    if (
        entry
        and entry.get("size") == meta["size"]
        and entry.get("mtime") == meta["mtime"]
        and "hash" in entry
    ):
        return entry["hash"]
    h = blake3_or_sha256_file(p)
    cache[key] = {"size": meta["size"], "mtime": meta["mtime"], "hash": h}
    return h


def manifest_hash_for_files(files: List[Path], cache) -> str:
    # Stable order
    lines = []
    for p in files:
        st = p.stat()
        fh = content_hash_with_cache(p, cache)
        lines.append(f"{p.name}\0{st.st_size}\0{fh}\n")
    joined = "".join(lines).encode("utf-8")
    # Use blake2b for the joined manifest (fast, stable); content hashes are already blake3/sha256
    return "blake2b:" + hashlib.blake2b(joined, digest_size=32).hexdigest()


# ----------------- Sequence summaries -----------------
def summarize_frames(file_names: List[str]):
    frames = []
    pad = None
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
    ranges += 1  # Last range
    return {
        "frame_min": frames[0],
        "frame_max": frames[-1],
        "pad": pad,
        "frame_count": len(frames),
        "range_count": ranges,
        "holes": holes,
    }


# ----------------- Sidecars -----------------
def sidecar_path_for_file(p: Path) -> Path:
    mode = globals().get("G_SIDECAR_MODE", "inline")
    name = f"{p.name}{SIDE_SUFFIX_FILE}"
    if mode == "inline":
        return p.with_suffix(p.suffix + SIDE_SUFFIX_FILE)
    if mode == "dot":
        return p.parent / f".{name}"
    return p.parent / ".qc" / name


def sequence_sidecar_path(dir_path: Path) -> Path:
    mode = globals().get("G_SIDECAR_MODE", "inline")
    if mode == "inline":
        return dir_path / SIDE_NAME_SEQUENCE
    if mode == "dot":
        return dir_path / f".{SIDE_NAME_SEQUENCE}"
    return dir_path / ".qc" / SIDE_NAME_SEQUENCE


def set_hidden_attribute(path: Path) -> None:
    mode = globals().get("G_SIDECAR_MODE", "inline")
    if mode not in ("dot", "subdir"):
        return
    try:
        if sys.platform.startswith("win"):
            import ctypes

            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
        elif sys.platform == "darwin":
            import subprocess

            subprocess.run(["chflags", "hidden", str(path)], check=False)
    except Exception:
        pass


def read_sidecar(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_sidecar(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    set_hidden_attribute(path)


def needs_reqc(existing, new_content_hash: str) -> bool:
    if not existing:
        return True
    if existing.get("policy_version") != QC_POLICY_VERSION:
        return True
    return existing.get("content_hash") != new_content_hash


# ----------------- xattrs (best-effort) -----------------
def set_xattr(path: Path, value: str) -> None:
    try:
        if sys.platform.startswith("linux"):
            os.setxattr(path.as_posix(), XATTR_KEY, value.encode("utf-8"))
        elif sys.platform == "darwin":
            import xattr

            xattr.setxattr(path.as_posix(), XATTR_KEY, value.encode("utf-8"))
    except Exception:
        pass


# ----------------- Tracker API (requests) -----------------
def tracker_lookup_asset_by_path(path: Path) -> dict:
    url = f"{TRAK_BASE_URL.rstrip('/')}/asset/asset-search"
    body = {
        "searchPage": {"pageSize": 100},
        "assetSearchType": 2,
        "includeCustomer": False,
        "assetPath": path.as_posix(),
        "tagIds": [],
    }
    try:
        r = requests.post(url, json=body, headers=headers_json(), timeout=15)
        logging.debug(r.text)
        if not r.ok:
            status = "unauthorized" if r.status_code in (401, 403) else "error"
            return {"asset_id": None, "status": status, "http_code": r.status_code}
        data = r.json()
        asset_id = (data.get("items") or [{}])[0].get("asset_id") or data.get(
            "asset_id"
        )
        return {"asset_id": asset_id, "status": "ok", "http_code": 200}
    except requests.RequestException:
        return {"asset_id": None, "status": "error", "http_code": None}


def tracker_set_qc(asset_id: Optional[str], payload: dict) -> bool:
    if not asset_id or payload.get("qc_result") == "pending":
        return False
    url = f"{TRAK_BASE_URL.rstrip('/')}/assets/{asset_id}/qc"
    try:
        r = requests.post(url, json=payload, headers=headers_json(), timeout=15)
        return bool(r.ok)
    except requests.RequestException:
        return False


# ----------------- Processing -----------------
def make_qc_signature(
    asset_path: Path,
    content_hash: str,
    asset_id: Optional[str],
    operator: str,
    result: str = "pass",
) -> dict:
    return {
        "qc_id": uuid7(),
        "qc_time": now_iso(),
        "operator": operator,
        "tool_version": TOOL_VERSION,
        "policy_version": QC_POLICY_VERSION,
        "asset_path": asset_path.as_posix(),
        "asset_id": asset_id,
        "content_hash": content_hash,
        "qc_result": result,
        "notes": G_NOTE or "",
    }


def process_single_file(p: Path, operator: str):
    sc = sidecar_path_for_file(p)
    existing = read_sidecar(sc)
    ch = blake3_or_sha256_file(p)
    if not needs_reqc(existing, ch):
        return ("skip", p)
    lookup = tracker_lookup_asset_by_path(p)
    asset_id = lookup.get("asset_id")
    result = G_FORCED_RESULT or ("pass" if asset_id else "pending")
    sig = make_qc_signature(p, ch, asset_id, operator, result=result)
    if result == "pending":
        sig["tracker_status"] = {k: lookup.get(k) for k in ("status", "http_code")}
    write_sidecar(sc, sig)
    set_xattr(p, sig["qc_id"])
    tracker_set_qc(asset_id, sig)
    return ("marked", p)


def process_sequence(
    dir_path: Path, base: str, ext: str, files: List[Path], operator: str
):
    sc = sequence_sidecar_path(dir_path)
    cache = load_hashcache(dir_path)

    # Reuse cheap fingerprint to avoid rehashing needlessly
    cheap_fp = cheap_fingerprint(files)
    existing = read_sidecar(sc)

    # If cheap fingerprint hasn't changed and policy unchanged, we can skip deep hashing & QC
    if existing and existing.get("policy_version") == QC_POLICY_VERSION:
        seq = existing.get("sequence", {})
        if seq.get("cheap_fp") == cheap_fp:
            return ("skip", dir_path / f"{base}*.{ext}")

    # Deep hashing with cache
    seq_hash = manifest_hash_for_files(files, cache)
    save_hashcache(dir_path, cache)
    if existing and not needs_reqc(existing, seq_hash):
        # But update cheap_fp if missing
        if existing.get("sequence", {}).get("cheap_fp") != cheap_fp:
            existing.setdefault("sequence", {})["cheap_fp"] = cheap_fp
            write_sidecar(sc, existing)
        return ("skip", dir_path / f"{base}*.{ext}")

    # Normalize base/ext for storage
    nbase, next_ = normalize_base_ext(base, ext)

    # Try folder then first file; pick the first successful lookup
    lookup_dir = tracker_lookup_asset_by_path(dir_path)
    asset_id = lookup_dir.get("asset_id")
    lookup_used = lookup_dir
    if not asset_id:
        lookup_file = tracker_lookup_asset_by_path(files[0])
        asset_id = lookup_file.get("asset_id")
        lookup_used = lookup_file
    result = G_FORCED_RESULT or ("pass" if asset_id else "pending")
    sig = make_qc_signature(dir_path, seq_hash, asset_id, operator, result=result)

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
    write_sidecar(sc, sig)

    try:
        set_xattr(dir_path, sig["qc_id"])
    except Exception:
        pass

    tracker_set_qc(asset_id, sig)
    return ("marked", dir_path / f"{nbase}*.{next_}")


# ----------------- CLI -----------------
def main():
    ap = argparse.ArgumentParser(
        description="QC marker for media on a SAN (consolidated)."
    )
    ap.add_argument("root", help="Root path to crawl")
    ap.add_argument(
        "--operator",
        default=os.environ.get("USER") or os.environ.get("USERNAME") or "system",
    )
    ap.add_argument("--workers", type=int, default=max(os.cpu_count() or 4, 4))
    ap.add_argument(
        "--log", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    ap.add_argument(
        "--min-seq", type=int, default=3, help="Minimum files to treat as a sequence"
    )
    ap.add_argument(
        "--sidecar-mode",
        choices=["inline", "dot", "subdir"],
        default="subdir",
        help="Where/how to store sidecars: inline, dot, or subdir (.qc/). Default: subdir",
    )
    ap.add_argument(
        "--result",
        choices=["pass", "fail", "pending"],
        help="Force QC result override for all assets processed",
    )
    ap.add_argument("--note", help="Optional operator note to store in the sidecar")
    args = ap.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log.upper(), logging.DEBUG),
        format="%(levelname)s %(message)s",
    )

    global G_SIDECAR_MODE, G_FORCED_RESULT, G_NOTE
    G_SIDECAR_MODE = args.sidecar_mode
    G_FORCED_RESULT = args.result
    G_NOTE = args.note

    root = Path(args.root).resolve()
    files = list(iter_media(root))

    sequences_map, singles = group_sequences(files)
    logging.info("Found %d sequences and %d singles", len(sequences_map), len(singles))

    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [
            ex.submit(process_sequence, d, base, ext, members, args.operator)
            for (d, base, ext), members in sequences_map.items()
        ]
        futs += [ex.submit(process_single_file, p, args.operator) for p in singles]
        for f in concurrent.futures.as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:
                logging.error("Worker error: %s", e)

    marked = [p for (s, p) in results if s == "marked"]
    skipped = [p for (s, p) in results if s == "skip"]
    logging.info("Marked: %d, Skipped: %d", len(marked), len(skipped))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
