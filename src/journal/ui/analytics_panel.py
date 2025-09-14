from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QLabel,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class AnalyticsPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.totals = QLabel("-")
        self.hitrate = QLabel("-")
        self.avg = QLabel("-")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Symbol", "Trades", "Net PnL"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)  # Enable multi-selection

        # Enable context menu for right-click operations
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_analytics_context_menu)

        lay = QVBoxLayout(self)
        lay.addWidget(self.totals)
        lay.addWidget(self.hitrate)
        lay.addWidget(self.avg)
        lay.addWidget(self.table)

    def _show_analytics_context_menu(self, position) -> None:
        """Show context menu for analytics table"""
        if not self.table.indexAt(position).isValid():
            return

        selection = self.table.selectionModel()
        selected_rows = [index.row() for index in selection.selectedRows()]

        menu = QMenu(self)

        # Add selection-based actions
        if selected_rows:
            if len(selected_rows) == 1:
                symbol_item = self.table.item(selected_rows[0], 0)
                if symbol_item:
                    symbol = symbol_item.text()
                    menu.addAction(f"Copy Symbol '{symbol}'", lambda: self._copy_symbol(symbol))
                    menu.addSeparator()
            else:
                menu.addAction(f"Copy {len(selected_rows)} Symbols", self._copy_selected_symbols)
                menu.addSeparator()

        # Always available actions
        menu.addAction("Select All", lambda: self.table.selectAll())
        menu.addAction("Copy All Data", self._copy_all_data)

        # Show menu at cursor position
        menu.exec(self.table.mapToGlobal(position))

    def _copy_symbol(self, symbol: str) -> None:
        """Copy a single symbol to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(symbol)

    def _copy_selected_symbols(self) -> None:
        """Copy selected symbols to clipboard"""
        selection = self.table.selectionModel()
        selected_rows = [index.row() for index in selection.selectedRows()]

        symbols = []
        for row in selected_rows:
            symbol_item = self.table.item(row, 0)
            if symbol_item:
                symbols.append(symbol_item.text())

        clipboard = QApplication.clipboard()
        clipboard.setText(", ".join(symbols))

    def _copy_all_data(self) -> None:
        """Copy all analytics data to clipboard as CSV"""
        lines = ["Symbol,Trades,Net PnL"]

        for row in range(self.table.rowCount()):
            row_data = []
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                row_data.append(item.text() if item else "")
            lines.append(",".join(row_data))

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(lines))

    def update_data(self, data: dict) -> None:
        t = data.get("trades", 0)
        w = data.get("wins", 0)
        losses = data.get("losses", 0)
        net = data.get("net_pnl", 0.0)
        self.totals.setText(f"Trades: {t} | Wins: {w} | Losses: {losses} | Net PnL: {net:.2f}")
        self.hitrate.setText(f"Hit Rate: {data.get('hit_rate',0.0):.1f}%")
        avg_gain = data.get("avg_gain", 0.0)
        avg_loss = data.get("avg_loss", 0.0)
        self.avg.setText(f"Avg Gain: {avg_gain:.2f} | Avg Loss: {avg_loss:.2f}")
        rows = data.get("by_symbol", [])
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r["symbol"])))
            self.table.setItem(i, 1, QTableWidgetItem(str(r["trades"])))
            self.table.setItem(i, 2, QTableWidgetItem(f"{r['net_pnl']:.2f}"))
