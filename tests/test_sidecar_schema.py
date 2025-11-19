import pytest
import json

from qc_asset_crawler.sidecar import (
    read_sidecar,
    write_sidecar,
    validate_v1_sidecar,
    ensure_schema_metadata,
    get_schema_name,
    get_schema_version,
    _coerce_schema_version,
    migrate_to_latest,
    needs_reqc,
    SCHEMA_NAME,
    MIN_SUPPORTED_SCHEMA_VERSION,
    MAX_SUPPORTED_SCHEMA_VERSION,
)


def make_minimal_v1_sidecar(**overrides):
    data: dict[str, object] = {
        "schema_name": SCHEMA_NAME,
        "schema_version": 1,
        "asset_path": "/path/file.ext",
        "asset_hash": "abc123",
    }
    data.update(overrides)
    return data


def test_validate_v1_sidecar_happy_path():
    data = make_minimal_v1_sidecar(asset_id=12345)
    # Should not raise
    validate_v1_sidecar(data)


def test_validate_v1_sidecar_missing_required_field_raises():
    data = make_minimal_v1_sidecar()
    data.pop("asset_path")
    with pytest.raises(ValueError) as excinfo:
        validate_v1_sidecar(data)
    assert "asset_path" in str(excinfo.value)


@pytest.mark.parametrize(
    "input_value, expected",
    [
        (1, 1),
        ("1", 1),
        ("v1", 1),
        ("V2", 2),
        ("  3  ", 3),
    ],
)
def test_coerce_schema_version_normal_cases(input_value, expected):
    assert _coerce_schema_version(input_value) == expected


@pytest.mark.parametrize("input_value", ["x", "vX", None, 0.5, object()])
def test_coerce_schema_version_fallback_to_1(input_value):
    assert _coerce_schema_version(input_value) == 1


def test_ensure_schema_metadata_sets_defaults(monkeypatch):
    monkeypatch.setenv("QC_SCHEMA_NAME", "custom.schema")
    monkeypatch.setenv("QC_SCHEMA_VERSION", "2")

    payload = {"asset_path": "/path/file.ext", "asset_hash": "abc123"}
    out = ensure_schema_metadata(payload)

    assert out["schema_name"] == "custom.schema"

    # schema_version is whatever get_schema_version() returns, clamped to supported range
    version = int(out["schema_version"])
    assert version == int(get_schema_version())
    assert MIN_SUPPORTED_SCHEMA_VERSION <= version <= MAX_SUPPORTED_SCHEMA_VERSION
    # and env > max should clamp to MAX_SUPPORTED_SCHEMA_VERSION
    assert version == MAX_SUPPORTED_SCHEMA_VERSION


"""
def test_get_schema_name_and_version_use_env(monkeypatch):
    monkeypatch.setenv("QC_SCHEMA_NAME", "test.schema")
    monkeypatch.setenv("QC_SCHEMA_VERSION", "5")

    assert get_schema_name() == "test.schema"
    assert int(get_schema_version()) == 5
"""


def test_get_schema_name_and_version_use_env(monkeypatch):
    monkeypatch.setenv("QC_SCHEMA_NAME", "test.schema")
    monkeypatch.setenv("QC_SCHEMA_VERSION", "5")

    # Name should always respect the env override
    assert get_schema_name() == "test.schema"

    # Version is clamped to the supported range, not blindly equal to the env
    version = int(get_schema_version())
    assert MIN_SUPPORTED_SCHEMA_VERSION <= version <= MAX_SUPPORTED_SCHEMA_VERSION
    assert version == MAX_SUPPORTED_SCHEMA_VERSION


def test_migrate_to_latest_future_version_returns_data(monkeypatch):
    # If a sidecar somehow has a higher version than we support,
    # migrate_to_latest should currently just return the payload unchanged.
    monkeypatch.setenv("QC_SCHEMA_VERSION", "1")
    data = make_minimal_v1_sidecar(schema_version=999)
    migrated = migrate_to_latest(dict(data))
    assert migrated == data


def test_needs_reqc_when_no_existing():
    assert needs_reqc(None, "newhash") is True


def test_needs_reqc_policy_change_triggers():
    existing = make_minimal_v1_sidecar(policy_version="old", content_hash="h1")
    assert needs_reqc(existing, "h1") is True


def test_needs_reqc_content_change_triggers():
    existing = make_minimal_v1_sidecar(policy_version="2025.11.0", content_hash="h1")
    # Same policy, different content hash
    assert needs_reqc(existing, "h2") is True


def test_needs_reqc_same_policy_and_hash_skips():
    existing = make_minimal_v1_sidecar(policy_version="2025.11.0", content_hash="h1")
    assert needs_reqc(existing, "h1") is False


# ---------------------------------------------------------------------------
# read_sidecar / write_sidecar round-trip + legacy behaviour
# ---------------------------------------------------------------------------


def test_read_sidecar_missing_returns_none(tmp_path):
    p = tmp_path / "missing.qc.json"
    assert read_sidecar(p) is None


def test_read_sidecar_invalid_json_returns_none(tmp_path):
    p = tmp_path / "broken.qc.json"
    p.write_text("{not-valid-json", encoding="utf-8")

    data = read_sidecar(p)
    assert data is None


def test_write_and_read_sidecar_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("QC_SCHEMA_NAME", "roundtrip.schema")
    monkeypatch.setenv("QC_SCHEMA_VERSION", "1")

    p = tmp_path / "test.qc.json"
    payload = {
        "asset_path": "/path/file.ext",
        "asset_hash": "hash123",
        "custom_field": "hello",
    }

    write_sidecar(p, payload)
    assert p.exists()

    loaded = read_sidecar(p)
    assert loaded is not None

    # Core fields round-trip
    assert loaded["asset_path"] == "/path/file.ext"
    assert loaded["asset_hash"] == "hash123"
    assert loaded["custom_field"] == "hello"

    # Schema metadata is present and aligned with helpers
    assert loaded["schema_name"] == "roundtrip.schema"
    assert int(loaded["schema_version"]) == int(get_schema_version())


def test_read_sidecar_adds_schema_metadata_for_legacy_file(tmp_path, monkeypatch):
    """
    Simulate a legacy sidecar that was written before we had schema_name/version.
    read_sidecar() should attach schema metadata on load.
    """
    monkeypatch.setenv("QC_SCHEMA_NAME", "legacy.schema")
    monkeypatch.setenv("QC_SCHEMA_VERSION", "1")

    p = tmp_path / "legacy.qc.json"
    legacy_payload = {
        "asset_path": "/path/old.ext",
        "asset_hash": "legacyhash",
        # deliberately no schema_name/schema_version here
    }
    p.write_text(json.dumps(legacy_payload), encoding="utf-8")

    loaded = read_sidecar(p)
    assert loaded is not None

    assert loaded["asset_path"] == "/path/old.ext"
    assert loaded["asset_hash"] == "legacyhash"

    # Metadata has been injected
    assert loaded["schema_name"] == "legacy.schema"
    assert int(loaded["schema_version"]) == int(get_schema_version())
