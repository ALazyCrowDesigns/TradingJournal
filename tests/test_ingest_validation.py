from pathlib import Path

from journal.ingest.tradersync import load_tradersync_csv


def test_bad_rows_logged(tmp_path: Path) -> None:
    csv_src = Path("tests/data/tradersync_bad.csv")
    csv_dst = tmp_path / "bad.csv"
    csv_dst.write_text(csv_src.read_text(encoding="utf-8"), encoding="utf-8")

    map_src = Path("src/journal/ingest/mapping.tradersync.json")
    map_dst = tmp_path / "mapping.json"
    map_dst.write_text(map_src.read_text(encoding="utf-8"), encoding="utf-8")

    # Use a unique profile ID to avoid conflicts with existing test data
    import time

    unique_profile_id = int(time.time() * 1000) % 10000  # Use timestamp for uniqueness

    s = load_tradersync_csv(
        csv_dst, profile_id=unique_profile_id, mapping_path=map_dst, dry_run=True
    )
    # Expect errors for bad rows in dry-run; no insert performed
    assert s["errors"] >= 1
