from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMainWindow, QTableView, QVBoxLayout, QWidget

from .trades_model import TradesTableModel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trading Journal")
        self.resize(1200, 700)

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


def run_gui() -> None:
    import sys

    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
