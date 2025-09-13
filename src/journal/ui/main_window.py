from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..services.floatmap import load_float_csv
from .trades_model import TradesTableModel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trading Journal")
        self.resize(1200, 700)

        # menu
        bar = QMenuBar(self)
        data_menu = bar.addMenu("&Data")
        act_load_float = data_menu.addAction("Load &Float CSV...")
        act_load_float.triggered.connect(self.on_load_float_csv)
        self.setMenuBar(bar)

        self.table = QTableView()
        self.model = TradesTableModel(
            headers=[
                "Date",
                "Symbol",
                "Side",
                "Size",
                "Entry",
                "Exit",
                "PnL",
                "%Ret",
                "PrevClose",
                "Open",
                "High",
                "Low",
                "Close",
                "Vol",
            ],
            rows=[],
        )
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)

        container = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(self.table)
        container.setLayout(layout)
        self.setCentralWidget(container)

    def on_load_float_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Float CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        # For now, use today's date as asof
        try:
            n = load_float_csv(path, asof=date.today())
            QMessageBox.information(self, "Float Loader", f"Float upserts attempted: {n}")
        except Exception as e:
            QMessageBox.critical(self, "Float Loader", f"Error: {e}")


def run_gui() -> None:
    import sys

    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
