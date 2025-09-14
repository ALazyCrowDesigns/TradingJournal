from __future__ import annotations

import csv
import os
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThread, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..container import ApplicationContainer
from ..services.session_manager import SessionTransactionManager
from ..services.session_persistence import SessionPersistence
from .analytics_panel import AnalyticsPanel
from .columns_dialog import ColumnsDialog
from .editable_trades_model import EditableTradesModel
from .prefs import (
    get_current_profile_id,
    get_profile_prefs,
    load_prefs,
    save_prefs,
    set_current_profile_id,
    set_profile_prefs,
)
from .profile_selector import ProfileSelectorWidget


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


class WorkerSignaler(QObject):
    """Helper class to emit signals from worker threads"""

    finished = Signal(object)
    failed = Signal(str)


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

        # Create signaler and connect to callbacks
        self.signaler = WorkerSignaler()
        if self.callback:
            self.signaler.finished.connect(self.callback)
        if self.error_callback:
            self.signaler.failed.connect(self.error_callback)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            if self.callback:
                # Emit signal which will be handled on main thread
                self.signaler.finished.emit(result)
        except Exception as e:
            if self.error_callback:
                # Emit error signal which will be handled on main thread
                self.signaler.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self, container: ApplicationContainer) -> None:
        super().__init__()
        self.resize(1400, 800)

        # Dependency injection
        self._container = container
        self._analytics_service = container.analytics_service()
        self._csv_import_service = container.csv_import_service()
        self._backfill_service = container.backfill_service()
        self._trade_repo = container.trade_repository()
        self._profile_service = container.profile_service()

        # Load preferences and initialize profile system
        self.prefs = load_prefs()
        self.current_profile_id = get_current_profile_id(self.prefs)

        # Ensure the profile exists and is active
        try:
            self.current_profile = self._profile_service.switch_to_profile(self.current_profile_id)
        except Exception:
            # Fallback to default profile
            self.current_profile = self._profile_service.get_default_profile()
            self.current_profile_id = self.current_profile.id
            set_current_profile_id(self.prefs, self.current_profile_id)
            save_prefs(self.prefs)

        # Initialize session manager for CRUD operations
        self._session_manager = SessionTransactionManager(self._trade_repo)
        self._session_persistence = SessionPersistence()

        # Try to restore previous session
        self._restore_session_if_available()

        # Thread pool for background operations
        self._thread_pool = QThreadPool()
        self._thread_pool.setMaxThreadCount(4)

        # --- Menus
        bar = QMenuBar(self)

        # File menu
        file_menu = bar.addMenu("&File")
        act_import = file_menu.addAction("&Import CSV…")
        act_import.triggered.connect(self.on_import_csv)
        act_export = file_menu.addAction("Export &View…")
        act_export.triggered.connect(self.on_export)
        file_menu.addSeparator()
        act_save = file_menu.addAction("&Save Session")
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self.on_save_session)
        act_commit = file_menu.addAction("&Commit to Database")
        act_commit.setShortcut("Ctrl+Shift+S")
        act_commit.triggered.connect(self.on_commit_session)

        # Edit menu
        edit_menu = bar.addMenu("&Edit")
        self.act_undo = edit_menu.addAction("&Undo")
        self.act_undo.setShortcut("Ctrl+Z")
        self.act_undo.triggered.connect(self.on_undo)
        self.act_redo = edit_menu.addAction("&Redo")
        self.act_redo.setShortcut("Ctrl+Y")
        self.act_redo.triggered.connect(self.on_redo)
        edit_menu.addSeparator()
        act_new_trade = edit_menu.addAction("&New Trade")
        act_new_trade.setShortcut("Ctrl+N")
        act_new_trade.triggered.connect(self.on_new_trade)
        act_duplicate = edit_menu.addAction("&Duplicate Trade")
        act_duplicate.setShortcut("Ctrl+D")
        act_duplicate.triggered.connect(self.on_duplicate_trade)
        act_delete = edit_menu.addAction("&Delete Selected")
        act_delete.setShortcut("Delete")
        act_delete.triggered.connect(self.on_delete_selected)
        act_select_all = edit_menu.addAction("Select &All")
        act_select_all.setShortcut("Ctrl+A")
        act_select_all.triggered.connect(lambda: self.table.selectAll())
        edit_menu.addSeparator()
        act_rollback = edit_menu.addAction("&Rollback All Changes")
        act_rollback.triggered.connect(self.on_rollback_session)

        # Profile menu
        profile_menu = bar.addMenu("&Profile")
        act_switch_profile = profile_menu.addAction("&Switch Profile…")
        act_switch_profile.triggered.connect(self.on_switch_profile)
        act_manage_profiles = profile_menu.addAction("&Manage Profiles…")
        act_manage_profiles.triggered.connect(self.on_manage_profiles)
        profile_menu.addSeparator()
        act_clear_data = profile_menu.addAction("&Clear Current Profile Data…")
        act_clear_data.triggered.connect(self.on_clear_current_profile_data)

        # Data menu
        data_menu = bar.addMenu("&Data")
        act_cols = data_menu.addAction("&Columns…")
        act_cols.triggered.connect(self.on_columns)
        act_backfill = data_menu.addAction("&Backfill All Missing")
        act_backfill.triggered.connect(self.on_backfill_all)
        act_open_logs = data_menu.addAction("Open &Logs Folder")
        act_open_logs.triggered.connect(self.on_open_logs)

        self.setMenuBar(bar)

        # --- Profile selector and filters
        top = QWidget()
        # Set maximum height to constrain the filter bar
        top.setMaximumHeight(40)
        tl = QHBoxLayout(top)
        # Reduce margins and spacing
        tl.setContentsMargins(5, 2, 5, 2)
        tl.setSpacing(8)

        # Profile selector
        self.profile_selector = ProfileSelectorWidget(self._profile_service)
        self.profile_selector.profileChanged.connect(self.on_profile_changed)
        self.profile_selector.set_current_profile(self.current_profile_id)
        tl.addWidget(self.profile_selector)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        tl.addWidget(separator)

        self.ed_symbol = QLineEdit()
        self.ed_symbol.setPlaceholderText("Symbol contains…")
        self.ed_symbol.setMaximumHeight(28)

        self.cb_side = QComboBox()
        self.cb_side.addItems(["", "LONG", "SHORT", "BUY", "SELL"])
        self.cb_side.setMaximumHeight(28)

        self.dt_from = QDateEdit()
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat("yyyy-MM-dd")
        self.dt_from.setMaximumHeight(28)
        self.dt_from.clear()  # Start with invalid date

        self.dt_to = QDateEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat("yyyy-MM-dd")
        self.dt_to.setMaximumHeight(28)
        self.dt_to.clear()  # Start with invalid date

        self.ed_pnl_min = QLineEdit()
        self.ed_pnl_min.setPlaceholderText("PnL ≥")
        self.ed_pnl_min.setMaximumHeight(28)

        self.ed_pnl_max = QLineEdit()
        self.ed_pnl_max.setPlaceholderText("PnL ≤")
        self.ed_pnl_max.setMaximumHeight(28)

        self.cb_has_ohlcv = QCheckBox("Has OHLCV")
        self.cb_has_ohlcv.setMaximumHeight(28)

        btn_apply = QPushButton("Apply")
        btn_apply.setMaximumHeight(28)
        btn_apply.clicked.connect(self.apply_filters)

        btn_clear = QPushButton("Clear")
        btn_clear.setMaximumHeight(28)
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

        # Use editable model with session management
        profile_prefs = get_profile_prefs(self.prefs, self.current_profile_id)
        self.model = EditableTradesModel(
            trade_repository=self._trade_repo,
            session_manager=self._session_manager,
            page_size=int(profile_prefs.get("page_size", 100)),
        )
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)  # Enable multi-selection
        self.table.setAlternatingRowColors(True)

        # Enable context menu for right-click operations
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_trades_context_menu)

        # Connect model signals
        self.model.sessionChanged.connect(self._update_menu_states)

        # Connect selection changes to update status bar
        self.table.selectionModel().selectionChanged.connect(self._update_selection_info)

        # Analytics panel
        self.analytics = AnalyticsPanel()

        # Tab widget with trades table and analytics panel
        tab_widget = QTabWidget()
        tab_widget.addTab(self.table, "Trades")
        tab_widget.addTab(self.analytics, "Analytics")

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
        # Reduce vertical spacing between filter bar and table
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)
        vl.addWidget(top)
        vl.addWidget(tab_widget)
        self.setCentralWidget(container)

        # load saved filters & columns
        self.restore_prefs()

        # Column visibility (immediate)
        self.apply_column_visibility()

        # Update menu states and window title
        self._update_menu_states()
        self._update_window_title()

        # Defer analytics loading for better startup performance
        self._analytics_loaded = False
        QTimer.singleShot(100, self._delayed_analytics_load)

    def _delayed_analytics_load(self) -> None:
        """Load analytics after startup to improve performance"""
        if not self._analytics_loaded:
            self.refresh_analytics()
            self._analytics_loaded = True

    # --- Helpers
    def _get_last_30_days_range(self):
        """Get the date range for the last 30 days starting from today"""
        from datetime import date, timedelta
        
        today = date.today()
        thirty_days_ago = today - timedelta(days=30)
        
        return thirty_days_ago, today
    
    def current_filters(self) -> dict:
        # Helper function for date conversion with better validation
        def get_valid_date(date_edit):
            if not date_edit.date().isValid():
                return None
            date_val = date_edit.date().toPython()
            # Check if it's a reasonable date (not the default 2000-01-01)
            from datetime import date

            if date_val <= date(2000, 1, 1):
                return None
            return date_val

        f = {
            "profile_id": self.current_profile_id,  # Always filter by current profile
            "symbol": self.ed_symbol.text().strip(),
            "side": self.cb_side.currentText().strip() or None,
            "date_from": get_valid_date(self.dt_from),
            "date_to": get_valid_date(self.dt_to),
            "pnl_min": float(self.ed_pnl_min.text()) if self.ed_pnl_min.text() else None,
            "pnl_max": float(self.ed_pnl_max.text()) if self.ed_pnl_max.text() else None,
            "has_ohlcv": self.cb_has_ohlcv.isChecked(),
        }
        # clean Nones (but keep profile_id and has_ohlcv)
        return {
            k: v for k, v in f.items() if v not in ("", None) or k in ("profile_id", "has_ohlcv")
        }

    def set_busy(self, on: bool, msg: str = "") -> None:
        self.status_msg.setText(msg or ("Working…" if on else "Ready"))
        self.progress.setVisible(on)

    def restore_prefs(self) -> None:
        profile_prefs = get_profile_prefs(self.prefs, self.current_profile_id)
        pf = profile_prefs.get("filters", {})
        self.ed_symbol.setText(pf.get("symbol", ""))
        self.cb_side.setCurrentText(pf.get("side", ""))
        
        # Set date range - use saved dates if available, otherwise default to last 30 days
        saved_date_from = pf.get("date_from")
        saved_date_to = pf.get("date_to")
        
        if saved_date_from and saved_date_to:
            # Use saved dates
            from PySide6.QtCore import QDate
            self.dt_from.setDate(QDate.fromString(saved_date_from.isoformat(), "yyyy-MM-dd"))
            self.dt_to.setDate(QDate.fromString(saved_date_to.isoformat(), "yyyy-MM-dd"))
        else:
            # Default to last 30 days
            start_date, end_date = self._get_last_30_days_range()
            from PySide6.QtCore import QDate
            self.dt_from.setDate(QDate.fromString(start_date.isoformat(), "yyyy-MM-dd"))
            self.dt_to.setDate(QDate.fromString(end_date.isoformat(), "yyyy-MM-dd"))
        
        self.cb_has_ohlcv.setChecked(bool(pf.get("has_ohlcv", False)))
        # Apply filters without refreshing analytics (will be done once after full init)
        self.model.setFilters(self.current_filters())
        self.save_prefs_now()

    def save_prefs_now(self) -> None:
        profile_prefs = get_profile_prefs(self.prefs, self.current_profile_id)
        profile_prefs["filters"] = self.current_filters()
        set_profile_prefs(self.prefs, self.current_profile_id, profile_prefs)
        save_prefs(self.prefs)

    # --- Actions
    def apply_filters(self) -> None:
        self.model.setFilters(self.current_filters())
        self.save_prefs_now()
        self.refresh_analytics()

    def clear_filters(self) -> None:
        self.ed_symbol.clear()
        self.cb_side.setCurrentIndex(0)
        
        # Reset dates to last 30 days instead of clearing
        start_date, end_date = self._get_last_30_days_range()
        from PySide6.QtCore import QDate
        self.dt_from.setDate(QDate.fromString(start_date.isoformat(), "yyyy-MM-dd"))
        self.dt_to.setDate(QDate.fromString(end_date.isoformat(), "yyyy-MM-dd"))
        
        self.ed_pnl_min.clear()
        self.ed_pnl_max.clear()
        self.cb_has_ohlcv.setChecked(False)
        self.apply_filters()

    def on_columns(self) -> None:
        profile_prefs = get_profile_prefs(self.prefs, self.current_profile_id)
        dlg = ColumnsDialog(profile_prefs.get("columns_visible", []))
        if dlg.exec():
            profile_prefs["columns_visible"] = dlg.selected_keys()
            set_profile_prefs(self.prefs, self.current_profile_id, profile_prefs)
            save_prefs(self.prefs)
            self.apply_column_visibility()

    def on_import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select CSV to import", "", "CSV Files (*.csv)")
        if not path:
            return

        # Show progress immediately
        self.set_busy(True, "Analyzing CSV file...")

        # Run dry run first to validate
        def do_dry_run() -> dict:
            result = self._csv_import_service.import_csv(
                csv_path=path,
                profile_id=self.current_profile_id,
                dry_run=True,
            )
            return {
                "inserted": result.imported,
                "duplicates_skipped": result.duplicates_skipped,
                "errors": result.errors,
            }

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
                result = self._csv_import_service.import_csv(
                    csv_path=path,
                    profile_id=self.current_profile_id,
                    dry_run=False,
                )
                return {
                    "inserted": result.imported,
                    "duplicates_skipped": result.duplicates_skipped,
                    "errors": result.errors,
                }

            # Store as instance variable to prevent garbage collection
            self._import_worker = Worker(do_import)
            self._import_worker.finished.connect(lambda out: self._after_import(out))
            self._import_worker.failed.connect(lambda err: self._op_failed("Import failed", err))
            self._import_worker.start()

        def on_dry_run_error(error: str) -> None:
            self.set_busy(False)
            QMessageBox.critical(self, "Dry run failed", error)

        # Execute dry run using Worker (QThread) instead of WorkerRunnable (QThreadPool)
        # This ensures proper signal handling
        # Store as instance variable to prevent garbage collection
        self._dry_run_worker = Worker(do_dry_run)
        self._dry_run_worker.finished.connect(lambda out: on_dry_run_complete(out))
        self._dry_run_worker.failed.connect(lambda err: on_dry_run_error(err))
        self._dry_run_worker.start()

    def _after_import(self, out: dict) -> None:
        try:
            self.set_busy(False, "Ready")
            ins = out.get("inserted", 0)
            dup = out.get("duplicates_skipped", 0)
            err = out.get("errors", 0)

            # Show import results
            QMessageBox.information(
                self, "Import done", f"Inserted: {ins}\nDuplicates skipped: {dup}\nErrors: {err}"
            )

            # Refresh session manager to see new database data
            try:
                # First, refresh the session manager's view of the database
                self._session_manager.refresh_from_database()

                # Clear analytics cache to ensure fresh stats
                if hasattr(self._analytics_service, "_cache") and self._analytics_service._cache:
                    self._analytics_service._cache.clear()
                    print("Analytics cache cleared - fresh stats will be calculated")

                # Then reload the model with fresh data
                self.model.reload(reset=True)

                # Also refresh analytics to show updated stats
                self.refresh_analytics()

            except Exception as e:
                print(f"Error during model reload: {e}")
                # Try to show a warning but don't crash
                QMessageBox.warning(
                    self,
                    "Model Reload Error",
                    f"Data was imported successfully, but there was an error refreshing the view: {e}\n\n"
                    f"Please restart the application to see the imported data.",
                )
                return

            # Prompt backfill
            if (
                QMessageBox.question(self, "Backfill", "Run backfill for all missing now?")
                == QMessageBox.Yes
            ):
                self.on_backfill_all()

        except Exception as e:
            # Catch any other errors in the post-import process
            print(f"Error in _after_import: {e}")
            import traceback

            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Post-Import Error",
                f"Import completed, but there was an error in post-processing: {e}\n\n"
                f"Your data has been saved. Please restart the application.",
            )
            self.set_busy(False, "Ready")

    def on_backfill_all(self) -> None:
        self.set_busy(True, "Backfilling…")
        # Store as instance variable to prevent garbage collection
        self._backfill_worker = Worker(self._backfill_service.backfill_all_missing, max_workers=4)
        self._backfill_worker.finished.connect(lambda out: self._after_backfill(out))
        self._backfill_worker.failed.connect(lambda err: self._op_failed("Backfill failed", err))
        self._backfill_worker.start()

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
        profile_prefs = get_profile_prefs(self.prefs, self.current_profile_id)
        vis = profile_prefs.get("columns_visible", [])
        from .repository import INDEX_TO_KEY

        for i, key in enumerate(INDEX_TO_KEY):
            self.table.setColumnHidden(i, key not in vis)

    def refresh_analytics(self) -> None:
        """Refresh analytics panel with cached data"""

        def fetch_analytics() -> dict:
            return self._analytics_service.get_summary(filters=self.current_filters())

        def update_ui(data: dict) -> None:
            self.analytics.update_data(data)

        def on_analytics_error(error: str) -> None:
            print(f"Analytics refresh error: {error}")
            # Don't show error dialog, just log it

        # Use Worker (QThread) instead of WorkerRunnable for reliable signal handling
        self._analytics_worker = Worker(fetch_analytics)
        self._analytics_worker.finished.connect(lambda out: update_ui(out))
        self._analytics_worker.failed.connect(lambda err: on_analytics_error(err))
        self._analytics_worker.start()

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

    # --- Context Menu ---

    def _show_trades_context_menu(self, position) -> None:
        """Show context menu for trades table"""
        if not self.table.indexAt(position).isValid():
            return

        selection = self.table.selectionModel()
        selected_rows = [index.row() for index in selection.selectedRows()]

        menu = QMenu(self)

        # Add actions based on selection
        if len(selected_rows) == 1:
            menu.addAction("Duplicate Trade", self.on_duplicate_trade)
            menu.addSeparator()

        if selected_rows:
            if len(selected_rows) == 1:
                menu.addAction("Delete Trade", self.on_delete_selected)
            else:
                menu.addAction(f"Delete {len(selected_rows)} Trades", self.on_delete_selected)
            menu.addSeparator()

        # Always available actions
        menu.addAction("New Trade", self.on_new_trade)
        menu.addSeparator()
        menu.addAction("Select All", lambda: self.table.selectAll())

        # Show menu at cursor position
        menu.exec(self.table.mapToGlobal(position))

    def _update_selection_info(self) -> None:
        """Update status bar with selection information"""
        selection = self.table.selectionModel()
        selected_rows = [index.row() for index in selection.selectedRows()]

        # If we have unsaved changes, show that info first
        if self.model.has_unsaved_changes():
            session_info = self.model.get_session_info()
            pending = (
                session_info.get("pending_creates", 0)
                + session_info.get("pending_updates", 0)
                + session_info.get("pending_deletes", 0)
            )
            base_msg = f"{pending} unsaved changes"
        else:
            base_msg = "Ready"

        # Add selection info if any rows are selected
        if selected_rows:
            total_rows = self.model.rowCount()
            if len(selected_rows) == 1:
                selection_msg = "1 row selected"
            else:
                selection_msg = f"{len(selected_rows)} rows selected"

            if total_rows > 0:
                selection_msg += f" of {total_rows}"

            self.status_msg.setText(f"{base_msg} - {selection_msg}")
        else:
            self.status_msg.setText(base_msg)

    # --- CRUD Operations ---

    def _update_menu_states(self) -> None:
        """Update menu item states based on session state"""
        self.act_undo.setEnabled(self.model.can_undo())
        self.act_redo.setEnabled(self.model.can_redo())

        # Update undo/redo text with descriptions
        undo_desc = self._session_manager.get_undo_description()
        redo_desc = self._session_manager.get_redo_description()

        if undo_desc:
            self.act_undo.setText(f"&Undo {undo_desc}")
        else:
            self.act_undo.setText("&Undo")

        if redo_desc:
            self.act_redo.setText(f"&Redo {redo_desc}")
        else:
            self.act_redo.setText("&Redo")

        # Update status bar with session and selection info
        self._update_selection_info()

    def on_save_session(self) -> None:
        """Save current session (checkpoint, but not to database)"""
        try:
            # Save session state to memory
            result = self.model.save_session()

            # Also persist to disk
            self._auto_save_session()

            QMessageBox.information(
                self,
                "Session Saved",
                "Session checkpoint created and saved to disk.\n\n"
                "Note: Changes are not yet committed to database.\n"
                "Use 'Commit to Database' to make changes permanent.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Failed to save session: {e}")

    def on_commit_session(self) -> None:
        """Commit all changes to database"""
        if not self.model.has_unsaved_changes():
            QMessageBox.information(self, "No Changes", "No changes to commit.")
            return

        # Confirm commit
        session_info = self.model.get_session_info()
        creates = session_info.get("pending_creates", 0)
        updates = session_info.get("pending_updates", 0)
        deletes = session_info.get("pending_deletes", 0)

        msg = "Commit the following changes to database?\n\n"
        msg += f"• {creates} new trades\n"
        msg += f"• {updates} updated trades\n"
        msg += f"• {deletes} deleted trades\n\n"
        msg += "This action cannot be undone after commit."

        reply = QMessageBox.question(
            self, "Confirm Commit", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            self.set_busy(True, "Committing changes to database...")
            result = self.model.commit_session()
            self.set_busy(False)

            if result.get("errors", 0) > 0:
                QMessageBox.warning(
                    self,
                    "Commit Completed with Errors",
                    f"Committed with some errors:\n"
                    f"• Created: {result.get('created', 0)}\n"
                    f"• Updated: {result.get('updated', 0)}\n"
                    f"• Deleted: {result.get('deleted', 0)}\n"
                    f"• Errors: {result.get('errors', 0)}",
                )
            else:
                QMessageBox.information(
                    self,
                    "Commit Successful",
                    f"Successfully committed changes:\n"
                    f"• Created: {result.get('created', 0)}\n"
                    f"• Updated: {result.get('updated', 0)}\n"
                    f"• Deleted: {result.get('deleted', 0)}",
                )

            # Refresh analytics after commit
            self.refresh_analytics()

        except Exception as e:
            self.set_busy(False)
            QMessageBox.critical(self, "Commit Failed", f"Failed to commit changes: {e}")

    def on_rollback_session(self) -> None:
        """Rollback all session changes"""
        if not self.model.has_unsaved_changes():
            QMessageBox.information(self, "No Changes", "No changes to rollback.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Rollback",
            "Rollback all changes in this session?\n\n"
            "This will discard all unsaved changes and cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.model.rollback_session()
            QMessageBox.information(self, "Rollback Complete", "All changes have been discarded.")
            self.refresh_analytics()

    def on_undo(self) -> None:
        """Undo last operation"""
        description = self.model.undo()
        if description:
            self.status_msg.setText(f"Undone: {description}")
        else:
            self.status_msg.setText("Nothing to undo")

    def on_redo(self) -> None:
        """Redo last undone operation"""
        description = self.model.redo()
        if description:
            self.status_msg.setText(f"Redone: {description}")
        else:
            self.status_msg.setText("Nothing to redo")

    def on_new_trade(self) -> None:
        """Create a new trade"""
        try:
            trade_id = self.model.create_trade()
            self.status_msg.setText(f"Created new trade: {trade_id[:8]}...")

            # Scroll to the new trade (it will be at the top with default sorting)
            self.table.scrollToTop()

        except Exception as e:
            QMessageBox.critical(self, "Create Trade Failed", f"Failed to create new trade: {e}")

    def on_duplicate_trade(self) -> None:
        """Duplicate selected trade"""
        selection = self.table.selectionModel()
        if not selection.hasSelection():
            QMessageBox.information(self, "No Selection", "Please select a trade to duplicate.")
            return

        selected_rows = [index.row() for index in selection.selectedRows()]
        if len(selected_rows) > 1:
            QMessageBox.information(
                self,
                "Multiple Selection",
                f"Please select exactly one trade to duplicate.\n\nCurrently selected: {len(selected_rows)} trades",
            )
            return

        try:
            row_idx = selected_rows[0]
            new_trade_id = self.model.duplicate_trade(row_idx)

            if new_trade_id:
                self.status_msg.setText(f"Duplicated trade: {new_trade_id[:8]}...")
                self.table.scrollToTop()
            else:
                QMessageBox.warning(
                    self, "Duplicate Failed", "Failed to duplicate the selected trade."
                )

        except Exception as e:
            QMessageBox.critical(self, "Duplicate Failed", f"Failed to duplicate trade: {e}")

    def on_delete_selected(self) -> None:
        """Delete selected trades"""
        selection = self.table.selectionModel()
        if not selection.hasSelection():
            QMessageBox.information(self, "No Selection", "Please select trades to delete.")
            return

        selected_rows = [index.row() for index in selection.selectedRows()]

        # Confirm deletion
        if len(selected_rows) == 1:
            msg = "Delete the selected trade?"
        else:
            msg = f"Delete {len(selected_rows)} selected trades?"

        reply = QMessageBox.question(
            self, "Confirm Delete", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            deleted_count = self.model.delete_selected_trades(selected_rows)

            if deleted_count > 0:
                self.status_msg.setText(f"Deleted {deleted_count} trade(s)")
            else:
                QMessageBox.warning(self, "Delete Failed", "No trades were deleted.")

        except Exception as e:
            QMessageBox.critical(self, "Delete Failed", f"Failed to delete trades: {e}")

    # --- Session Persistence ---

    def _restore_session_if_available(self) -> None:
        """Check for and optionally restore a previous session"""
        if not self._session_persistence.has_saved_session():
            return

        session_info = self._session_persistence.get_session_info()
        if not session_info or not session_info.get("has_unsaved_changes", False):
            # No unsaved changes, just clear the old session file
            self._session_persistence.clear_session_file()
            return

        # Show restore dialog
        saved_at = session_info.get("saved_at", "Unknown")
        num_changes = session_info.get("num_session_trades", 0) + session_info.get(
            "num_deleted_trades", 0
        )

        msg = (
            f"Found a previous session with unsaved changes:\n\n"
            f"• Saved at: {saved_at}\n"
            f"• Number of changes: {num_changes}\n"
            f"• Commands in history: {session_info.get('num_commands', 0)}\n\n"
            f"Would you like to restore this session?"
        )

        reply = QMessageBox.question(
            self,
            "Restore Previous Session?",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if reply == QMessageBox.Yes:
            if self._session_persistence.load_session_state(self._session_manager):
                self.status_msg.setText("Previous session restored")
            else:
                QMessageBox.warning(self, "Restore Failed", "Failed to restore previous session.")
                self._session_persistence.clear_session_file()
        else:
            # User chose not to restore, clear the session file
            self._session_persistence.clear_session_file()

    def _auto_save_session(self) -> None:
        """Auto-save session state"""
        if self._session_manager.has_unsaved_changes():
            self._session_persistence.save_session_state(self._session_manager)

    def closeEvent(self, event) -> None:
        """Handle application close event"""
        # Check for unsaved changes
        if self._session_manager.has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. What would you like to do?\n\n"
                "• Save Session: Keep changes for next time\n"
                "• Commit: Save changes to database permanently\n"
                "• Discard: Lose all changes",
                QMessageBox.Save | QMessageBox.Apply | QMessageBox.Discard | QMessageBox.Cancel,
            )

            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            elif reply == QMessageBox.Save:
                # Save session for next time
                self._auto_save_session()
            elif reply == QMessageBox.Apply:
                # Commit to database
                try:
                    result = self._session_manager.commit()
                    if result.get("errors", 0) > 0:
                        QMessageBox.warning(
                            self,
                            "Commit Errors",
                            f"Some changes could not be committed:\n"
                            f"Errors: {result.get('errors', 0)}",
                        )
                except Exception as e:
                    QMessageBox.critical(self, "Commit Failed", f"Failed to commit: {e}")
                    event.ignore()
                    return
                # Clear session file after successful commit
                self._session_persistence.clear_session_file()
            else:
                # Discard changes
                self._session_persistence.clear_session_file()
        else:
            # No changes, just clear any session file
            self._session_persistence.clear_session_file()

        event.accept()

    # --- Profile Management ---

    def _update_window_title(self) -> None:
        """Update window title to include current profile"""
        title = f"Trading Journal - {self.current_profile.name}"
        self.setWindowTitle(title)

    def on_profile_changed(self, profile_id: int) -> None:
        """Handle profile change from profile selector"""
        if profile_id != self.current_profile_id:
            self._switch_to_profile(profile_id)

    def on_switch_profile(self) -> None:
        """Handle switch profile menu action"""
        self.profile_selector.show_profile_selection_dialog()

    def on_manage_profiles(self) -> None:
        """Handle manage profiles menu action"""
        self.profile_selector._open_profile_manager()

    def on_clear_current_profile_data(self) -> None:
        """Handle clear current profile data menu action"""
        # Get current trade count for confirmation
        try:
            summary = self._profile_service.get_profile_summary(self.current_profile_id)
            trade_count = summary.get("trade_count", 0)
        except Exception:
            trade_count = 0

        if trade_count == 0:
            QMessageBox.information(
                self,
                "No Data",
                f"Current profile '{self.current_profile.name}' has no trades to delete.",
            )
            return

        # Confirmation dialog with strong warning
        reply = QMessageBox.question(
            self,
            "Confirm Clear All Data",
            f"⚠️ WARNING: This will permanently delete ALL DATA for the current profile '{self.current_profile.name}':\n\n"
            f"• {trade_count} trades will be permanently deleted\n"
            f"• The profile itself will remain intact\n"
            f"• This action CANNOT be undone!\n\n"
            f"Are you absolutely sure you want to clear all data for this profile?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            # Double confirmation for safety
            reply2 = QMessageBox.question(
                self,
                "Final Confirmation",
                f"Last chance to cancel!\n\n"
                f"This will delete {trade_count} trades from '{self.current_profile.name}'.\n\n"
                f"Proceed with data deletion?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if reply2 == QMessageBox.Yes:
                try:
                    self.set_busy(True, "Clearing profile data...")
                    result = self._profile_service.delete_profile_data(self.current_profile_id)
                    trades_deleted = result.get("trades_deleted", 0)

                    self.set_busy(False)

                    QMessageBox.information(
                        self,
                        "Data Cleared",
                        f"Successfully cleared all data for profile '{self.current_profile.name}'.\n\n"
                        f"Trades deleted: {trades_deleted}",
                    )

                    # Refresh the data view and analytics
                    self.model.reload(reset=True)
                    self.refresh_analytics()

                except Exception as e:
                    self.set_busy(False)
                    QMessageBox.critical(self, "Error", f"Failed to clear profile data: {e}")

    def _switch_to_profile(self, profile_id: int) -> None:
        """Switch to a different profile"""
        try:
            # Save current profile preferences
            self.save_prefs_now()

            # Switch to new profile
            self.current_profile = self._profile_service.switch_to_profile(profile_id)
            self.current_profile_id = profile_id

            # Update preferences
            set_current_profile_id(self.prefs, profile_id)
            save_prefs(self.prefs)

            # Update UI
            self._update_window_title()
            self.restore_prefs()
            self.apply_column_visibility()

            # Reload data for new profile
            self.model.setFilters(self.current_filters())
            self.model.reload(reset=True)
            self.refresh_analytics()

            self.status_msg.setText(f"Switched to profile: {self.current_profile.name}")

        except Exception as e:
            QMessageBox.critical(self, "Profile Switch Error", f"Failed to switch profile: {e}")
            # Revert profile selector
            self.profile_selector.set_current_profile(self.current_profile_id)


def run_gui(container: ApplicationContainer) -> None:
    import sys

    app = QApplication(sys.argv)
    w = MainWindow(container)
    w.show()
    sys.exit(app.exec())
