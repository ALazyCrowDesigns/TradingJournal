"""Compute trading metrics from bar data."""

from datetime import date

from .models import BackfillRow, PolygonBar, SessionMetrics
from .time_windows import categorize_bar_by_time


def compute_backfill_row(
    symbol: str, 
    trade_date: date, 
    bars_30min: list[PolygonBar], 
    daily_bar: PolygonBar | None
) -> BackfillRow:
    """Compute complete backfill metrics from 30-minute bars and daily aggregate.
    
    Args:
        symbol: Stock symbol
        trade_date: Trading date
        bars_30min: List of 30-minute bars for extended hours
        daily_bar: Daily aggregate bar (authoritative for OHLC and volume)
        
    Returns:
        BackfillRow with all computed metrics
    """
    # Initialize session metrics
    pre_metrics = SessionMetrics()
    reg_metrics = SessionMetrics()
    ah_metrics = SessionMetrics()
    
    # Categorize and process 30-minute bars
    for bar in bars_30min:
        session = categorize_bar_by_time(bar.t, trade_date)
        
        if session == "pre":
            pre_metrics.update_from_bar(bar)
        elif session == "reg":
            reg_metrics.update_from_bar(bar)
        elif session == "ah":
            ah_metrics.update_from_bar(bar)
        # Ignore bars outside defined sessions
    
    # Create backfill row
    row = BackfillRow(
        symbol=symbol,
        trade_date=trade_date,
        pre_high=pre_metrics.high,
        pre_low=pre_metrics.low,
        ah_high=ah_metrics.high,
        ah_low=ah_metrics.low,
    )
    
    # Use daily aggregate as authoritative source for OHLC and volume
    if daily_bar:
        row.open_price = daily_bar.o
        row.hod = daily_bar.h
        row.lod = daily_bar.l
        row.day_volume = daily_bar.v
    else:
        # Fallback to regular session bars if daily aggregate is missing
        # This should be rare but provides robustness
        if reg_metrics.high is not None and reg_metrics.low is not None:
            row.hod = reg_metrics.high
            row.lod = reg_metrics.low
            
            # Try to get open from first regular session bar
            for bar in bars_30min:
                if categorize_bar_by_time(bar.t, trade_date) == "reg":
                    row.open_price = bar.o
                    break
        
        # day_volume stays None if no daily aggregate (as specified)
    
    return row


def compute_backfill_rows(
    requests_and_data: list[tuple[str, date, list[PolygonBar], PolygonBar | None]]
) -> list[BackfillRow]:
    """Compute backfill rows for multiple symbol/date pairs.
    
    Args:
        requests_and_data: List of (symbol, trade_date, bars_30min, daily_bar) tuples
        
    Returns:
        List of BackfillRow objects with computed metrics
    """
    rows = []
    
    for symbol, trade_date, bars_30min, daily_bar in requests_and_data:
        row = compute_backfill_row(symbol, trade_date, bars_30min, daily_bar)
        rows.append(row)
    
    return rows


def validate_backfill_row(row: BackfillRow) -> list[str]:
    """Validate a backfill row and return list of issues found.
    
    Args:
        row: BackfillRow to validate
        
    Returns:
        List of validation error messages (empty if valid)
    """
    issues = []
    
    # Check for impossible price relationships
    if row.pre_high is not None and row.pre_low is not None:
        if row.pre_high < row.pre_low:
            issues.append(f"Premarket high ({row.pre_high}) < low ({row.pre_low})")
    
    if row.ah_high is not None and row.ah_low is not None:
        if row.ah_high < row.ah_low:
            issues.append(f"After-hours high ({row.ah_high}) < low ({row.ah_low})")
    
    if row.hod is not None and row.lod is not None:
        if row.hod < row.lod:
            issues.append(f"Day high ({row.hod}) < low ({row.lod})")
    
    # Check for negative volume
    if row.day_volume is not None and row.day_volume < 0:
        issues.append(f"Negative volume: {row.day_volume}")
    
    # Check for negative prices
    price_fields = [
        ("pre_high", row.pre_high),
        ("pre_low", row.pre_low),
        ("open_price", row.open_price),
        ("hod", row.hod),
        ("lod", row.lod),
        ("ah_high", row.ah_high),
        ("ah_low", row.ah_low),
    ]
    
    for field_name, price in price_fields:
        if price is not None and price <= 0:
            issues.append(f"Non-positive {field_name}: {price}")
    
    return issues
