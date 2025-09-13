from __future__ import annotations

import csv
import os
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QRunnable, QThread, QThreadPool, Signal, pyqtSlot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..container import ApplicationContainer
from .analytics_panel import AnalyticsPanel
from .columns_dialog import ColumnsDialog
from .prefs import load_prefs, save_prefs
from .trades_model import TradesTableModel


class Worker(QThread):
    progressed = Signal(int)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kw = kwargs

    def run(self) -> None:
        try:
            out = self.fn(*self.args, **self.kw)
            self.finished.emit(out if isinstance(out, dict) else {"result": out})
        except Exception as e:
            self.failed.emit(str(e))


class WorkerRunnable(QRunnable):
    """Lightweight runnable for thread pool execution"""

    def __init__(
        self,
        fn: Callable,
        callback: Callable | None = None,
        error_callback: Callable | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.callback = callback
        self.error_callback = error_callback

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            if self.callback:
                self.callback(result)
        except Exception as e:
            if self.error_callback:
                self.error_callback(str(e))


class MainWindow(QMainWindow):
    def __init__(self, container: ApplicationContainer) -> None:
        super().__init__()
        self.setWindowTitle("Trading Journal")
        self.resize(1400, 800)

        # Dependency injection
        self._container = container
        self._analytics_service = container.analytics_service()
        self._import_service = container.import_service()
        self._backfill_service = container.backfill_service()
        self._trade_repo = container.trade_repository()

        self.prefs = load_prefs()

        # Thread pool for background operations
        self._thread_pool = QThreadPool()
        self._thread_pool.setMaxThreadCount(4)

        # --- Menus
        bar = QMenuBar(self)
        file_menu = bar.addMenu("&File")
        act_import = file_menu.addAction("&Import CSV…")
        act_import.triggered.connect(self.on_import_csv)
        act_export = file_menu.addAction("Export &View…")
        act_export.triggered.connect(self.on_export)
        data_menu = bar.addMenu("&Data")
        act_cols = data_menu.addAction("&Columns…")
        act_cols.triggered.connect(self.on_columns)
        act_backfill = data_menu.addAction("&Backfill All Missing")
        act_backfill.triggered.connect(self.on_backfill_all)
        act_open_logs = data_menu.addAction("Open &Logs Folder")
        act_open_logs.triggered.connect(self.on_open_logs)
        self.setMenuBar(bar)

        # --- Filters
        top = QWidget()
        tl = QHBoxLayout(top)
        self.ed_symbol = QLineEdit()
        self.ed_symbol.setPlaceholderText("Symbol contains…")
        self.cb_side = QComboBox()
        self.cb_side.addItems(["", "LONG", "SHORT", "BUY", "SELL"])
        self.dt_from = QDateEdit()
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat("yyyy-MM-dd")
        self.dt_to = QDateEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat("yyyy-MM-dd")
        self.ed_pnl_min = QLineEdit()
        self.ed_pnl_min.setPlaceholderText("PnL ≥")
        self.ed_pnl_max = QLineEdit()
        self.ed_pnl_max.setPlaceholderText("PnL ≤")
        self.cb_has_ohlcv = QCheckBox("Has OHLCV")
        btn_apply = QPushButton("Apply")
        btn_clear = QPushButton("Clear")
        btn_apply.clicked.connect(self.apply_filters)
        btn_clear.clicked.connect(self.clear_filters)

        for w in [
            QLabel("Symbol"),
            self.ed_symbol,
            QLabel("Side"),
            self.cb_side,
            QLabel("From"),
            self.dt_from,
            QLabel("To"),
            self.dt_to,
            self.ed_pnl_min,
            self.ed_pnl_max,
            self.cb_has_ohlcv,
            btn_apply,
            btn_clear,
        ]:
            tl.addWidget(w)
        tl.addStretch(1)

        # --- Table and Analytics
        self.table = QTableView()
        self.model = TradesTableModel(
            trade_repository=self._trade_repo, page_size=int(self.prefs.get("page_size", 100))
        )
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)

        # Analytics panel
        self.analytics = AnalyticsPanel()

        # Splitter with table (left) and analytics (right)
        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(self.analytics)

        # --- Status
        sb = QStatusBar()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximum(0)
        self.progress.hide()
        self.status_msg = QLabel("Ready")
        sb.addWidget(self.status_msg)
        sb.addPermanentWidget(self.progress, 0)
        self.setStatusBar(sb)

        # --- Layout
        container = QWidget()
        vl = QVBoxLayout(container)
        vl.addWidget(top)
        vl.addWidget(splitter)
        self.setCentralWidget(container)

        # load saved filters & columns
        self.restore_prefs()

        # Column visibility and initial analytics
        self.apply_column_visibility()
        self.refresh_analytics()

    # --- Helpers
    def current_filters(self) -> dict:
        # Helper function for date conversion
        def convert_date(d: Any) -> Any:
            return d.date().toPython() if hasattr(d, "date") and d.date().isValid() else None

        f = {
            "symbol": self.ed_symbol.text().strip(),
            "side": self.cb_side.currentText().strip() or None,
            "date_from": self.dt_from.date().toPython() if self.dt_from.date().isValid() else None,
            "date_to": self.dt_to.date().toPython() if self.dt_to.date().isValid() else None,
            "pnl_min": float(self.ed_pnl_min.text()) if self.ed_pnl_min.text() else None,
            "pnl_max": float(self.ed_pnl_max.text()) if self.ed_pnl_max.text() else None,
            "has_ohlcv": self.cb_has_ohlcv.isChecked(),
        }
        # clean Nones
        return {k: v for k, v in f.items() if v not in ("", None) or k == "has_ohlcv"}

    def set_busy(self, on: bool, msg: str = "") -> None:
        self.status_msg.setText(msg or ("Working…" if on else "Ready"))
        self.progress.setVisible(on)

    def restore_prefs(self) -> None:
        pf = self.prefs.get("filters", {})
        self.ed_symbol.setText(pf.get("symbol", ""))
        self.cb_side.setCurrentText(pf.get("side", ""))
        # dates left empty by default
        self.cb_has_ohlcv.setChecked(bool(pf.get("has_ohlcv", False)))
        self.apply_filters()

    def save_prefs_now(self) -> None:
        self.prefs["filters"] = self.current_filters()
        save_prefs(self.prefs)

    # --- Actions
    def apply_filters(self) -> None:
        self.model.setFilters(self.current_filters())
        self.save_prefs_now()
        self.refresh_analytics()

    def clear_filters(self) -> None:
        self.ed_symbol.clear()
        self.cb_side.setCurrentIndex(0)
        self.dt_from.clear()
        self.dt_to.clear()
        self.ed_pnl_min.clear()
        self.ed_pnl_max.clear()
        self.cb_has_ohlcv.setChecked(False)
        self.apply_filters()

    def on_columns(self) -> None:
        dlg = ColumnsDialog(self.prefs.get("columns_visible", []))
        if dlg.exec():
            self.prefs["columns_visible"] = dlg.selected_keys()
            save_prefs(self.prefs)
            self.apply_column_visibility()

    def on_import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select CSV to import", "", "CSV Files (*.csv)")
        if not path:
            return

        # Show progress immediately
        self.set_busy(True, "Analyzing CSV file...")

        # Load mapping
        mapping = self._import_service.load_mapping("src/journal/ingest/mapping.tradersync.json")

        # Run dry run in thread pool
        def do_dry_run() -> dict:
            return self._import_service.import_csv(
                csv_path=path,
                profile_id=1,
                mapping=mapping,
                dry_run=True,
                chunk_size=10000,
                max_workers=4,
            )

        def on_dry_run_complete(result: dict) -> None:
            self.set_busy(False)
            msg = (
                f"Rows OK: {result.get('inserted',0)} (would insert)\n"
                f"Dupes: {result.get('duplicates_skipped',0)}\n"
                f"Errors: {result.get('errors',0)}\n\nProceed with import?"
            )
            if QMessageBox.question(self, "Dry run", msg) != QMessageBox.Yes:
                return

            # Proceed with actual import
            self.set_busy(True, "Importing CSV…")

            def do_import() -> dict:
                return self._import_service.import_csv(
                    csv_path=path,
                    profile_id=1,
                    mapping=mapping,
                    dry_run=False,
                    chunk_size=5000,
                    max_workers=4,
                    progress_callback=None,  # Could add progress tracking
                )

            w = Worker(do_import)
            w.finished.connect(lambda out: self._after_import(out))
            w.failed.connect(lambda err: self._op_failed("Import failed", err))
            w.start()

        def on_dry_run_error(error: str) -> None:
            self.set_busy(False)
            QMessageBox.critical(self, "Dry run failed", error)

        # Execute dry run
        runnable = WorkerRunnable(
            do_dry_run, callback=on_dry_run_complete, error_callback=on_dry_run_error
        )
        self._thread_pool.start(runnable)

    def _after_import(self, out: dict) -> None:
        self.set_busy(False, "Ready")
        ins = out.get("inserted", 0)
        dup = out.get("duplicates_skipped", 0)
        err = out.get("errors", 0)
        QMessageBox.information(
            self, "Import done", f"Inserted: {ins}\nDuplicates skipped: {dup}\nErrors: {err}"
        )
        self.model.reload(reset=True)
        # Prompt backfill
        if (
            QMessageBox.question(self, "Backfill", "Run backfill for all missing now?")
            == QMessageBox.Yes
        ):
            self.on_backfill_all()

    def on_backfill_all(self) -> None:
        self.set_busy(True, "Backfilling…")
        w = Worker(self._backfill_service.backfill_all_missing, max_workers=4)
        w.finished.connect(lambda out: self._after_backfill(out))
        w.failed.connect(lambda err: self._op_failed("Backfill failed", err))
        w.start()

    def _after_backfill(self, out: dict) -> None:
        self.set_busy(False, "Ready")
        QMessageBox.information(self, "Backfill done", str(out))
        self.model.reload(reset=True)

    def _op_failed(self, title: str, err: str) -> None:
        self.set_busy(False, "Ready")
        QMessageBox.critical(self, title, err)

    def on_open_logs(self) -> None:
        try:
            os.startfile("logs")  # Windows
        except Exception:
            QMessageBox.information(self, "Logs", "Open the 'logs' folder in the project root.")

    def apply_column_visibility(self) -> None:
        vis = self.prefs.get("columns_visible", [])
        from .repository import INDEX_TO_KEY

        for i, key in enumerate(INDEX_TO_KEY):
            self.table.setColumnHidden(i, key not in vis)

    def refresh_analytics(self) -> None:
        """Refresh analytics panel with cached data"""

        def fetch_analytics() -> dict:
            return self._analytics_service.get_summary(filters=self.current_filters())

        def update_ui(data: dict) -> None:
            self.analytics.update_data(data)

        # Run in thread pool for non-blocking operation
        runnable = WorkerRunnable(fetch_analytics, callback=update_ui)
        self._thread_pool.start(runnable)

    def on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export View", "journal_export.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        from .repository import HEADERS

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(HEADERS)
                for row in self._trade_repo.iter_for_export(
                    self.current_filters(), self.model.order_by, self.model.order_dir
                ):
                    w.writerow(row[1:])  # Skip the ID column
            QMessageBox.information(self, "Export", f"Exported to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))


def run_gui(container: ApplicationContainer) -> None:
    import sys

    app = QApplication(sys.argv)
    w = MainWindow(container)
    w.show()
    sys.exit(app.exec())
