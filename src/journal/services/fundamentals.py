from __future__ import annotations

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from ..repositories.symbol import SymbolRepository
from ..services.cache import TTLCache, cached

FMP_BASE = "https://financialmodelingprep.com/api/v3/profile"


class FundamentalsService:
    """Service for fetching fundamental data from FMP API"""

    def __init__(
        self,
        api_key: str | None,
        symbol_repository: SymbolRepository,
        cache: TTLCache | None = None,
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        self._api_key = api_key
        self._symbol_repo = symbol_repository
        self._cache = cache
        self._logger = logger or structlog.get_logger()

    def _enabled(self) -> bool:
        """Check if service is enabled"""
        return bool(self._api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    @cached(ttl=3600, key_prefix="fundamentals")  # Cache for 1 hour
    def _fetch_profile(self, symbol: str) -> dict | None:
        """Fetch company profile from FMP API"""
        url = f"{FMP_BASE}/{symbol}"

        with httpx.Client(timeout=30) as client:
            response = client.get(url, params={"apikey": self._api_key})
            response.raise_for_status()

            data = response.json() or []
            if not data:
                self._logger.warning("no_profile_data", symbol=symbol)
                return None

            profile = data[0]
            return {
                "symbol": symbol,
                "name": profile.get("companyName"),
                "sector": profile.get("sector"),
                "industry": profile.get("industry"),
            }

    def hydrate_missing(self, limit: int | None = None) -> dict:
        """Fetch and update missing fundamental data for symbols"""
        if not self._enabled():
            self._logger.info("fundamentals_service_disabled")
            return {"skipped": True, "updated": 0, "reason": "FMP API key not configured"}

        symbols = self._symbol_repo.get_missing_fundamentals(limit=limit)

        self._logger.info("hydrating_fundamentals", count=len(symbols), limit=limit)

        updated = 0
        errors = 0
        profiles_to_update = []

        # Fetch all profiles first
        for symbol in symbols:
            try:
                profile = self._fetch_profile(symbol)
                if profile:
                    profiles_to_update.append(profile)
                    self._logger.debug("symbol_fetched", symbol=symbol, name=profile.get("name"))
            except Exception as e:
                errors += 1
                self._logger.warning("fetch_failed", symbol=symbol, error=str(e))
                # Continue processing other symbols

        # Batch update all profiles at once
        if profiles_to_update:
            try:
                self._symbol_repo.update_fundamentals(profiles_to_update)
                updated = len(profiles_to_update)
                self._logger.info("batch_updated", count=updated)
            except Exception as e:
                errors += len(profiles_to_update)
                self._logger.error("batch_update_failed", error=str(e))

        self._logger.info("hydration_complete", updated=updated, errors=errors, total=len(symbols))

        return {"skipped": False, "updated": updated, "errors": errors, "total": len(symbols)}

    @cached(ttl=300, key_prefix="fundamentals")
    def get_sector_overview(self) -> dict[str, int]:
        """Get count of symbols by sector using SQL aggregation"""
        with self._symbol_repo._session_scope() as session:
            from sqlalchemy import func, select

            from ..db.models import Symbol

            query = (
                select(Symbol.sector, func.count(Symbol.symbol).label("count"))
                .where(Symbol.sector.isnot(None))
                .group_by(Symbol.sector)
                .order_by(func.count(Symbol.symbol).desc())
            )

            results = session.execute(query).all()
            return {row.sector: row.count for row in results}

    @cached(ttl=300, key_prefix="fundamentals")
    def get_industry_overview(self) -> dict[str, int]:
        """Get count of symbols by industry using SQL aggregation"""
        with self._symbol_repo._session_scope() as session:
            from sqlalchemy import func, select

            from ..db.models import Symbol

            query = (
                select(Symbol.industry, func.count(Symbol.symbol).label("count"))
                .where(Symbol.industry.isnot(None))
                .group_by(Symbol.industry)
                .order_by(func.count(Symbol.symbol).desc())
            )

            results = session.execute(query).all()
            return {row.industry: row.count for row in results}
