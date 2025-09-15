"""
Backfill dialog for integrating the async backfill service with the GUI
"""

import asyncio
import os
from datetime import date
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QButtonGroup,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QMessageBox,
    QGroupBox,
)

from journal_backfill.backfill_async import BackfillOrchestrator
from journal_backfill.config import BackfillConfig
from journal_backfill.models import BackfillRequest


class BackfillWorkerSignals(QObject):
    """Signals for the backfill worker"""
    finished = Signal(dict)
    failed = Signal(str)
    progress = Signal(str)


class BackfillWorker(QRunnable):
    """Worker to run async backfill in a thread pool"""
    
    def __init__(self, requests: list[BackfillRequest]) -> None:
        super().__init__()
        self.requests = requests
        self.signals = BackfillWorkerSignals()
    
    def run(self) -> None:
        """Run the async backfill process"""
        try:
            # Set up the event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Run the backfill
                result = loop.run_until_complete(self._run_backfill())
                self.signals.finished.emit(result)
            finally:
                loop.close()
                
        except Exception as e:
            self.signals.failed.emit(str(e))
    
    async def _run_backfill(self) -> dict[str, Any]:
        """Run the actual backfill process"""
        # Check if API key is set
        if not os.getenv("POLYGON_API_KEY"):
            # Use the provided API key from the requirements
            os.environ["POLYGON_API_KEY"] = "QjD_Isd8mrkdv85s30J0r7qeGcApznGf"
        
        # Ensure we use the correct database file (same as main app)
        from ...config import settings
        os.environ["BACKFILL_DB_URL"] = f"sqlite:///{settings.db_path}"
        
        config = BackfillConfig.from_env()
        orchestrator = BackfillOrchestrator(config)
        
        self.signals.progress.emit(f"Starting backfill for {len(self.requests)} symbol-date pairs...")
        
        result = await orchestrator.backfill_requests(self.requests)
        return result


class BackfillDialog(QDialog):
    """Dialog for backfill operations"""
    
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Backfill Market Data")
        self.setMinimumSize(500, 400)
        self.setModal(True)
        
        # Store data for backfill
        self.selected_trades: list[dict] = []
        self.all_trades: list[dict] = []
        
        self._setup_ui()
        self._setup_connections()
    
    def _setup_ui(self) -> None:
        """Set up the dialog UI"""
        layout = QVBoxLayout(self)
        
        # Header
        header = QLabel("Backfill Market Data")
        header.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(header)
        
        description = QLabel(
            "This will fetch premarket/after-hours highs/lows and daily OHLC data "
            "from Polygon.io for your trades using the new async backfill service."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #666; margin-bottom: 15px;")
        layout.addWidget(description)
        
        # Options group
        options_group = QGroupBox("Backfill Options")
        options_layout = QVBoxLayout(options_group)
        
        self.radio_selected = QRadioButton("Backfill selected trades only")
        self.radio_all = QRadioButton("Backfill all trades in current profile")
        
        self.radio_group = QButtonGroup()
        self.radio_group.addButton(self.radio_selected, 0)
        self.radio_group.addButton(self.radio_all, 1)
        
        options_layout.addWidget(self.radio_selected)
        options_layout.addWidget(self.radio_all)
        
        layout.addWidget(options_group)
        
        # Progress section
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)
        
        self.progress_text = QTextEdit()
        self.progress_text.setMaximumHeight(100)
        self.progress_text.setVisible(False)
        progress_layout.addWidget(self.progress_text)
        
        layout.addWidget(progress_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.btn_start = QPushButton("Start Backfill")
        self.btn_start.setStyleSheet("QPushButton { background-color: #0078d4; color: white; padding: 8px 16px; }")
        
        self.btn_cancel = QPushButton("Cancel")
        
        button_layout.addWidget(self.btn_start)
        button_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(button_layout)
    
    def _setup_connections(self) -> None:
        """Set up signal connections"""
        self.btn_start.clicked.connect(self._start_backfill)
        self.btn_cancel.clicked.connect(self.reject)
        self.radio_group.buttonToggled.connect(self._update_ui_state)
    
    def set_trade_data(self, selected_trades: list[dict], all_trades: list[dict]) -> None:
        """Set the trade data for backfill options"""
        self.selected_trades = selected_trades
        self.all_trades = all_trades
        
        # Update radio button text with counts
        self.radio_selected.setText(f"Backfill selected trades ({len(selected_trades)} trades)")
        self.radio_all.setText(f"Backfill all trades in current profile ({len(all_trades)} trades)")
        
        # Set default selection
        if selected_trades:
            self.radio_selected.setChecked(True)
        else:
            self.radio_all.setChecked(True)
            self.radio_selected.setEnabled(False)
        
        self._update_ui_state()
    
    def _update_ui_state(self) -> None:
        """Update UI state based on selections"""
        has_selection = len(self.selected_trades) > 0
        self.radio_selected.setEnabled(has_selection)
        
        if not has_selection and self.radio_selected.isChecked():
            self.radio_all.setChecked(True)
    
    def _start_backfill(self) -> None:
        """Start the backfill process"""
        # Determine which trades to backfill
        if self.radio_selected.isChecked():
            trades_to_backfill = self.selected_trades
            operation_name = f"selected trades ({len(trades_to_backfill)})"
        else:
            trades_to_backfill = self.all_trades
            operation_name = f"all trades ({len(trades_to_backfill)})"
        
        if not trades_to_backfill:
            QMessageBox.warning(self, "No Trades", "No trades available for backfill.")
            return
        
        # Convert trades to backfill requests
        requests = []
        unique_pairs = set()
        
        for trade in trades_to_backfill:
            symbol = trade.get('symbol', '').strip().upper()
            trade_date = trade.get('trade_date')
            
            if not symbol or not trade_date:
                continue
                
            # Convert trade_date to date object if it's a string
            if isinstance(trade_date, str):
                try:
                    trade_date = date.fromisoformat(trade_date)
                except (ValueError, TypeError):
                    continue
            elif not isinstance(trade_date, date):
                continue
            
            # Avoid duplicate symbol-date pairs
            pair = (symbol, trade_date)
            if pair not in unique_pairs:
                unique_pairs.add(pair)
                requests.append(BackfillRequest(symbol, trade_date))
        
        if not requests:
            QMessageBox.warning(self, "No Valid Data", "No valid symbol-date pairs found for backfill.")
            return
        
        # Confirm the operation
        reply = QMessageBox.question(
            self,
            "Confirm Backfill",
            f"Start backfill for {operation_name}?\n\n"
            f"This will fetch data for {len(requests)} unique symbol-date pairs.\n"
            f"The process may take several minutes depending on the amount of data.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Start the backfill process
        self._run_backfill(requests)
    
    def _run_backfill(self, requests: list[BackfillRequest]) -> None:
        """Run the backfill in a background thread"""
        # Update UI for running state
        self.btn_start.setEnabled(False)
        self.btn_start.setText("Running...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        self.progress_text.setVisible(True)
        self.progress_text.clear()
        
        # Create and start worker
        self.worker = BackfillWorker(requests)
        self.worker.signals.finished.connect(self._on_backfill_finished)
        self.worker.signals.failed.connect(self._on_backfill_failed)
        self.worker.signals.progress.connect(self._on_backfill_progress)
        
        # Run in thread pool
        QThreadPool.globalInstance().start(self.worker)
    
    def _on_backfill_progress(self, message: str) -> None:
        """Handle progress updates"""
        self.progress_text.append(message)
    
    def _on_backfill_finished(self, result: dict) -> None:
        """Handle successful backfill completion"""
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        
        success_msg = (
            f"✅ Backfill completed successfully!\n\n"
            f"Total requests: {result['total_requests']}\n"
            f"Successful: {result['successful']}\n"
            f"Failed: {result['failed']}\n"
            f"Rows written: {result['rows_written']}"
        )
        
        self.progress_text.append(success_msg)
        
        # Update buttons
        self.btn_start.setText("Close")
        self.btn_start.setEnabled(True)
        self.btn_start.clicked.disconnect()
        self.btn_start.clicked.connect(self.accept)
        
        self.btn_cancel.setText("Close")
    
    def _on_backfill_failed(self, error: str) -> None:
        """Handle backfill failure"""
        self.progress_bar.setVisible(False)
        
        error_msg = f"❌ Backfill failed: {error}"
        self.progress_text.append(error_msg)
        
        # Reset buttons
        self.btn_start.setText("Start Backfill")
        self.btn_start.setEnabled(True)
        
        QMessageBox.critical(self, "Backfill Failed", f"The backfill process failed:\n\n{error}")
