from __future__ import annotations

from collections import Counter

from qc_asset_crawler import summary


def test_format_rollup_no_items() -> None:
    counter = Counter()
    line = summary.format_rollup(counter)
    assert line == "Summary: no items."


def test_format_rollup_single_status() -> None:
    counter = Counter({"pass": 3})
    line = summary.format_rollup(counter)
    # Should say "3 items – 3 PASS"
    assert "3 items" in line
    assert "3 PASS" in line
    # No FAIL/PENDING in there
    assert "FAIL" not in line
    assert "PENDING" not in line


def test_format_rollup_multiple_statuses_in_fixed_order() -> None:
    counter = Counter({"pass": 2, "fail": 1, "pending": 3})
    line = summary.format_rollup(counter)
    # Basic content
    assert "6 items" in line
    assert "2 PASS" in line
    assert "1 FAIL" in line
    assert "3 PENDING" in line

    # Order should be PASS, FAIL, PENDING (as per implementation)
    # Strip prefix up to the dash.
    _, _, tail = line.partition("– ")
    # Now check relative ordering
    assert tail.index("2 PASS") < tail.index("1 FAIL")
    assert tail.index("1 FAIL") < tail.index("3 PENDING")


def test_format_rollup_custom_prefix() -> None:
    counter = Counter({"pending": 2})
    line = summary.format_rollup(counter, prefix="   ")
    assert line.startswith("   ")
    assert "2 items" in line
    assert "2 PENDING" in line


def test_choose_overall_status_priority_order() -> None:
    # If any FAIL present -> FAIL
    assert (
        summary.choose_overall_status(Counter({"fail": 1, "pending": 3, "pass": 10}))
        == "fail"
    )
    assert summary.choose_overall_status(Counter({"fail": 1})) == "fail"

    # No FAIL, but PENDING present -> PENDING
    assert (
        summary.choose_overall_status(Counter({"pending": 5, "pass": 2})) == "pending"
    )

    # Only PASS -> PASS
    assert summary.choose_overall_status(Counter({"pass": 4})) == "pass"

    # Empty / unknown -> falls back to first key or 'pending'
    assert summary.choose_overall_status(Counter()) == "pending"
    assert summary.choose_overall_status(Counter({"weird": 3})) == "weird"


def test_group_key_for_sidecar_inside_qc_dir(tmp_path) -> None:
    # sidecar in .qc dir -> group by parent of .qc
    asset_dir = tmp_path / "shot_a"
    qc_dir = asset_dir / ".qc"
    qc_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = qc_dir / "file.exr.qc.json"
    sidecar_path.write_text("{}", encoding="utf-8")

    key = summary.group_key_for_sidecar(sidecar_path)
    assert key == asset_dir


def test_group_key_for_sidecar_not_in_qc_dir(tmp_path) -> None:
    # sidecar inline in same dir as asset -> group by its parent dir
    asset_dir = tmp_path / "shot_b"
    asset_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = asset_dir / "file.exr.qc.json"
    sidecar_path.write_text("{}", encoding="utf-8")

    key = summary.group_key_for_sidecar(sidecar_path)
    assert key == asset_dir
