from pathlib import Path

from journal.ingest.tradersync import load_tradersync_csv


def test_idempotent(tmp_path: Path) -> None:
    # Use a temp copy so test is hermetic
    csv_src = Path("tests/data/tradersync_good.csv")
    csv_dst = tmp_path / "good.csv"
    csv_dst.write_text(csv_src.read_text(encoding="utf-8"), encoding="utf-8")

    map_src = Path("src/journal/ingest/mapping.tradersync.json")
    map_dst = tmp_path / "mapping.json"
    map_dst.write_text(map_src.read_text(encoding="utf-8"), encoding="utf-8")

    # Use a unique profile ID to avoid conflicts with existing test data
    import time

    unique_profile_id = int(time.time() * 1000) % 10000  # Use timestamp for uniqueness

    s1 = load_tradersync_csv(
        csv_dst, profile_id=unique_profile_id, mapping_path=map_dst, dry_run=False
    )
    s2 = load_tradersync_csv(
        csv_dst, profile_id=unique_profile_id, mapping_path=map_dst, dry_run=False
    )

    # First run inserts all rows, second run inserts zero
    assert s1["inserted"] > 0
    assert s2["inserted"] == 0
    assert s2["duplicates_skipped"] >= s1["inserted"]
