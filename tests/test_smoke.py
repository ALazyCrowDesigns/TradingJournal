from journal.db.models import DailyPrice, Symbol, Trade


def test_models_exist() -> None:
    assert hasattr(Symbol, "__tablename__")
    assert hasattr(Trade, "__tablename__")
    assert hasattr(DailyPrice, "__tablename__")
