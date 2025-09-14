"""
Enhanced table model that supports editing with session-based transaction management.
Extends the existing TradesTableModel with CRUD capabilities.
"""

from __future__ import annotations

from collections import deque
from datetime import date
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor

from ..repositories.trade import TradeRepository
from ..services.session_manager import SessionTransactionManager
from .repository import HEADERS, INDEX_TO_KEY


class EditableTradesModel(QAbstractTableModel):
    """
    Enhanced trades table model with editing capabilities and session management.
    Supports inline editing, validation, and visual indicators for changed data.
    """

    # Signals for UI updates
    dataChanged = Signal()
    sessionChanged = Signal()

    def __init__(
        self,
        trade_repository: TradeRepository,
        session_manager: SessionTransactionManager,
        page_size: int = 100,
    ) -> None:
        super().__init__()
        self._trade_repo = trade_repository
        self._session_manager = session_manager
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
        self._cache_size = 1000
        self._cache_queue: deque[int] = deque(maxlen=self._cache_size)

        # Track row states for visual indicators
        self._row_states: dict[int, str] = (
            {}
        )  # row_index -> state ('created', 'modified', 'deleted')
        self._trade_id_to_row: dict[str, int] = {}  # trade_id -> row_index

        # Connect to session manager for updates
        self._session_manager.add_change_callback(self._on_session_changed)

    def _on_session_changed(self) -> None:
        """Called when session data changes"""
        self.reload(reset=True)
        self.sessionChanged.emit()

    # --- Qt Model Interface ---

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is None:
            parent = QModelIndex()
        return len(self.rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        if parent is None:
            parent = QModelIndex()
        return len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None

        row_idx = index.row()
        col_idx = index.column()

        if role in (Qt.DisplayRole, Qt.EditRole):
            # Try cache first
            if row_idx in self._row_cache:
                val = self._row_cache[row_idx][col_idx]
            else:
                val = self.rows[row_idx][col_idx]
                # Cache the row for future access
                self._update_cache(row_idx, self.rows[row_idx])

            return "" if val is None else val

        elif role == Qt.BackgroundRole:
            # Color coding for different row states
            if row_idx in self._row_states:
                state = self._row_states[row_idx]
                if state == "created":
                    return QBrush(QColor(200, 255, 200))  # Light green for new
                elif state == "modified":
                    return QBrush(QColor(255, 255, 200))  # Light yellow for modified
                elif state == "deleted":
                    return QBrush(QColor(255, 200, 200))  # Light red for deleted

        elif role == Qt.ToolTipRole:
            if row_idx in self._row_states:
                state = self._row_states[row_idx]
                if state == "created":
                    return "New trade (not yet committed to database)"
                elif state == "modified":
                    return "Modified trade (changes not yet committed)"
                elif state == "deleted":
                    return "Deleted trade (will be removed on commit)"

        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:
        """Handle data editing"""
        if not index.isValid() or role != Qt.EditRole:
            return False

        row_idx = index.row()
        col_idx = index.column()

        if row_idx >= len(self.rows) or col_idx >= len(self.headers):
            return False

        # Get the field name
        field_name = INDEX_TO_KEY[col_idx]

        # Get the trade ID from the row
        trade_id = (
            self.rows[row_idx][0] if self.rows[row_idx] else None
        )  # Assuming ID is first column
        if not trade_id:
            return False

        # Validate the input
        if not self._validate_field_value(field_name, value):
            return False

        # Convert value to appropriate type
        converted_value = self._convert_field_value(field_name, value)

        # Update through session manager
        success = self._session_manager.update_trade(str(trade_id), {field_name: converted_value})

        if success:
            # Update local cache
            self.rows[row_idx][col_idx] = converted_value
            if row_idx in self._row_cache:
                self._row_cache[row_idx][col_idx] = converted_value

            # Mark row as modified
            self._row_states[row_idx] = "modified"

            # Emit data changed signal
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.BackgroundRole, Qt.ToolTipRole])
            return True

        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        """Define which cells are editable"""
        if not index.isValid():
            return Qt.NoItemFlags

        col_idx = index.column()
        field_name = INDEX_TO_KEY[col_idx]

        # Make most fields editable except computed ones
        non_editable_fields = {"id", "created_at", "return_pct"}  # Add computed fields here

        if field_name in non_editable_fields:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable
        else:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        return None

    # --- Validation and Conversion ---

    def _validate_field_value(self, field_name: str, value: Any) -> bool:
        """Validate field values before setting"""
        if field_name == "symbol":
            return isinstance(value, str) and len(value.strip()) > 0
        elif field_name == "side":
            return value in ["LONG", "SHORT", "BUY", "SELL"]
        elif field_name in ["size"]:
            try:
                int_val = int(value)
                return int_val > 0
            except (ValueError, TypeError):
                return False
        elif field_name in ["entry", "exit", "pnl", "prev_close"]:
            try:
                float(value)
                return True
            except (ValueError, TypeError):
                return False
        elif field_name == "trade_date":
            if isinstance(value, date):
                return True
            elif isinstance(value, str):
                try:
                    date.fromisoformat(value)
                    return True
                except ValueError:
                    return False

        return True  # Default to valid for other fields

    def _convert_field_value(self, field_name: str, value: Any) -> Any:
        """Convert field values to appropriate types"""
        if field_name == "symbol" or field_name == "side":
            return str(value).upper().strip()
        elif field_name == "size":
            return int(value)
        elif field_name in ["entry", "exit", "pnl", "prev_close"]:
            return float(value)
        elif field_name == "trade_date":
            if isinstance(value, str):
                return date.fromisoformat(value)
            return value
        elif field_name == "notes":
            return str(value) if value is not None else None

        return value

    # --- CRUD Operations ---

    def create_trade(self, trade_data: dict[str, Any] | None = None) -> str:
        """Create a new trade"""
        if trade_data is None:
            trade_data = {
                "symbol": "NEW",
                "side": "LONG",
                "size": 100,
                "entry": 0.0,
                "exit": 0.0,
                "pnl": 0.0,
                "trade_date": date.today(),
            }

        trade_id = self._session_manager.create_trade(trade_data)

        # Reload to show the new trade
        self.reload(reset=True)

        return trade_id

    def delete_selected_trades(self, selected_rows: list[int]) -> int:
        """Delete multiple selected trades"""
        deleted_count = 0

        for row_idx in sorted(selected_rows, reverse=True):  # Delete from bottom up
            if row_idx < len(self.rows):
                trade_id = self.rows[row_idx][0]  # Assuming ID is first column
                if self._session_manager.delete_trade(str(trade_id)):
                    deleted_count += 1

        if deleted_count > 0:
            self.reload(reset=True)

        return deleted_count

    def duplicate_trade(self, row_idx: int) -> str | None:
        """Duplicate a trade"""
        if row_idx >= len(self.rows):
            return None

        # Get original trade data
        trade_id = self.rows[row_idx][0]
        original_trade = self._session_manager.get_trade(str(trade_id))

        if not original_trade:
            return None

        # Create duplicate with new ID and today's date
        duplicate_data = original_trade.copy()
        duplicate_data.pop("id", None)  # Remove ID so new one is generated
        duplicate_data["trade_date"] = date.today()

        new_trade_id = self._session_manager.create_trade(duplicate_data)
        self.reload(reset=True)

        return new_trade_id

    # --- Sorting ---

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:
        key = INDEX_TO_KEY[column]
        self.order_by = key
        self.order_dir = "desc" if order == Qt.DescendingOrder else "asc"
        self.reload(reset=True)

    # --- Pagination ---

    def canFetchMore(self, parent: QModelIndex | None = None) -> bool:
        if parent is None:
            parent = QModelIndex()
        return self.rowCount() < self.total

    def fetchMore(self, parent: QModelIndex | None = None) -> None:
        if parent is None:
            parent = QModelIndex()
        if not self.canFetchMore(parent) or self._pending_fetch:
            return

        self._pending_fetch = True
        self._fetch_timer.stop()
        self._fetch_timer.start(200)

    def _do_fetch_more(self) -> None:
        """Actually perform the fetch operation"""
        self._pending_fetch = False
        self.offset += self.page_size

        # Get data from session manager instead of directly from repository
        session_trades = self._session_manager.get_all_trades(filters=self.filters)

        # Convert to row format and apply pagination
        data = self._trades_to_rows(session_trades[self.offset : self.offset + self.page_size])

        if data:
            start_idx = len(self.rows)
            self.beginInsertRows(QModelIndex(), start_idx, start_idx + len(data) - 1)
            self.rows.extend(data)

            # Update row cache
            for i, row in enumerate(data):
                row_idx = start_idx + i
                self._update_cache(row_idx, row)

            self.endInsertRows()

    def _trades_to_rows(self, trades: list[dict[str, Any]]) -> list[list[Any]]:
        """Convert trade dictionaries to row data"""
        rows = []

        for trade in trades:
            row = [
                trade.get("id"),
                trade.get("trade_date").strftime("%Y-%m-%d") if trade.get("trade_date") else "",
                trade.get("symbol", ""),
                trade.get("side", ""),
                trade.get("size"),
                trade.get("entry"),
                trade.get("exit"),
                trade.get("pnl"),
                trade.get("return_pct"),
                trade.get("prev_close"),
                None,  # Open price (would need to be fetched)
                None,  # High price
                None,  # Low price
                None,  # Close price
                None,  # Volume
                None,  # Gap %
                None,  # Range %
                None,  # Close change %
            ]
            rows.append(row)

        return rows

    def _update_cache(self, row_idx: int, row_data: list[Any]) -> None:
        """Update row cache with LRU eviction"""
        if row_idx in self._row_cache:
            self._cache_queue.remove(row_idx)
        elif len(self._cache_queue) >= self._cache_size:
            oldest = self._cache_queue.popleft()
            del self._row_cache[oldest]

        self._row_cache[row_idx] = row_data
        self._cache_queue.append(row_idx)

    # --- Filters ---

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
            self._row_states.clear()
            self._trade_id_to_row.clear()
            self.endResetModel()

        # Get data from session manager
        session_trades = self._session_manager.get_all_trades(filters=self.filters)

        # Apply sorting
        if self.order_by and session_trades:
            reverse_order = self.order_dir == "desc"
            try:
                session_trades.sort(key=lambda x: x.get(self.order_by) or 0, reverse=reverse_order)
            except (TypeError, KeyError):
                pass  # Skip sorting if field doesn't exist or can't be compared

        # Convert to row format
        data = self._trades_to_rows(session_trades[: self.page_size])

        self.beginResetModel()
        self.rows = data or []
        self.total = len(session_trades)

        # Update row state tracking
        for i, row in enumerate(self.rows):
            trade_id = str(row[0]) if row[0] else None
            if trade_id:
                self._trade_id_to_row[trade_id] = i
                # Determine row state based on session manager
                # This is simplified - you might want more sophisticated state tracking
                if trade_id in self._session_manager._session_trades:
                    if trade_id in self._session_manager._original_trades:
                        self._row_states[i] = "modified"
                    else:
                        self._row_states[i] = "created"
                elif trade_id in self._session_manager._deleted_trades:
                    self._row_states[i] = "deleted"

        self.endResetModel()

    # --- Session Management ---

    def save_session(self) -> dict[str, int]:
        """Save the current session state"""
        return self._session_manager.save()

    def commit_session(self) -> dict[str, int]:
        """Commit all changes to database"""
        result = self._session_manager.commit()
        if result.get("errors", 0) == 0:
            # Reload from database after successful commit
            self.reload(reset=True)
        return result

    def rollback_session(self) -> None:
        """Rollback all session changes"""
        self._session_manager.rollback()
        self.reload(reset=True)

    def undo(self) -> str | None:
        """Undo last operation"""
        result = self._session_manager.undo()
        if result:
            self.reload(reset=True)
        return result

    def redo(self) -> str | None:
        """Redo last undone operation"""
        result = self._session_manager.redo()
        if result:
            self.reload(reset=True)
        return result

    def can_undo(self) -> bool:
        return self._session_manager.can_undo()

    def can_redo(self) -> bool:
        return self._session_manager.can_redo()

    def has_unsaved_changes(self) -> bool:
        return self._session_manager.has_unsaved_changes()

    def get_session_info(self) -> dict[str, Any]:
        return self._session_manager.get_session_info()
