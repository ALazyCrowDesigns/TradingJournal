"""
Session persistence for saving/restoring session state across application restarts.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..config import settings


class SessionPersistence:
    """Handles saving and loading session state to/from disk"""

    def __init__(self, session_file: str = "session_state.json"):
        self.session_file = Path(settings.db_path).parent / session_file

    def save_session_state(self, session_manager) -> bool:
        """Save current session state to disk"""
        try:
            state = {
                "version": "1.0",
                "saved_at": datetime.now().isoformat(),
                "session_started": session_manager._session_started.isoformat(),
                "last_save_time": (
                    session_manager._last_save_time.isoformat()
                    if session_manager._last_save_time
                    else None
                ),
                "has_unsaved_changes": session_manager._has_unsaved_changes,
                # Session data
                "session_trades": self._serialize_trades(session_manager._session_trades),
                "deleted_trades": list(session_manager._deleted_trades),
                "original_trades": self._serialize_trades(session_manager._original_trades),
                # Command history for undo/redo
                "command_history": self._serialize_commands(session_manager._command_history),
                "current_command_index": session_manager._current_command_index,
            }

            # Write to temporary file first, then rename for atomic operation
            temp_file = self.session_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=self._json_serializer)

            # Atomic rename
            temp_file.replace(self.session_file)
            return True

        except Exception as e:
            print(f"Error saving session state: {e}")
            return False

    def load_session_state(self, session_manager) -> bool:
        """Load session state from disk"""
        if not self.session_file.exists():
            return False

        try:
            with open(self.session_file, encoding="utf-8") as f:
                state = json.load(f)

            # Validate version
            if state.get("version") != "1.0":
                print(f"Unsupported session state version: {state.get('version')}")
                return False

            # Clear current session
            session_manager.clear_session()

            # Restore session metadata
            session_manager._session_started = datetime.fromisoformat(state["session_started"])
            if state["last_save_time"]:
                session_manager._last_save_time = datetime.fromisoformat(state["last_save_time"])
            session_manager._has_unsaved_changes = state["has_unsaved_changes"]

            # Restore session data
            session_manager._session_trades = self._deserialize_trades(state["session_trades"])
            session_manager._deleted_trades = set(state["deleted_trades"])
            session_manager._original_trades = self._deserialize_trades(state["original_trades"])

            # Restore command history
            session_manager._command_history = self._deserialize_commands(
                state["command_history"], session_manager
            )
            session_manager._current_command_index = state["current_command_index"]

            # Notify of changes
            session_manager._notify_changes()

            return True

        except Exception as e:
            print(f"Error loading session state: {e}")
            return False

    def clear_session_file(self) -> bool:
        """Remove the session state file"""
        try:
            if self.session_file.exists():
                self.session_file.unlink()
            return True
        except Exception as e:
            print(f"Error clearing session file: {e}")
            return False

    def has_saved_session(self) -> bool:
        """Check if there's a saved session state"""
        return self.session_file.exists()

    def get_session_info(self) -> dict[str, Any] | None:
        """Get basic info about saved session without loading it"""
        if not self.session_file.exists():
            return None

        try:
            with open(self.session_file, encoding="utf-8") as f:
                state = json.load(f)

            return {
                "version": state.get("version"),
                "saved_at": state.get("saved_at"),
                "session_started": state.get("session_started"),
                "has_unsaved_changes": state.get("has_unsaved_changes", False),
                "num_session_trades": len(state.get("session_trades", {})),
                "num_deleted_trades": len(state.get("deleted_trades", [])),
                "num_commands": len(state.get("command_history", [])),
            }
        except Exception as e:
            print(f"Error reading session info: {e}")
            return None

    def _serialize_trades(
        self, trades_dict: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Serialize trades dictionary for JSON storage"""
        serialized = {}
        for trade_id, trade_data in trades_dict.items():
            serialized[trade_id] = trade_data.copy()
            # Convert date objects to ISO format
            if "trade_date" in serialized[trade_id] and isinstance(
                serialized[trade_id]["trade_date"], date
            ):
                serialized[trade_id]["trade_date"] = serialized[trade_id]["trade_date"].isoformat()
            if "created_at" in serialized[trade_id] and isinstance(
                serialized[trade_id]["created_at"], datetime
            ):
                serialized[trade_id]["created_at"] = serialized[trade_id]["created_at"].isoformat()
        return serialized

    def _deserialize_trades(
        self, serialized_trades: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Deserialize trades dictionary from JSON storage"""
        trades = {}
        for trade_id, trade_data in serialized_trades.items():
            trades[trade_id] = trade_data.copy()
            # Convert ISO format back to date objects
            if "trade_date" in trades[trade_id] and isinstance(trades[trade_id]["trade_date"], str):
                trades[trade_id]["trade_date"] = date.fromisoformat(trades[trade_id]["trade_date"])
            if "created_at" in trades[trade_id] and isinstance(trades[trade_id]["created_at"], str):
                trades[trade_id]["created_at"] = datetime.fromisoformat(
                    trades[trade_id]["created_at"]
                )
        return trades

    def _serialize_commands(self, command_history) -> list[dict[str, Any]]:
        """Serialize command history for JSON storage"""
        from ..services.session_manager import TradeCommand

        serialized = []
        for command in command_history:
            if isinstance(command, TradeCommand):
                cmd_data = {
                    "type": "TradeCommand",
                    "operation": command.operation.value,
                    "trade_data": self._serialize_trade_data(command.trade_data),
                    "original_data": (
                        self._serialize_trade_data(command.original_data)
                        if command.original_data
                        else None
                    ),
                    "trade_id": command.trade_id,
                }
                serialized.append(cmd_data)
        return serialized

    def _deserialize_commands(self, serialized_commands: list[dict[str, Any]], session_manager):
        """Deserialize command history from JSON storage"""
        from collections import deque

        from ..services.session_manager import OperationType, TradeCommand

        commands = deque(maxlen=100)
        for cmd_data in serialized_commands:
            if cmd_data["type"] == "TradeCommand":
                operation = OperationType(cmd_data["operation"])
                trade_data = self._deserialize_trade_data(cmd_data["trade_data"])
                original_data = (
                    self._deserialize_trade_data(cmd_data["original_data"])
                    if cmd_data["original_data"]
                    else None
                )

                command = TradeCommand(session_manager, operation, trade_data, original_data)
                command.trade_id = cmd_data["trade_id"]
                commands.append(command)
        return commands

    def _serialize_trade_data(self, trade_data: dict[str, Any] | None) -> dict[str, Any] | None:
        """Serialize individual trade data"""
        if not trade_data:
            return None

        serialized = trade_data.copy()
        if "trade_date" in serialized and isinstance(serialized["trade_date"], date):
            serialized["trade_date"] = serialized["trade_date"].isoformat()
        if "created_at" in serialized and isinstance(serialized["created_at"], datetime):
            serialized["created_at"] = serialized["created_at"].isoformat()
        return serialized

    def _deserialize_trade_data(
        self, serialized_data: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Deserialize individual trade data"""
        if not serialized_data:
            return None

        trade_data = serialized_data.copy()
        if "trade_date" in trade_data and isinstance(trade_data["trade_date"], str):
            trade_data["trade_date"] = date.fromisoformat(trade_data["trade_date"])
        if "created_at" in trade_data and isinstance(trade_data["created_at"], str):
            trade_data["created_at"] = datetime.fromisoformat(trade_data["created_at"])
        return trade_data

    def _json_serializer(self, obj: Any) -> Any:
        """Custom JSON serializer for special types"""
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def auto_save_session(session_manager, persistence: SessionPersistence | None = None) -> None:
    """Auto-save session state if there are unsaved changes"""
    if persistence is None:
        persistence = SessionPersistence()

    if session_manager.has_unsaved_changes():
        persistence.save_session_state(session_manager)


def prompt_restore_session(session_manager, persistence: SessionPersistence | None = None) -> bool:
    """Prompt user to restore saved session and return whether restoration was attempted"""
    if persistence is None:
        persistence = SessionPersistence()

    if not persistence.has_saved_session():
        return False

    # Get session info
    session_info = persistence.get_session_info()
    if not session_info:
        return False

    # This would typically show a dialog in the GUI
    # For now, just auto-restore if there are unsaved changes
    if session_info.get("has_unsaved_changes", False):
        return persistence.load_session_state(session_manager)

    return False
