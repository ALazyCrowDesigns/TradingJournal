"""
Profile selector widget for the main window toolbar
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from ..dto import ProfileOut
from ..services.profile_service import ProfileService
from .profile_dialog import ProfileManagerDialog, ProfileSelectionDialog


class ProfileSelectorWidget(QWidget):
    """Widget for selecting and managing profiles in the main window"""

    profileChanged = Signal(int)  # profile_id

    def __init__(self, profile_service: ProfileService, parent=None) -> None:
        super().__init__(parent)
        self.profile_service = profile_service
        self.current_profile_id: int = 1
        self.current_profile: ProfileOut | None = None

        self._setup_ui()
        self._load_profiles()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Profile label
        self.profile_label = QLabel("Profile:")
        layout.addWidget(self.profile_label)

        # Profile combo box
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(150)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        layout.addWidget(self.profile_combo)

        # Manage button
        self.manage_btn = QPushButton("Manage...")
        self.manage_btn.clicked.connect(self._open_profile_manager)
        layout.addWidget(self.manage_btn)

    def _load_profiles(self) -> None:
        """Load profiles into the combo box"""
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()

        try:
            profiles = self.profile_service.list_active_profiles()

            if not profiles:
                # No active profiles, ensure default exists
                default_profile = self.profile_service.get_default_profile()
                profiles = [default_profile]

            current_index = 0
            for i, profile in enumerate(profiles):
                self.profile_combo.addItem(profile.name, profile.id)
                if profile.id == self.current_profile_id:
                    current_index = i
                    self.current_profile = profile

            self.profile_combo.setCurrentIndex(current_index)

            # If we couldn't find the current profile, use the first one
            if current_index == 0 and profiles:
                self.current_profile_id = profiles[0].id
                self.current_profile = profiles[0]

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load profiles: {e}")
        finally:
            self.profile_combo.blockSignals(False)

    def _on_profile_changed(self) -> None:
        """Handle profile selection change"""
        if self.profile_combo.currentData():
            new_profile_id = self.profile_combo.currentData()
            if new_profile_id != self.current_profile_id:
                self.set_current_profile(new_profile_id)

    def set_current_profile(self, profile_id: int) -> None:
        """Set the current profile"""
        try:
            # Validate the profile exists and is active
            profile = self.profile_service.switch_to_profile(profile_id)

            self.current_profile_id = profile_id
            self.current_profile = profile

            # Update combo box selection
            for i in range(self.profile_combo.count()):
                if self.profile_combo.itemData(i) == profile_id:
                    self.profile_combo.blockSignals(True)
                    self.profile_combo.setCurrentIndex(i)
                    self.profile_combo.blockSignals(False)
                    break

            # Emit signal
            self.profileChanged.emit(profile_id)

        except Exception as e:
            QMessageBox.critical(self, "Profile Switch Error", f"Failed to switch to profile: {e}")
            # Revert to previous selection
            self._load_profiles()

    def get_current_profile_id(self) -> int:
        """Get the current profile ID"""
        return self.current_profile_id

    def get_current_profile(self) -> ProfileOut | None:
        """Get the current profile"""
        return self.current_profile

    def refresh_profiles(self) -> None:
        """Refresh the profile list (call after profile changes)"""
        old_profile_id = self.current_profile_id
        self._load_profiles()

        # Try to maintain the same selection
        if old_profile_id != self.current_profile_id:
            self.profileChanged.emit(self.current_profile_id)

    def _open_profile_manager(self) -> None:
        """Open the profile management dialog"""
        dialog = ProfileManagerDialog(self.profile_service, self)
        if dialog.exec():
            # Refresh profiles after management
            old_profile_id = self.current_profile_id
            self._load_profiles()

            # If the current profile was changed, emit signal
            if old_profile_id != self.current_profile_id:
                self.profileChanged.emit(self.current_profile_id)

    def show_profile_selection_dialog(self) -> int | None:
        """Show profile selection dialog and return selected profile ID"""
        dialog = ProfileSelectionDialog(self.profile_service, self.current_profile_id, self)
        if dialog.exec() == ProfileSelectionDialog.Accepted:
            selected_id = dialog.get_selected_profile_id()
            if selected_id and selected_id != self.current_profile_id:
                self.set_current_profile(selected_id)
                return selected_id
        return None
