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
        self._fetch_timer = QTimer()
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
        self._fetch_timer.start(50)  # 50ms debounce

    def _do_fetch_more(self) -> None:
        """Actually perform the fetch operation"""
        self._pending_fetch = False
        self.offset += self.page_size

        # Fetch data from repository
        trades, total = self._trade_repo.get_paginated(
            limit=self.page_size,
            offset=self.offset,
            order_by=self.order_by,
            order_dir=self.order_dir,
            filters=self.filters,
        )

        # Convert trades to row data
        data = self._trades_to_rows(trades)

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

    def _trades_to_rows(self, trades: list) -> list[list[Any]]:
        """Convert Trade objects to row data"""
        from ..db.models import DailyPrice

        rows = []

        for trade in trades:
            # Get associated daily price if available
            with self._trade_repo._session_scope() as session:
                from sqlalchemy import and_, select

                price = session.scalar(
                    select(DailyPrice).where(
                        and_(DailyPrice.symbol == trade.symbol, DailyPrice.date == trade.trade_date)
                    )
                )

            # Calculate derived fields
            gap_pct = None
            range_pct = None
            closechg_pct = None

            if price and trade.prev_close:
                gap_pct = (price.o - trade.prev_close) / trade.prev_close * 100
                if price.low > 0:
                    range_pct = (price.h - price.low) / price.low * 100
                closechg_pct = (price.c - trade.prev_close) / trade.prev_close * 100

            row = [
                trade.trade_date,
                trade.symbol,
                trade.side,
                trade.size,
                trade.entry,
                trade.exit,
                trade.pnl,
                trade.return_pct,
                trade.prev_close,
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

        # Fetch fresh data
        trades, total = self._trade_repo.get_paginated(
            limit=self.page_size,
            offset=self.offset,
            order_by=self.order_by,
            order_dir=self.order_dir,
            filters=self.filters,
        )

        data = self._trades_to_rows(trades)

        self.beginResetModel()
        self.rows = data or []
        self.total = total
        self.endResetModel()
