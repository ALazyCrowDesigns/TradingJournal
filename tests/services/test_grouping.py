from datetime import date, timedelta


def _group_contiguous(dates: list[date]) -> list[tuple[date, date]]:
    """Helper function for grouping contiguous dates (moved from deleted backfill service)"""
    if not dates:
        return []
    ds = sorted(set(dates))
    spans: list[tuple[date, date]] = []
    start = prev = ds[0]
    for d in ds[1:]:
        if (d - prev).days == 1:
            prev = d
            continue
        spans.append((start, prev))
        start = prev = d
    spans.append((start, prev))
    return spans


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
