"""
Symbol repository implementation
"""

from __future__ import annotations

from sqlalchemy import Engine, or_, select

from ..db.models import Symbol
from ..dto import SymbolIn
from ..services.cache import TTLCache
from .base import BaseRepository


class SymbolRepository(BaseRepository[Symbol]):
    """Repository for Symbol entities"""

    def __init__(self, engine: Engine, cache: TTLCache | None = None) -> None:
        super().__init__(engine, Symbol)
        self._cache = cache

    def upsert(self, symbol_data: dict) -> Symbol:
        """Upsert a symbol (update if exists, insert if not)"""
        symbol_key = (symbol_data.get("symbol") or "").upper()
        if not symbol_key:
            raise ValueError("Symbol key is required")

        with self._session_scope() as session:
            existing = session.get(Symbol, symbol_key)

            if existing:
                # Update existing
                for key, value in symbol_data.items():
                    setattr(existing, key, value)
                symbol = existing
            else:
                # Create new
                symbol = Symbol(**symbol_data)
                session.add(symbol)

            session.flush()
            session.refresh(symbol)

            # Invalidate cache
            if self._cache:
                self._cache.invalidate_prefix(f"symbol:{symbol_key}")

            return symbol

    def upsert_many(self, symbols: list[dict] | list[SymbolIn]) -> list[Symbol]:
        """Upsert multiple symbols"""
        results = []

        with self._session_scope() as session:
            for item in symbols:
                  data = item.model_dump() if isinstance(item, SymbolIn) else item

                symbol_key = (data.get("symbol") or "").upper()
                if not symbol_key:
                    continue

                existing = session.get(Symbol, symbol_key)

                if existing:
                    for key, value in data.items():
                        setattr(existing, key, value)
                    results.append(existing)
                else:
                    symbol = Symbol(**data)
                    session.add(symbol)
                    results.append(symbol)

            session.flush()

            # Invalidate caches
            if self._cache:
                for symbol in results:
                    self._cache.invalidate_prefix(f"symbol:{symbol.symbol}")

        return results

    def get_missing_fundamentals(self, limit: int | None = None) -> list[str]:
        """Get symbols missing fundamental data"""
        with self._session_scope() as session:
            query = select(Symbol.symbol).where(
                or_(Symbol.name.is_(None), Symbol.sector.is_(None), Symbol.industry.is_(None))
            )

            if limit:
                query = query.limit(limit)

            return list(session.scalars(query).all())

    def update_fundamentals(self, symbol_data: list[dict]) -> int:
        """Update fundamental data for symbols"""
        updated = 0

        with self._session_scope() as session:
            for data in symbol_data:
                symbol_key = data.get("symbol")
                if not symbol_key:
                    continue

                symbol = session.get(Symbol, symbol_key)
                if symbol:
                    if name := data.get("name"):
                        symbol.name = name
                    if sector := data.get("sector"):
                        symbol.sector = sector
                    if industry := data.get("industry"):
                        symbol.industry = industry
                    updated += 1

            session.flush()

            # Invalidate caches
            if self._cache and updated > 0:
                self._cache.invalidate_prefix("symbol:")

        return updated

    def get_by_sector(self, sector: str) -> list[Symbol]:
        """Get all symbols in a specific sector"""
        with self._session_scope() as session:
            query = select(Symbol).where(Symbol.sector == sector)
            return list(session.scalars(query).all())

    def get_by_industry(self, industry: str) -> list[Symbol]:
        """Get all symbols in a specific industry"""
        with self._session_scope() as session:
            query = select(Symbol).where(Symbol.industry == industry)
            return list(session.scalars(query).all())

    def search(self, term: str) -> list[Symbol]:
        """Search symbols by symbol code or name"""
        with self._session_scope() as session:
            query = select(Symbol).where(
                or_(Symbol.symbol.ilike(f"%{term}%"), Symbol.name.ilike(f"%{term}%"))
            )
            return list(session.scalars(query).all())
