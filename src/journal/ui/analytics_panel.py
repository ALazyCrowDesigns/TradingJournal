from __future__ import annotations

from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
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

        lay = QVBoxLayout(self)
        lay.addWidget(self.totals)
        lay.addWidget(self.hitrate)
        lay.addWidget(self.avg)
        lay.addWidget(self.table)

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
