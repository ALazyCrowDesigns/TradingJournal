"""
Example demonstrating the new architecture benefits

This script shows how to use the dependency injection container
and service layer for various operations.
"""

# Add parent directory to path for imports
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from journal.container import container


def demo_dependency_injection() -> None:
    """Demonstrate dependency injection benefits"""
    print("\n=== Dependency Injection Demo ===")

    # Get services from container - dependencies are automatically injected
    analytics_service = container.analytics_service()
    import_service = container.import_service()

    # Services are properly configured with all dependencies
    print(f"Analytics Service: {analytics_service}")
    print(f"Import Service: {import_service}")

    # The container provides consistent configuration
    print("\nContainer benefits:")
    print("- Centralized configuration")
    print("- Automatic dependency injection")
    print("- Easy testing with mock dependencies")
    print("- Singleton management for shared resources")


def demo_repository_pattern() -> None:
    """Demonstrate repository pattern benefits"""
    print("\n=== Repository Pattern Demo ===")

    # Get repositories
    trade_repo = container.trade_repository()
    symbol_repo = container.symbol_repository()

    # Clean, testable interface for data access
    print("Counting trades...")
    total_trades = trade_repo.count()
    print(f"Total trades in database: {total_trades}")

    # Type-safe queries with filters
    recent_trades, _ = trade_repo.get_paginated(
        limit=5,
        order_by="trade_date",
        order_dir="desc",
        filters={"date_from": date.today() - timedelta(days=30)},
    )

    print(f"Recent trades (last 30 days): {len(recent_trades)}")

    # Repository handles caching automatically
    print("\nFetching symbols with missing fundamentals...")
    missing = symbol_repo.get_missing_fundamentals(limit=10)
    print(f"Symbols needing fundamental data: {missing[:5]}...")


def demo_service_layer() -> None:
    """Demonstrate service layer benefits"""
    print("\n=== Service Layer Demo ===")

    # Services encapsulate business logic
    analytics = container.analytics_service()

    # Get comprehensive analytics with caching
    print("Calculating analytics (cached for 60 seconds)...")
    summary = analytics.get_summary()

    print(f"Total trades: {summary['trades']}")
    print(f"Win rate: {summary['hit_rate']:.1f}%")
    print(f"Net P&L: ${summary['net_pnl']:.2f}")

    # Get performance by date
    print("\nPerformance by month:")
    monthly_perf = analytics.get_performance_by_date(
        start_date=date.today() - timedelta(days=365), end_date=date.today(), group_by="month"
    )

    for month in monthly_perf[-3:]:  # Last 3 months
        print(
            f"  {month['period']}: {month['trades']} trades, "
            f"${month['net_pnl']:.2f} P&L, {month['hit_rate']:.1f}% win rate"
        )


def demo_import_service() -> None:
    """Demonstrate enhanced import service"""
    print("\n=== Import Service Demo ===")

    import_service = container.import_service()

    # Load mapping
    mapping = import_service.load_mapping("src/journal/ingest/mapping.tradersync.json")

    print(f"Loaded mapping for: {mapping.columns.get('symbol', 'Symbol')} column")
    print(f"Date formats supported: {mapping.date_formats}")

    # The import service now supports:
    # - Parallel chunk processing
    # - Progress callbacks
    # - Detailed error reporting
    # - Dry run validation

    print("\nImport features:")
    print("- Chunked processing with configurable workers")
    print("- Progress tracking with callbacks")
    print("- Comprehensive error collection")
    print("- Dry run mode for validation")


def demo_error_handling() -> None:
    """Demonstrate improved error handling"""
    print("\n=== Error Handling Demo ===")

    market_service = container.market_service()

    # Services use structured logging
    print("Services now include structured logging with context")

    # Automatic retry with exponential backoff
    print("Market service includes automatic retry logic")

    # Example: Fetching with bad symbol handles gracefully
    try:
        # This would retry 3 times with exponential backoff
        _ = market_service.get_daily_range(
            "INVALID_SYMBOL_XYZ", date.today() - timedelta(days=7), date.today()
        )
    except Exception as e:
        print(f"Handled error gracefully: {type(e).__name__}")


def demo_performance_improvements() -> None:
    """Demonstrate performance improvements"""
    print("\n=== Performance Improvements ===")

    print("1. Database Optimizations:")
    print("   - Added composite indexes for common queries")
    print("   - Optimized connection pooling with StaticPool")
    print("   - Enabled SQLite performance pragmas")
    print("   - Query result caching with TTL")

    print("\n2. CSV Import Optimizations:")
    print("   - Parallel chunk processing")
    print("   - Batch database operations")
    print("   - Progress tracking")

    print("\n3. GUI Optimizations:")
    print("   - Virtual scrolling with row cache")
    print("   - Debounced fetch operations")
    print("   - Background thread pool")
    print("   - Non-blocking analytics refresh")


def main() -> None:
    """Run all demonstrations"""
    print("Trading Journal Architecture Improvements Demo")
    print("=" * 50)

    # Initialize container resources
    container.init_resources()

    try:
        demo_dependency_injection()
        demo_repository_pattern()
        demo_service_layer()
        demo_import_service()
        demo_error_handling()
        demo_performance_improvements()

        print("\n" + "=" * 50)
        print("Demo completed successfully!")
        print("\nKey Benefits of New Architecture:")
        print("✓ Better testability with dependency injection")
        print("✓ Cleaner code organization with repository pattern")
        print("✓ Improved performance with caching and optimization")
        print("✓ More maintainable with service layer separation")
        print("✓ Enhanced error handling and logging")

    except Exception as e:
        print(f"\nError during demo: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
