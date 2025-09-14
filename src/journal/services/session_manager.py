"""
Session-based transaction manager for CRUD operations with undo/redo support.
Keeps all changes in memory until explicitly committed to database.
"""

from __future__ import annotations

import copy
import uuid
from collections import deque
from datetime import date, datetime
from enum import Enum
from typing import Any, Protocol

from ..db.models import Trade


class OperationType(Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class Command(Protocol):
    """Command pattern interface for undo/redo operations"""
    
    def execute(self) -> None:
        """Execute the command"""
        ...
    
    def undo(self) -> None:
        """Undo the command"""
        ...
    
    def description(self) -> str:
        """Human-readable description of the command"""
        ...


class TradeCommand:
    """Command for trade operations"""
    
    def __init__(
        self,
        session_manager: SessionTransactionManager,
        operation: OperationType,
        trade_data: dict[str, Any],
        original_data: dict[str, Any] | None = None,
    ):
        self.session_manager = session_manager
        self.operation = operation
        self.trade_data = trade_data.copy()
        self.original_data = original_data.copy() if original_data else None
        self.trade_id = trade_data.get('id') or str(uuid.uuid4())
        
    def execute(self) -> None:
        """Execute the trade command"""
        if self.operation == OperationType.CREATE:
            self.session_manager._create_trade_internal(self.trade_id, self.trade_data)
        elif self.operation == OperationType.UPDATE:
            self.session_manager._update_trade_internal(self.trade_id, self.trade_data)
        elif self.operation == OperationType.DELETE:
            self.session_manager._delete_trade_internal(self.trade_id)
    
    def undo(self) -> None:
        """Undo the trade command"""
        if self.operation == OperationType.CREATE:
            self.session_manager._delete_trade_internal(self.trade_id)
        elif self.operation == OperationType.UPDATE:
            if self.original_data:
                self.session_manager._update_trade_internal(self.trade_id, self.original_data)
        elif self.operation == OperationType.DELETE:
            if self.original_data:
                self.session_manager._create_trade_internal(self.trade_id, self.original_data)
    
    def description(self) -> str:
        """Get command description"""
        symbol = self.trade_data.get('symbol', 'Unknown')
        if self.operation == OperationType.CREATE:
            return f"Create trade {symbol}"
        elif self.operation == OperationType.UPDATE:
            return f"Update trade {symbol}"
        elif self.operation == OperationType.DELETE:
            return f"Delete trade {symbol}"
        return "Unknown operation"


class SessionTransactionManager:
    """
    Manages uncommitted changes to trades in memory with full undo/redo support.
    Changes are not persisted to database until commit() is called.
    """
    
    def __init__(self, trade_repository):
        self.trade_repository = trade_repository
        
        # Session state
        self._session_trades: dict[str, dict[str, Any]] = {}  # id -> trade_data
        self._deleted_trades: set[str] = set()  # IDs of deleted trades
        self._original_trades: dict[str, dict[str, Any]] = {}  # id -> original_data (for rollback)
        
        # Command history for undo/redo
        self._command_history: deque[Command] = deque(maxlen=100)  # Limit to 100 operations
        self._undo_stack: deque[Command] = deque(maxlen=100)
        self._current_command_index = 0
        
        # Session metadata
        self._session_started = datetime.now()
        self._last_save_time: datetime | None = None
        self._has_unsaved_changes = False
        
        # Callbacks for UI updates
        self._change_callbacks: list[callable] = []
        
    def add_change_callback(self, callback: callable) -> None:
        """Add callback to be notified when data changes"""
        self._change_callbacks.append(callback)
    
    def remove_change_callback(self, callback: callable) -> None:
        """Remove change callback"""
        if callback in self._change_callbacks:
            self._change_callbacks.remove(callback)
    
    def _notify_changes(self) -> None:
        """Notify all callbacks that data has changed"""
        for callback in self._change_callbacks:
            try:
                callback()
            except Exception as e:
                print(f"Error in change callback: {e}")
    
    def _execute_command(self, command: Command) -> None:
        """Execute a command and add it to history"""
        command.execute()
        
        # Clear any redo history when new command is executed
        self._undo_stack.clear()
        
        # Add to command history
        self._command_history.append(command)
        self._current_command_index = len(self._command_history)
        
        self._has_unsaved_changes = True
        self._notify_changes()
    
    def create_trade(self, trade_data: dict[str, Any]) -> str:
        """Create a new trade in the session"""
        trade_id = str(uuid.uuid4())
        trade_data = trade_data.copy()
        trade_data['id'] = trade_id
        
        # Ensure required fields
        if 'trade_date' not in trade_data:
            trade_data['trade_date'] = date.today()
        if 'profile_id' not in trade_data:
            trade_data['profile_id'] = 1
            
        command = TradeCommand(self, OperationType.CREATE, trade_data)
        self._execute_command(command)
        return trade_id
    
    def update_trade(self, trade_id: str, updates: dict[str, Any]) -> bool:
        """Update an existing trade in the session"""
        # Get current trade data (from session or database)
        current_data = self.get_trade(trade_id)
        if not current_data:
            return False
        
        # Store original data for undo
        original_data = current_data.copy()
        
        # Apply updates
        updated_data = current_data.copy()
        updated_data.update(updates)
        
        command = TradeCommand(self, OperationType.UPDATE, updated_data, original_data)
        self._execute_command(command)
        return True
    
    def delete_trade(self, trade_id: str) -> bool:
        """Delete a trade from the session"""
        # Get current trade data for undo
        current_data = self.get_trade(trade_id)
        if not current_data:
            return False
        
        command = TradeCommand(self, OperationType.DELETE, {'id': trade_id}, current_data)
        self._execute_command(command)
        return True
    
    def _create_trade_internal(self, trade_id: str, trade_data: dict[str, Any]) -> None:
        """Internal method to create trade (used by commands)"""
        self._session_trades[trade_id] = trade_data.copy()
        self._deleted_trades.discard(trade_id)
    
    def _update_trade_internal(self, trade_id: str, trade_data: dict[str, Any]) -> None:
        """Internal method to update trade (used by commands)"""
        if trade_id not in self._original_trades and trade_id not in self._session_trades:
            # Load original from database if not already cached
            original = self._load_trade_from_db(trade_id)
            if original:
                self._original_trades[trade_id] = original
        
        self._session_trades[trade_id] = trade_data.copy()
        self._deleted_trades.discard(trade_id)
    
    def _delete_trade_internal(self, trade_id: str) -> None:
        """Internal method to delete trade (used by commands)"""
        if trade_id in self._session_trades:
            # If it was created in this session, just remove it
            if trade_id not in self._original_trades:
                del self._session_trades[trade_id]
            else:
                # Mark as deleted but keep the data for undo
                self._deleted_trades.add(trade_id)
        else:
            # Load from database and mark as deleted
            original = self._load_trade_from_db(trade_id)
            if original:
                self._original_trades[trade_id] = original
                self._deleted_trades.add(trade_id)
    
    def _load_trade_from_db(self, trade_id: str) -> dict[str, Any] | None:
        """Load trade data from database"""
        try:
            with self.trade_repository._session_scope() as session:
                trade = session.get(Trade, trade_id)
                if trade:
                    return {
                        'id': trade.id,
                        'profile_id': trade.profile_id,
                        'trade_date': trade.trade_date,
                        'symbol': trade.symbol,
                        'side': trade.side,
                        'size': trade.size,
                        'entry': trade.entry,
                        'exit': trade.exit,
                        'pnl': trade.pnl,
                        'return_pct': trade.return_pct,
                        'notes': trade.notes,
                        'prev_close': trade.prev_close,
                        'created_at': trade.created_at,
                    }
        except Exception as e:
            print(f"Error loading trade {trade_id}: {e}")
        return None
    
    def get_trade(self, trade_id: str) -> dict[str, Any] | None:
        """Get trade data from session or database"""
        if trade_id in self._deleted_trades:
            return None
        
        if trade_id in self._session_trades:
            return self._session_trades[trade_id].copy()
        
        # Load from database
        return self._load_trade_from_db(trade_id)
    
    def get_all_trades(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get all trades from session and database, applying filters"""
        all_trades = []
        
        # Get trades from database first
        try:
            db_trades, _ = self.trade_repository.get_paginated(
                limit=10000,  # Large limit to get all
                offset=0,
                filters=filters
            )
            
            for trade in db_trades:
                trade_id = str(trade['id'])
                if trade_id not in self._deleted_trades:
                    # Use session version if available, otherwise database version
                    if trade_id in self._session_trades:
                        all_trades.append(self._session_trades[trade_id].copy())
                    else:
                        all_trades.append(trade.copy())
        except Exception as e:
            print(f"Error loading trades from database: {e}")
        
        # Add new trades from session
        for trade_id, trade_data in self._session_trades.items():
            if trade_id not in self._original_trades and trade_id not in self._deleted_trades:
                # This is a new trade created in session
                if self._matches_filters(trade_data, filters):
                    all_trades.append(trade_data.copy())
        
        return all_trades
    
    def _matches_filters(self, trade_data: dict[str, Any], filters: dict[str, Any] | None) -> bool:
        """Check if trade data matches the given filters"""
        if not filters:
            return True
        
        # Simple filter matching - extend as needed
        if symbol_filter := filters.get('symbol'):
            if symbol_filter.upper() not in trade_data.get('symbol', '').upper():
                return False
        
        if side_filter := filters.get('side'):
            if trade_data.get('side') != side_filter:
                return False
        
        if date_from := filters.get('date_from'):
            if trade_data.get('trade_date', date.min) < date_from:
                return False
        
        if date_to := filters.get('date_to'):
            if trade_data.get('trade_date', date.max) > date_to:
                return False
        
        return True
    
    def can_undo(self) -> bool:
        """Check if undo is possible"""
        return len(self._command_history) > 0 and self._current_command_index > 0
    
    def can_redo(self) -> bool:
        """Check if redo is possible"""
        return len(self._undo_stack) > 0
    
    def undo(self) -> str | None:
        """Undo the last operation"""
        if not self.can_undo():
            return None
        
        self._current_command_index -= 1
        command = self._command_history[self._current_command_index]
        
        command.undo()
        self._undo_stack.append(command)
        
        self._has_unsaved_changes = True
        self._notify_changes()
        
        return command.description()
    
    def redo(self) -> str | None:
        """Redo the last undone operation"""
        if not self.can_redo():
            return None
        
        command = self._undo_stack.pop()
        command.execute()
        
        self._current_command_index += 1
        self._has_unsaved_changes = True
        self._notify_changes()
        
        return command.description()
    
    def get_undo_description(self) -> str | None:
        """Get description of operation that would be undone"""
        if not self.can_undo():
            return None
        return self._command_history[self._current_command_index - 1].description()
    
    def get_redo_description(self) -> str | None:
        """Get description of operation that would be redone"""
        if not self.can_redo():
            return None
        return self._undo_stack[-1].description()
    
    def save(self) -> dict[str, int]:
        """Save changes to a temporary state (but not to database)"""
        self._last_save_time = datetime.now()
        # In this implementation, "save" just marks a checkpoint
        # The actual database commit happens only on commit()
        return {
            "saved_changes": len(self._session_trades) + len(self._deleted_trades),
            "timestamp": int(self._last_save_time.timestamp())
        }
    
    def commit(self) -> dict[str, int]:
        """Commit all changes to the database"""
        created = 0
        updated = 0
        deleted = 0
        errors = 0
        
        try:
            with self.trade_repository._session_scope() as session:
                # Handle deletions first
                for trade_id in self._deleted_trades:
                    try:
                        trade = session.get(Trade, trade_id)
                        if trade:
                            session.delete(trade)
                            deleted += 1
                    except Exception as e:
                        print(f"Error deleting trade {trade_id}: {e}")
                        errors += 1
                
                # Handle creates and updates
                for trade_id, trade_data in self._session_trades.items():
                    try:
                        if trade_id in self._original_trades:
                            # This is an update
                            trade = session.get(Trade, trade_id)
                            if trade:
                                for key, value in trade_data.items():
                                    if key != 'id':  # Don't update the ID
                                        setattr(trade, key, value)
                                updated += 1
                        else:
                            # This is a create
                            trade_data_copy = trade_data.copy()
                            if 'id' in trade_data_copy:
                                del trade_data_copy['id']  # Let database assign ID
                            
                            trade = Trade(**trade_data_copy)
                            session.add(trade)
                            created += 1
                    except Exception as e:
                        print(f"Error saving trade {trade_id}: {e}")
                        errors += 1
                
                # Commit the transaction
                session.commit()
                
                # Clear session state after successful commit
                self.clear_session()
                
        except Exception as e:
            print(f"Error committing transaction: {e}")
            errors += 1
        
        return {
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "errors": errors
        }
    
    def rollback(self) -> None:
        """Rollback all changes in the session"""
        self.clear_session()
        self._notify_changes()
    
    def clear_session(self) -> None:
        """Clear all session state"""
        self._session_trades.clear()
        self._deleted_trades.clear()
        self._original_trades.clear()
        self._command_history.clear()
        self._undo_stack.clear()
        self._current_command_index = 0
        self._has_unsaved_changes = False
        self._last_save_time = None
    
    def has_unsaved_changes(self) -> bool:
        """Check if there are unsaved changes"""
        return self._has_unsaved_changes
    
    def get_session_info(self) -> dict[str, Any]:
        """Get information about the current session"""
        return {
            "session_started": self._session_started,
            "last_save_time": self._last_save_time,
            "has_unsaved_changes": self._has_unsaved_changes,
            "pending_creates": len([t for t in self._session_trades.values() 
                                  if t.get('id') not in self._original_trades]),
            "pending_updates": len([t for t in self._session_trades.values() 
                                  if t.get('id') in self._original_trades]),
            "pending_deletes": len(self._deleted_trades),
            "can_undo": self.can_undo(),
            "can_redo": self.can_redo(),
            "undo_description": self.get_undo_description(),
            "redo_description": self.get_redo_description(),
        }
    
    def refresh_from_database(self) -> None:
        """
        Refresh session manager's understanding of database state.
        This should be called after external database changes (like CSV import)
        to ensure the session manager sees the latest data.
        
        Note: This preserves all unsaved session changes while ensuring
        fresh data is loaded from the database on the next data access.
        """
        # Clear the repository cache to force fresh data retrieval
        # This is critical after CSV imports or other external database changes
        if hasattr(self.trade_repository, '_cache') and self.trade_repository._cache:
            self.trade_repository._cache.clear()
            print("Repository cache cleared - fresh data will be loaded")