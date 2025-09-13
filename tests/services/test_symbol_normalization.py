from datetime import date
from pathlib import Path

from journal.db.dao import session_scope
from journal.db.models import Symbol
from journal.services.floatmap import load_float_csv


def test_symbol_upper_trim(tmp_path: Path) -> None:
    csvp = tmp_path / "float.csv"
    csvp.write_text("symbol,float\n aapl , 12345 \n", encoding="utf-8")
    load_float_csv(str(csvp), asof=date(2024, 6, 30))
    with session_scope() as s:
        assert s.get(Symbol, "AAPL") is not None
