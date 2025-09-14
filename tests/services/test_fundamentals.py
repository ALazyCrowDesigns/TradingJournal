from typing import Any

import httpx

from journal.db.dao import _mk_engine, session_scope
from journal.db.models import Symbol
from journal.repositories.symbol import SymbolRepository
from journal.services.fundamentals import FundamentalsService


def test_hydrate_missing(monkeypatch: Any) -> None:
    # seed a symbol with missing fundamentals
    import uuid

    test_symbol = f"TEST{uuid.uuid4().hex[:8].upper()}"
    with session_scope() as s:
        s.add(Symbol(symbol=test_symbol))

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
            class Resp:
                status_code = 200

                def raise_for_status(self) -> None:
                    pass

                def json(self) -> list[dict[str, Any]]:
                    return [
                        {"companyName": "Fake Co", "sector": "Industrials", "industry": "Tools"}
                    ]

            return Resp()

    monkeypatch.setattr(httpx, "Client", MockClient)

    # Create service instance with fake API key and symbol repository
    engine = _mk_engine()
    symbol_repo = SymbolRepository(engine)
    service = FundamentalsService(api_key="fake_key", symbol_repository=symbol_repo)

    out = service.hydrate_missing(limit=10)
    assert out["updated"] >= 1
