from datetime import date
from pathlib import Path

from journal.db.dao import session_scope, upsert_symbols_float_newer
from journal.db.models import Symbol
from journal.services.floatmap import load_float_csv


def test_newer_wins(tmp_path: Path) -> None:
    # seed older value
    upsert_symbols_float_newer([{"symbol": "ZZZZ", "float": 10.0, "float_asof": date(2024, 1, 1)}])

    # load older asof -> should NOT overwrite
    csv1 = tmp_path / "float1.csv"
    csv1.write_text("symbol,float\nZZZZ,20.0\n", encoding="utf-8")
    load_float_csv(str(csv1), asof=date(2024, 1, 1))

    # load newer asof -> SHOULD overwrite
    csv2 = tmp_path / "float2.csv"
    csv2.write_text("symbol,float\nZZZZ,30.0\n", encoding="utf-8")
    load_float_csv(str(csv2), asof=date(2024, 2, 1))

    with session_scope() as s:
        obj = s.get(Symbol, "ZZZZ")
        assert obj.float == 30.0
        assert str(obj.float_asof) == "2024-02-01"
