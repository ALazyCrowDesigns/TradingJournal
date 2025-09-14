#!/usr/bin/env python3
"""
Demo script showing the new CRUD functionality with session management.
Run this to test the new features without the full GUI.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from journal.container import ApplicationContainer
from journal.services.session_manager import SessionTransactionManager


def demo_crud_operations():
    """Demonstrate CRUD operations with session management"""

    print("🚀 Trading Journal CRUD Demo")
    print("=" * 50)

    # Initialize container and session manager
    container = ApplicationContainer()
    trade_repo = container.trade_repository()
    session_manager = SessionTransactionManager(trade_repo)

    print("\n1. Creating new trades...")

    # Create some test trades
    trade1_id = session_manager.create_trade(
        {
            "symbol": "AAPL",
            "side": "LONG",
            "size": 100,
            "entry": 150.00,
            "exit": 155.00,
            "pnl": 500.00,
            "trade_date": date(2025, 9, 13),
        }
    )
    print(f"   ✓ Created AAPL trade: {trade1_id[:8]}...")

    trade2_id = session_manager.create_trade(
        {
            "symbol": "TSLA",
            "side": "SHORT",
            "size": 50,
            "entry": 800.00,
            "exit": 780.00,
            "pnl": 1000.00,
            "trade_date": date(2025, 9, 12),
        }
    )
    print(f"   ✓ Created TSLA trade: {trade2_id[:8]}...")

    print("\n2. Session state:")
    session_info = session_manager.get_session_info()
    print(f"   • Pending creates: {session_info['pending_creates']}")
    print(f"   • Can undo: {session_info['can_undo']}")
    print(f"   • Undo description: {session_info['undo_description']}")

    print("\n3. Updating a trade...")
    success = session_manager.update_trade(trade1_id, {"pnl": 600.00, "exit": 156.00})
    print(f"   ✓ Updated AAPL trade: {success}")

    print("\n4. Session state after update:")
    session_info = session_manager.get_session_info()
    print(f"   • Pending updates: {session_info['pending_updates']}")
    print(f"   • Can undo: {session_info['can_undo']}")

    print("\n5. Demonstrating undo/redo...")
    undo_desc = session_manager.undo()
    print(f"   ✓ Undone: {undo_desc}")

    redo_desc = session_manager.redo()
    print(f"   ✓ Redone: {redo_desc}")

    print("\n6. Getting all trades...")
    all_trades = session_manager.get_all_trades()
    print(f"   • Total trades in session: {len(all_trades)}")
    for trade in all_trades:
        if str(trade.get("id")) in [trade1_id, trade2_id]:
            print(
                f"   • {trade['symbol']}: {trade['side']} {trade['size']} @ ${trade['entry']} → ${trade['exit']} = ${trade['pnl']}"
            )

    print("\n7. Deleting a trade...")
    success = session_manager.delete_trade(trade2_id)
    print(f"   ✓ Deleted TSLA trade: {success}")

    print("\n8. Final session state:")
    session_info = session_manager.get_session_info()
    print(f"   • Pending creates: {session_info['pending_creates']}")
    print(f"   • Pending updates: {session_info['pending_updates']}")
    print(f"   • Pending deletes: {session_info['pending_deletes']}")
    print(f"   • Has unsaved changes: {session_info['has_unsaved_changes']}")

    print("\n9. Simulating save checkpoint...")
    save_result = session_manager.save()
    print(
        f"   ✓ Saved {save_result['saved_changes']} changes at timestamp {save_result['timestamp']}"
    )

    print("\n10. Testing rollback (instead of commit)...")
    print("    Note: In real usage, you'd call commit() to save to database")
    session_manager.rollback()
    print("    ✓ All changes rolled back")

    final_info = session_manager.get_session_info()
    print(f"    • Has unsaved changes: {final_info['has_unsaved_changes']}")

    print("\n✅ Demo completed! The new CRUD system provides:")
    print("   • Create, Update, Delete operations")
    print("   • Full undo/redo with command pattern")
    print("   • Session-based transactions (changes not permanent until commit)")
    print("   • Save/rollback functionality")
    print("   • Session persistence across app restarts")


if __name__ == "__main__":
    demo_crud_operations()
