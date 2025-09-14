from datetime import date
from typing import Any

import httpx

from journal.db.dao import _mk_engine
from journal.repositories.price import PriceRepository
from journal.services.market import MarketService


class Flip:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self, *a: Any, **k: Any) -> httpx.Response:
        self.n += 1
        if self.n < 3:
            # first two calls simulate 429
            r = httpx.Response(429, request=httpx.Request("GET", "http://x"))
            raise httpx.HTTPStatusError("retry", request=r.request, response=r)
        # success
        data = {"results": [{"t": 1704067200000, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000}]}
        return httpx.Response(200, json=data, request=httpx.Request("GET", "http://x"))


def test_retries(monkeypatch: Any) -> None:
    f = Flip()
    monkeypatch.setattr(httpx, "get", f)

    # Create service instance with fake API key and price repository
    engine = _mk_engine()
    price_repo = PriceRepository(engine)
    service = MarketService(api_key="fake_key", price_repository=price_repo)

    rows = service.get_daily_range("ABCD", date(2024, 1, 1), date(2024, 1, 1))
    assert len(rows) == 1
