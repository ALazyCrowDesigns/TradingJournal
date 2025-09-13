from typing import Any

import httpx

from journal.db.dao import session_scope
from journal.db.models import Symbol
from journal.services.fundamentals import hydrate_missing


def test_hydrate_missing(monkeypatch: Any) -> None:
    # seed a symbol with missing fundamentals
    with session_scope() as s:
        s.add(Symbol(symbol="FAKE"))

    def fake_get(url: str, params: dict[str, Any] | None = None, timeout: int = 30) -> Any:
        class Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self) -> list[dict[str, Any]]:
                return [{"companyName": "Fake Co", "sector": "Industrials", "industry": "Tools"}]

        return Resp()

    monkeypatch.setattr(httpx, "get", fake_get)

    # Bypass API key check by monkeypatching _enabled
    from journal.services import fundamentals as f

    monkeypatch.setattr(f, "_enabled", lambda: True)

    out = hydrate_missing(limit=10)
    assert out["updated"] >= 1
