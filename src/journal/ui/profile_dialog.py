"""
Profile management dialog for selecting, creating, and managing trader profiles
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QCheckBox,
    QGroupBox,
    QFormLayout,
    QMessageBox,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QFrame,
    QInputDialog,
)

from ..dto import ProfileOut
from ..services.profile_service import ProfileService


class ProfileSelectionDialog(QDialog):
    """Simple dialog for selecting a profile"""
    
    profileSelected = Signal(int)  # profile_id
    
    def __init__(self, profile_service: ProfileService, current_profile_id: int = 1, parent=None) -> None:
        super().__init__(parent)
        self.profile_service = profile_service
        self.current_profile_id = current_profile_id
        self.selected_profile_id = current_profile_id
        
        self.setWindowTitle("Select Profile")
        self.setModal(True)
        self.resize(400, 200)
        
        self._setup_ui()
        self._load_profiles()
    
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        
        # Profile selection
        form_layout = QFormLayout()
        
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        form_layout.addRow("Select Profile:", self.profile_combo)
        
        layout.addLayout(form_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.manage_btn = QPushButton("Manage Profiles...")
        self.manage_btn.clicked.connect(self._open_profile_manager)
        button_layout.addWidget(self.manage_btn)
        
        button_layout.addStretch()
        
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.accept)
        self.ok_btn.setDefault(True)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(self.ok_btn)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
    
    def _load_profiles(self) -> None:
        """Load profiles into the combo box"""
        self.profile_combo.clear()
        
        try:
            profiles = self.profile_service.list_active_profiles()
            
            current_index = 0
            for i, profile in enumerate(profiles):
                self.profile_combo.addItem(profile.name, profile.id)
                if profile.id == self.current_profile_id:
                    current_index = i
            
            if profiles:
                self.profile_combo.setCurrentIndex(current_index)
                self.selected_profile_id = profiles[current_index].id
            else:
                QMessageBox.warning(self, "No Profiles", "No active profiles found. Please create a profile first.")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load profiles: {e}")
    
    def _on_profile_changed(self) -> None:
        """Handle profile selection change"""
        if self.profile_combo.currentData():
            self.selected_profile_id = self.profile_combo.currentData()
    
    def _open_profile_manager(self) -> None:
        """Open the profile management dialog"""
        dialog = ProfileManagerDialog(self.profile_service, self)
        if dialog.exec() == QDialog.Accepted:
            # Refresh the profile list
            old_selected = self.selected_profile_id
            self._load_profiles()
            
            # Try to maintain selection
            for i in range(self.profile_combo.count()):
                if self.profile_combo.itemData(i) == old_selected:
                    self.profile_combo.setCurrentIndex(i)
                    break
    
    def get_selected_profile_id(self) -> int:
        """Get the selected profile ID"""
        return self.selected_profile_id
    
    def accept(self) -> None:
        """Accept the dialog and emit the selected profile"""
        if self.selected_profile_id:
            self.profileSelected.emit(self.selected_profile_id)
        super().accept()


class ProfileManagerDialog(QDialog):
    """Comprehensive profile management dialog"""
    
    def __init__(self, profile_service: ProfileService, parent=None) -> None:
        super().__init__(parent)
        self.profile_service = profile_service
        self.current_profile: Optional[ProfileOut] = None
        
        self.setWindowTitle("Manage Profiles")
        self.setModal(True)
        self.resize(700, 500)
        
        self._setup_ui()
        self._refresh_profiles()
    
    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        
        # Create splitter for list and details
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)
        
        # Left side - Profile list
        left_frame = QFrame()
        left_layout = QVBoxLayout(left_frame)
        
        left_layout.addWidget(QLabel("Profiles:"))
        
        self.profile_list = QListWidget()
        self.profile_list.itemSelectionChanged.connect(self._on_profile_selected)
        left_layout.addWidget(self.profile_list)
        
        # List buttons
        list_button_layout = QHBoxLayout()
        
        self.new_btn = QPushButton("New")
        self.new_btn.clicked.connect(self._create_new_profile)
        list_button_layout.addWidget(self.new_btn)
        
        self.duplicate_btn = QPushButton("Duplicate")
        self.duplicate_btn.clicked.connect(self._duplicate_profile)
        list_button_layout.addWidget(self.duplicate_btn)
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_profile)
        list_button_layout.addWidget(self.delete_btn)
        
        self.clear_data_btn = QPushButton("Clear Data")
        self.clear_data_btn.clicked.connect(self._clear_profile_data)
        self.clear_data_btn.setToolTip("Delete all trades for this profile")
        list_button_layout.addWidget(self.clear_data_btn)
        
        left_layout.addLayout(list_button_layout)
        
        splitter.addWidget(left_frame)
        
        # Right side - Profile details
        right_frame = QFrame()
        right_layout = QVBoxLayout(right_frame)
        
        # Profile details form
        details_group = QGroupBox("Profile Details")
        details_layout = QFormLayout(details_group)
        
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_details_changed)
        details_layout.addRow("Name:", self.name_edit)
        
        self.description_edit = QTextEdit()
        self.description_edit.textChanged.connect(self._on_details_changed)
        self.description_edit.setMaximumHeight(100)
        details_layout.addRow("Description:", self.description_edit)
        
        self.active_check = QCheckBox("Active")
        self.active_check.stateChanged.connect(self._on_details_changed)
        details_layout.addRow("Status:", self.active_check)
        
        self.csv_format_combo = QComboBox()
        self.csv_format_combo.addItems(["tradersync", "custom"])
        self.csv_format_combo.currentTextChanged.connect(self._on_details_changed)
        details_layout.addRow("Default CSV Format:", self.csv_format_combo)
        
        right_layout.addWidget(details_group)
        
        # Profile stats
        stats_group = QGroupBox("Statistics")
        stats_layout = QFormLayout(stats_group)
        
        self.trade_count_label = QLabel("0")
        stats_layout.addRow("Trade Count:", self.trade_count_label)
        
        self.created_label = QLabel("-")
        stats_layout.addRow("Created:", self.created_label)
        
        self.updated_label = QLabel("-")
        stats_layout.addRow("Last Updated:", self.updated_label)
        
        right_layout.addWidget(stats_group)
        
        right_layout.addStretch()
        
        # Detail buttons
        detail_button_layout = QHBoxLayout()
        
        self.save_btn = QPushButton("Save Changes")
        self.save_btn.clicked.connect(self._save_profile)
        self.save_btn.setEnabled(False)
        detail_button_layout.addWidget(self.save_btn)
        
        self.revert_btn = QPushButton("Revert")
        self.revert_btn.clicked.connect(self._revert_changes)
        self.revert_btn.setEnabled(False)
        detail_button_layout.addWidget(self.revert_btn)
        
        right_layout.addLayout(detail_button_layout)
        
        splitter.addWidget(right_frame)
        
        # Set splitter proportions
        splitter.setSizes([200, 500])
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        
        main_layout = QVBoxLayout()
        main_layout.addWidget(splitter)
        main_layout.addWidget(button_box)
        
        self.setLayout(main_layout)
    
    def _refresh_profiles(self) -> None:
        """Refresh the profile list"""
        self.profile_list.clear()
        
        try:
            profiles = self.profile_service.list_all_profiles()
            
            for profile in profiles:
                item = QListWidgetItem()
                status = "Active" if profile.is_active else "Inactive"
                item.setText(f"{profile.name} ({status})")
                item.setData(Qt.UserRole, profile)
                
                if not profile.is_active:
                    item.setForeground(Qt.gray)
                
                self.profile_list.addItem(item)
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load profiles: {e}")
    
    def _on_profile_selected(self) -> None:
        """Handle profile selection in the list"""
        current_item = self.profile_list.currentItem()
        if current_item:
            profile = current_item.data(Qt.UserRole)
            self._load_profile_details(profile)
        else:
            self._clear_profile_details()
    
    def _load_profile_details(self, profile: ProfileOut) -> None:
        """Load profile details into the form"""
        self.current_profile = profile
        
        # Block signals to prevent triggering change detection
        self.name_edit.blockSignals(True)
        self.description_edit.blockSignals(True)
        self.active_check.blockSignals(True)
        self.csv_format_combo.blockSignals(True)
        
        self.name_edit.setText(profile.name)
        self.description_edit.setPlainText(profile.description or "")
        self.active_check.setChecked(profile.is_active)
        
        # Set CSV format
        csv_format = profile.default_csv_format or "tradersync"
        index = self.csv_format_combo.findText(csv_format)
        if index >= 0:
            self.csv_format_combo.setCurrentIndex(index)
        
        # Update stats
        try:
            summary = self.profile_service.get_profile_summary(profile.id)
            self.trade_count_label.setText(str(summary.get("trade_count", 0)))
        except Exception:
            self.trade_count_label.setText("Error")
        
        self.created_label.setText(profile.created_at.strftime("%Y-%m-%d %H:%M"))
        self.updated_label.setText(profile.updated_at.strftime("%Y-%m-%d %H:%M"))
        
        # Re-enable signals
        self.name_edit.blockSignals(False)
        self.description_edit.blockSignals(False)
        self.active_check.blockSignals(False)
        self.csv_format_combo.blockSignals(False)
        
        # Enable/disable buttons
        self.duplicate_btn.setEnabled(True)
        # Always enable delete button since we support force deletion
        self.delete_btn.setEnabled(True)
        # Enable clear data button only if profile has trades
        try:
            summary = self.profile_service.get_profile_summary(profile.id)
            has_trades = summary.get("trade_count", 0) > 0
            self.clear_data_btn.setEnabled(has_trades)
        except Exception:
            self.clear_data_btn.setEnabled(False)
        
        # Reset change tracking
        self._reset_change_tracking()
    
    def _clear_profile_details(self) -> None:
        """Clear the profile details form"""
        self.current_profile = None
        
        self.name_edit.clear()
        self.description_edit.clear()
        self.active_check.setChecked(True)
        self.csv_format_combo.setCurrentIndex(0)
        
        self.trade_count_label.setText("-")
        self.created_label.setText("-")
        self.updated_label.setText("-")
        
        self.duplicate_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.clear_data_btn.setEnabled(False)
        
        self._reset_change_tracking()
    
    def _on_details_changed(self) -> None:
        """Handle changes to profile details"""
        if self.current_profile:
            self.save_btn.setEnabled(True)
            self.revert_btn.setEnabled(True)
    
    def _reset_change_tracking(self) -> None:
        """Reset change tracking"""
        self.save_btn.setEnabled(False)
        self.revert_btn.setEnabled(False)
    
    def _save_profile(self) -> None:
        """Save changes to the current profile"""
        if not self.current_profile:
            return
        
        try:
            # Validate name
            name = self.name_edit.text().strip()
            if not name:
                QMessageBox.warning(self, "Validation Error", "Profile name cannot be empty.")
                return
            
            # Check if name is unique (excluding current profile)
            if not self.profile_service.validate_profile_name(name, self.current_profile.id):
                QMessageBox.warning(self, "Validation Error", f"Profile name '{name}' already exists.")
                return
            
            # Update profile
            updated_profile = self.profile_service.update_profile(
                self.current_profile.id,
                name=name,
                description=self.description_edit.toPlainText().strip() or None,
                is_active=self.active_check.isChecked(),
                default_csv_format=self.csv_format_combo.currentText()
            )
            
            if updated_profile:
                QMessageBox.information(self, "Success", "Profile updated successfully.")
                self._refresh_profiles()
                
                # Reselect the updated profile
                for i in range(self.profile_list.count()):
                    item = self.profile_list.item(i)
                    if item.data(Qt.UserRole).id == updated_profile.id:
                        self.profile_list.setCurrentItem(item)
                        break
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to update profile: {e}")
    
    def _revert_changes(self) -> None:
        """Revert changes to the current profile"""
        if self.current_profile:
            self._load_profile_details(self.current_profile)
    
    def _create_new_profile(self) -> None:
        """Create a new profile"""
        dialog = NewProfileDialog(self.profile_service, self)
        if dialog.exec() == QDialog.Accepted:
            self._refresh_profiles()
            
            # Select the new profile
            new_profile_id = dialog.get_created_profile_id()
            if new_profile_id:
                for i in range(self.profile_list.count()):
                    item = self.profile_list.item(i)
                    if item.data(Qt.UserRole).id == new_profile_id:
                        self.profile_list.setCurrentItem(item)
                        break
    
    def _duplicate_profile(self) -> None:
        """Duplicate the selected profile"""
        if not self.current_profile:
            return
        
        name, ok = QInputDialog.getText(
            self, "Duplicate Profile",
            f"Enter name for duplicate of '{self.current_profile.name}':",
            text=f"{self.current_profile.name} Copy"
        )
        
        if ok and name.strip():
            try:
                new_profile = self.profile_service.duplicate_profile(
                    self.current_profile.id, name.strip()
                )
                QMessageBox.information(self, "Success", f"Profile '{new_profile.name}' created successfully.")
                self._refresh_profiles()
                
                # Select the new profile
                for i in range(self.profile_list.count()):
                    item = self.profile_list.item(i)
                    if item.data(Qt.UserRole).id == new_profile.id:
                        self.profile_list.setCurrentItem(item)
                        break
                        
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to duplicate profile: {e}")
    
    def _delete_profile(self) -> None:
        """Delete the selected profile"""
        if not self.current_profile:
            return
        
        # Check if profile has trades
        summary = self.profile_service.get_profile_summary(self.current_profile.id)
        trade_count = summary.get("trade_count", 0)
        can_delete = summary.get("can_delete", False)
        
        # If profile has trades, offer force delete option
        if not can_delete and trade_count > 0:
            reply = QMessageBox.question(
                self, "Confirm Force Delete",
                f"Profile '{self.current_profile.name}' has {trade_count} associated trades.\n\n"
                f"⚠️ WARNING: Force deleting will permanently remove:\n"
                f"• The profile\n"
                f"• All {trade_count} associated trades\n"
                f"• This action cannot be undone!\n\n"
                f"Do you want to force delete this profile?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                try:
                    if self.profile_service.delete_profile(self.current_profile.id, force=True):
                        QMessageBox.information(self, "Success", f"Profile and {trade_count} trades deleted successfully.")
                        self._refresh_profiles()
                    else:
                        QMessageBox.warning(self, "Error", "Profile could not be deleted.")
                        
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to delete profile: {e}")
        else:
            # Normal deletion (no trades)
            reply = QMessageBox.question(
                self, "Confirm Delete",
                f"Are you sure you want to delete profile '{self.current_profile.name}'?\n\n"
                f"This action cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                try:
                    if self.profile_service.delete_profile(self.current_profile.id):
                        QMessageBox.information(self, "Success", "Profile deleted successfully.")
                        self._refresh_profiles()
                    else:
                        QMessageBox.warning(self, "Error", "Profile could not be deleted.")
                        
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to delete profile: {e}")
    
    def _clear_profile_data(self) -> None:
        """Clear all data (trades) for the selected profile"""
        if not self.current_profile:
            return
        
        # Get current trade count for confirmation
        try:
            summary = self.profile_service.get_profile_summary(self.current_profile.id)
            trade_count = summary.get("trade_count", 0)
        except Exception:
            trade_count = 0
        
        if trade_count == 0:
            QMessageBox.information(
                self, "No Data", 
                f"Profile '{self.current_profile.name}' has no trades to delete."
            )
            return
        
        # Confirmation dialog with strong warning
        reply = QMessageBox.question(
            self, "Confirm Clear All Data",
            f"⚠️ WARNING: This will permanently delete ALL DATA for profile '{self.current_profile.name}':\n\n"
            f"• {trade_count} trades will be permanently deleted\n"
            f"• The profile itself will remain intact\n"
            f"• This action CANNOT be undone!\n\n"
            f"Are you absolutely sure you want to clear all data for this profile?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Double confirmation for safety
            reply2 = QMessageBox.question(
                self, "Final Confirmation",
                f"Last chance to cancel!\n\n"
                f"This will delete {trade_count} trades from '{self.current_profile.name}'.\n\n"
                f"Proceed with data deletion?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply2 == QMessageBox.Yes:
                try:
                    result = self.profile_service.delete_profile_data(self.current_profile.id)
                    trades_deleted = result.get('trades_deleted', 0)
                    
                    QMessageBox.information(
                        self, "Data Cleared",
                        f"Successfully cleared all data for profile '{self.current_profile.name}'.\n\n"
                        f"Trades deleted: {trades_deleted}"
                    )
                    
                    # Refresh the profile details to update trade count
                    self._load_profile_details(self.current_profile)
                    
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to clear profile data: {e}")


class NewProfileDialog(QDialog):
    """Dialog for creating a new profile"""
    
    def __init__(self, profile_service: ProfileService, parent=None) -> None:
        super().__init__(parent)
        self.profile_service = profile_service
        self.created_profile_id: Optional[int] = None
        
        self.setWindowTitle("Create New Profile")
        self.setModal(True)
        self.resize(400, 300)
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        
        # Form
        form_layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._validate_form)
        form_layout.addRow("Name:", self.name_edit)
        
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(100)
        form_layout.addRow("Description:", self.description_edit)
        
        self.csv_format_combo = QComboBox()
        self.csv_format_combo.addItems(["tradersync", "custom"])
        form_layout.addRow("Default CSV Format:", self.csv_format_combo)
        
        layout.addLayout(form_layout)
        
        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self._create_profile)
        button_box.rejected.connect(self.reject)
        
        self.ok_button = button_box.button(QDialogButtonBox.Ok)
        self.ok_button.setEnabled(False)
        
        layout.addWidget(button_box)
        
        # Focus on name field
        self.name_edit.setFocus()
    
    def _validate_form(self) -> None:
        """Validate the form and enable/disable OK button"""
        name = self.name_edit.text().strip()
        self.ok_button.setEnabled(bool(name))
    
    def _create_profile(self) -> None:
        """Create the new profile"""
        name = self.name_edit.text().strip()
        description = self.description_edit.toPlainText().strip()
        csv_format = self.csv_format_combo.currentText()
        
        if not name:
            QMessageBox.warning(self, "Validation Error", "Profile name cannot be empty.")
            return
        
        try:
            new_profile = self.profile_service.create_profile(
                name=name,
                description=description or None,
                csv_format=csv_format
            )
            
            self.created_profile_id = new_profile.id
            QMessageBox.information(self, "Success", f"Profile '{new_profile.name}' created successfully.")
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create profile: {e}")
    
    def get_created_profile_id(self) -> Optional[int]:
        """Get the ID of the created profile"""
        return self.created_profile_id
