from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QVBoxLayout

from .repository import COLUMNS


class ColumnsDialog(QDialog):
    def __init__(self, visible: list[str]) -> None:
        super().__init__()
        self.setWindowTitle("Choose Columns")
        self.list = QListWidget()
        for key, title in COLUMNS:
            it = QListWidgetItem(title)
            it.setCheckState(2 if key in visible else 0)
            it.setData(32, key)  # Qt.UserRole
            self.list.addItem(it)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.list)
        lay.addWidget(btns)

    def selected_keys(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == 2:
                out.append(it.data(32))
        return out
