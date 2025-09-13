from datetime import date, timedelta

from journal.services.backfill import _group_contiguous


def test_group_contiguous_ranges() -> None:
    d = date(2024, 1, 1)
    dates = [
        d,
        d + timedelta(days=1),
        d + timedelta(days=3),
        d + timedelta(days=4),
        d + timedelta(days=6),
    ]
    spans = _group_contiguous(dates)
    assert spans == [
        (d, d + timedelta(days=1)),
        (d + timedelta(days=3), d + timedelta(days=4)),
        (d + timedelta(days=6), d + timedelta(days=6)),
    ]
