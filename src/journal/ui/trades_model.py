from __future__ import annotations

from collections import deque
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer

from ..repositories.trade import TradeRepository
from .repository import HEADERS, INDEX_TO_KEY


class TradesTableModel(QAbstractTableModel):
    def __init__(self, trade_repository: TradeRepository, page_size: int = 100) -> None:
        super().__init__()
        self._trade_repo = trade_repository
        self.headers = HEADERS
        self.rows: list[list[Any]] = []
        self.total = 0
        self.page_size = page_size

        self.filters: dict | None = None
        self.order_by: str = "trade_date"
        self.order_dir: str = "desc"
        self.offset = 0

        # Performance optimizations
        self._fetch_timer = QTimer(self)  # Set parent to avoid threading issues
        self._fetch_timer.setSingleShot(True)
        self._fetch_timer.timeout.connect(self._do_fetch_more)
        self._pending_fetch = False

        # Row cache for virtual scrolling
        self._row_cache: dict[int, list[Any]] = {}
        self._cache_size = 1000  # Cache up to 1000 rows
        self._cache_queue: deque[int] = deque(maxlen=self._cache_size)

    # --- data/structure ---
    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is None:
            parent = QModelIndex()
        return len(self.rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        if parent is None:
            parent = QModelIndex()
        return len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole):
            return None

        row_idx = index.row()
        col_idx = index.column()

        # Try cache first
        if row_idx in self._row_cache:
            val = self._row_cache[row_idx][col_idx]
        else:
            val = self.rows[row_idx][col_idx]
            # Cache the row for future access
            self._update_cache(row_idx, self.rows[row_idx])

        return "" if val is None else val

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        return None

    # --- sorting ---
    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:
        key = INDEX_TO_KEY[column]
        self.order_by = key
        self.order_dir = "desc" if order == Qt.DescendingOrder else "asc"
        self.reload(reset=True)

    # --- pagination ---
    def canFetchMore(self, parent: QModelIndex | None = None) -> bool:
        if parent is None:
            parent = QModelIndex()
        return self.rowCount() < self.total

    def fetchMore(self, parent: QModelIndex | None = None) -> None:
        if parent is None:
            parent = QModelIndex()
        if not self.canFetchMore(parent) or self._pending_fetch:
            return

        # Debounce fetching to avoid rapid successive calls
        self._pending_fetch = True
        self._fetch_timer.stop()
        self._fetch_timer.start(200)  # 200ms debounce to reduce startup queries

    def _do_fetch_more(self) -> None:
        """Actually perform the fetch operation"""
        self._pending_fetch = False
        self.offset += self.page_size

        # Fetch data from repository with prices
        trades_with_prices, total = self._trade_repo.get_paginated_with_prices(
            limit=self.page_size,
            offset=self.offset,
            order_by=self.order_by,
            order_dir=self.order_dir,
            filters=self.filters,
        )

        # Convert trades to row data
        data = self._trades_with_prices_to_rows(trades_with_prices)

        if data:
            start_idx = len(self.rows)
            self.beginInsertRows(QModelIndex(), start_idx, start_idx + len(data) - 1)
            self.rows.extend(data)

            # Update row cache
            for i, row in enumerate(data):
                row_idx = start_idx + i
                self._update_cache(row_idx, row)

            self.endInsertRows()
        self.total = total

    def _trades_with_prices_to_rows(self, trades_with_prices: list[tuple]) -> list[list[Any]]:
        """Convert Trade and DailyPrice data tuples to row data without additional queries"""
        rows = []

        for trade_data, price_data in trades_with_prices:
            # Access trade attributes from dictionary
            trade_date = trade_data['trade_date']
            symbol = trade_data['symbol']
            side = trade_data['side']
            size = trade_data['size']
            entry = trade_data['entry']
            exit = trade_data['exit']
            pnl = trade_data['pnl']
            return_pct = trade_data['return_pct']
            prev_close = trade_data['prev_close']

            # Calculate derived fields
            gap_pct = None
            range_pct = None
            closechg_pct = None

            if price_data and prev_close:
                gap_pct = (price_data['o'] - prev_close) / prev_close * 100
                if price_data['low'] > 0:
                    range_pct = (price_data['h'] - price_data['low']) / price_data['low'] * 100
                closechg_pct = (price_data['c'] - prev_close) / prev_close * 100

            row = [
                trade_date.strftime('%Y-%m-%d') if trade_date else '',
                symbol,
                side,
                size,
                entry,
                exit,
                pnl,
                return_pct,
                prev_close,
                price_data['o'] if price_data else None,
                price_data['h'] if price_data else None,
                price_data['low'] if price_data else None,
                price_data['c'] if price_data else None,
                price_data['v'] if price_data else None,
                gap_pct,
                range_pct,
                closechg_pct,
            ]
            rows.append(row)

        return rows

    def _trades_to_rows(self, trades: list) -> list[list[Any]]:
        """Convert Trade objects to row data (deprecated - use _trades_with_prices_to_rows)"""
        from ..db.models import DailyPrice

        rows = []

        # Process trades within a single session to avoid detached instance errors
        with self._trade_repo._session_scope() as session:
            from sqlalchemy import and_, select

            for trade in trades:
                # Merge the trade into the current session to access its attributes
                merged_trade = session.merge(trade)
                
                # Access trade attributes from the merged object
                trade_date = merged_trade.trade_date
                symbol = merged_trade.symbol
                side = merged_trade.side
                size = merged_trade.size
                entry = merged_trade.entry
                exit = merged_trade.exit
                pnl = merged_trade.pnl
                return_pct = merged_trade.return_pct
                prev_close = merged_trade.prev_close

                # Get associated daily price if available
                price = session.scalar(
                    select(DailyPrice).where(
                        and_(DailyPrice.symbol == symbol, DailyPrice.date == trade_date)
                    )
                )

                # Calculate derived fields
                gap_pct = None
                range_pct = None
                closechg_pct = None

                if price and prev_close:
                    gap_pct = (price.o - prev_close) / prev_close * 100
                    if price.low > 0:
                        range_pct = (price.h - price.low) / price.low * 100
                    closechg_pct = (price.c - prev_close) / prev_close * 100

                row = [
                    trade_date.strftime('%Y-%m-%d') if trade_date else '',
                    symbol,
                    side,
                    size,
                    entry,
                    exit,
                    pnl,
                    return_pct,
                    prev_close,
                    price.o if price else None,
                    price.h if price else None,
                    price.low if price else None,
                    price.c if price else None,
                    price.v if price else None,
                    gap_pct,
                    range_pct,
                    closechg_pct,
                ]
                rows.append(row)

        return rows

    def _update_cache(self, row_idx: int, row_data: list[Any]) -> None:
        """Update row cache with LRU eviction"""
        if row_idx in self._row_cache:
            # Move to end
            self._cache_queue.remove(row_idx)
        elif len(self._cache_queue) >= self._cache_size:
            # Evict oldest
            oldest = self._cache_queue.popleft()
            del self._row_cache[oldest]

        self._row_cache[row_idx] = row_data
        self._cache_queue.append(row_idx)

    # --- filters ---
    def setFilters(self, filters: dict | None) -> None:
        self.filters = filters or {}
        self.reload(reset=True)

    def reload(self, reset: bool = False) -> None:
        if reset:
            self.beginResetModel()
            self.rows.clear()
            self.offset = 0
            self._row_cache.clear()
            self._cache_queue.clear()
            self.endResetModel()

        # Fetch fresh data with prices
        trades_with_prices, total = self._trade_repo.get_paginated_with_prices(
            limit=self.page_size,
            offset=self.offset,
            order_by=self.order_by,
            order_dir=self.order_dir,
            filters=self.filters,
        )

        data = self._trades_with_prices_to_rows(trades_with_prices)

        self.beginResetModel()
        self.rows = data or []
        self.total = total
        self.endResetModel()
