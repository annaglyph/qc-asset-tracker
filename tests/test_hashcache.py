from __future__ import annotations

import json
from pathlib import Path


from qc_asset_crawler.hashcache import load_hashcache, save_hashcache


def test_load_hashcache_empty_directory(tmp_path: Path) -> None:
    """
    If the hashcache file does not exist, load_hashcache must return {}
    and NOT throw.
    """
    cache = load_hashcache(tmp_path)
    assert cache == {}


def test_load_hashcache_invalid_json(tmp_path: Path) -> None:
    """
    If the hashcache exists but contains invalid JSON,
    load_hashcache should return {} and not crash.
    """
    cache_file = tmp_path / ".qc.hashcache.json"
    cache_file.write_text("{this is not valid json", encoding="utf-8")

    cache = load_hashcache(tmp_path)
    assert cache == {}  # safe fallback


def test_save_hashcache_creates_file(tmp_path: Path) -> None:
    """
    save_hashcache() should create '.qc.hashcache.json' and write JSON content.
    """
    cache = {
        "fileA.exr": "blake3:123456",
        "fileB.exr": "blake3:abcabc",
    }

    save_hashcache(tmp_path, cache)

    cache_file = tmp_path / ".qc.hashcache.json"
    assert cache_file.exists()

    # Validate written JSON
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert data == cache


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """
    save_hashcache followed by load_hashcache should round-trip exactly.
    """
    cache_in = {
        "f1.exr": "blake3:1111",
        "f2.exr": "blake3:2222",
    }

    save_hashcache(tmp_path, cache_in)
    cache_out = load_hashcache(tmp_path)

    assert cache_in == cache_out


def test_load_hashcache_ignores_extra_fields(tmp_path: Path) -> None:
    """
    If someone manually edits the hashcache and adds junk fields,
    load_hashcache should still return a dictionary and not error.
    """
    cache_file = tmp_path / ".qc.hashcache.json"
    cache_file.write_text(
        json.dumps(
            {
                "somefile.dpx": "blake3:abcd",
                "junk_field": ["unexpected", 123],
            }
        ),
        encoding="utf-8",
    )

    cache = load_hashcache(tmp_path)

    # We accept everything as-is because the cache file is just a
    # string-to-string mapping, but it must still be a dict.
    assert isinstance(cache, dict)
    assert cache["somefile.dpx"] == "blake3:abcd"
    assert cache["junk_field"] == ["unexpected", 123]
