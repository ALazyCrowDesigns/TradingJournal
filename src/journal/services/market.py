from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..repositories.price import PriceRepository
from ..services.cache import TTLCache, cached

BASE = "https://api.polygon.io/v2"


class MarketService:
    """Service for fetching market data from external APIs"""

    def __init__(
        self,
        api_key: str | None,
        price_repository: PriceRepository,
        cache: TTLCache | None = None,
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        self._api_key = api_key
        self._price_repo = price_repository
        self._cache = cache
        self._logger = logger or structlog.get_logger()

    def _auth(self) -> dict:
        if not self._api_key:
            raise RuntimeError("Polygon API key not configured")
        return {"apiKey": self._api_key}

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=0.5, max=8),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        before_sleep=lambda retry_state: None,  # Could add logging here
    )
    def _request_with_retry(self, url: str, params: dict) -> httpx.Response:
        """Make HTTP request with automatic retry on failure"""
        with httpx.Client(timeout=30) as client:
            response = client.get(url, params=params)

            # Retry on server errors
            if response.status_code in (429, 500, 502, 503, 504):
                self._logger.warning("retryable_error", status=response.status_code, url=url)
                raise httpx.HTTPStatusError(
                    f"Retryable error: {response.status_code}",
                    request=response.request,
                    response=response,
                )

            response.raise_for_status()
            return response

    def _parse_results(self, symbol: str, results: list[dict]) -> list[dict]:
        """Parse Polygon API results into standard format"""
        rows = []
        for item in results or []:
            # Polygon returns ms epoch in "t"; normalize to UTC date
            timestamp = datetime.fromtimestamp(item["t"] / 1000, UTC).date()
            rows.append(
                {
                    "symbol": symbol,
                    "date": timestamp,
                    "o": float(item["o"]),
                    "h": float(item["h"]),
                    "low": float(item["l"]),
                    "c": float(item["c"]),
                    "v": int(item["v"]),
                }
            )
        return rows

    @cached(ttl=300, key_prefix="market_daily")  # Cache for 5 minutes
    def get_daily_range(self, symbol: str, start: date, end: date) -> list[dict]:
        """Fetch daily price data for a symbol within date range"""
        url = f"{BASE}/aggs/ticker/{symbol}/range/1/day/{start.isoformat()}/{end.isoformat()}"

        self._logger.info("fetching_daily_prices", symbol=symbol, start=start, end=end)

        response = self._request_with_retry(url, self._auth())
        data = response.json() or {}
        results = data.get("results", []) or []

        parsed = self._parse_results(symbol, results)

        self._logger.info("daily_prices_fetched", symbol=symbol, count=len(parsed))

        return parsed

    def backfill_daily(self, symbol: str, start: date, end: date) -> int:
        """Backfill daily prices for a symbol"""
        try:
            # Check what's missing first
            dates_needed = self._get_trading_days(start, end)
            missing_dates = self._price_repo.get_missing_dates(symbol, dates_needed)

            if not missing_dates:
                self._logger.info("no_missing_dates", symbol=symbol, start=start, end=end)
                return 0

            # Fetch and store
            rows = self.get_daily_range(symbol, start, end)
            if rows:
                inserted = self._price_repo.upsert_batch(rows)

                self._logger.info(
                    "backfill_complete", symbol=symbol, fetched=len(rows), inserted=inserted
                )

                return inserted

            return 0

        except Exception as e:
            self._logger.error("backfill_failed", symbol=symbol, error=str(e))
            raise

    def _get_trading_days(self, start: date, end: date) -> list[date]:
        """Get list of potential trading days between dates"""
        from datetime import timedelta

        days = []
        current = start

        while current <= end:
            # Skip weekends (simplified - doesn't account for holidays)
            if current.weekday() < 5:  # Monday = 0, Friday = 4
                days.append(current)
            current += timedelta(days=1)

        return days
