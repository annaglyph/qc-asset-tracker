from __future__ import annotations

from pathlib import Path
from typing import List, Dict
import hashlib

try:
    import blake3  # type: ignore
except Exception:
    blake3 = None


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
