"""Time window utilities for converting ET session times to UTC milliseconds."""

from datetime import date, datetime, time, timezone
import sys

from .config import SessionWindows

# Timezone constants - handle Windows timezone data availability
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
    UTC = ZoneInfo("UTC")
except ImportError:
    # Fallback for systems without zoneinfo (older Python)
    import pytz
    ET = pytz.timezone("America/New_York")
    UTC = pytz.UTC
except Exception:
    # Final fallback - use fixed offset (this is less accurate but works)
    # EST/EDT handling would need to be more sophisticated in production
    print("Warning: Using fixed UTC-5 offset for ET. Install tzdata package for accurate timezone handling.")
    from datetime import timezone, timedelta
    ET = timezone(timedelta(hours=-5))  # Simplified - doesn't handle DST
    UTC = timezone.utc


def et_time_to_utc_ms(trade_date: date, hour: int, minute: int) -> int:
    """Convert ET time on a specific date to UTC milliseconds since epoch.
    
    Args:
        trade_date: The trading date
        hour: Hour in ET (24-hour format)
        minute: Minute in ET
        
    Returns:
        UTC milliseconds since Unix epoch
    """
    et_datetime = datetime.combine(trade_date, time(hour, minute), tzinfo=ET)
    utc_datetime = et_datetime.astimezone(UTC)
    return int(utc_datetime.timestamp() * 1000)


def get_session_window_ms(trade_date: date, session: str) -> tuple[int, int]:
    """Get UTC millisecond timestamps for a trading session window.
    
    Args:
        trade_date: The trading date
        session: Session type ('pre', 'reg', 'ah')
        
    Returns:
        Tuple of (start_ms, end_ms) in UTC milliseconds
        
    Raises:
        ValueError: If session type is invalid
    """
    windows = SessionWindows()
    
    if session == "pre":
        start_hour, start_min = windows.PRE_START
        end_hour, end_min = windows.PRE_END
    elif session == "reg":
        start_hour, start_min = windows.REG_START
        end_hour, end_min = windows.REG_END
    elif session == "ah":
        start_hour, start_min = windows.AH_START
        end_hour, end_min = windows.AH_END
    else:
        raise ValueError(f"Invalid session type: {session}. Must be 'pre', 'reg', or 'ah'")
    
    start_ms = et_time_to_utc_ms(trade_date, start_hour, start_min)
    end_ms = et_time_to_utc_ms(trade_date, end_hour, end_min)
    
    return start_ms, end_ms


def get_extended_hours_window_ms(trade_date: date) -> tuple[int, int]:
    """Get UTC millisecond timestamps for the full extended hours window (04:00-20:00 ET).
    
    This covers both premarket and after-hours sessions for efficient 30-minute aggregate fetching.
    
    Args:
        trade_date: The trading date
        
    Returns:
        Tuple of (start_ms, end_ms) covering 04:00-20:00 ET in UTC milliseconds
    """
    windows = SessionWindows()
    
    start_ms = et_time_to_utc_ms(trade_date, *windows.PRE_START)
    end_ms = et_time_to_utc_ms(trade_date, *windows.AH_END)
    
    return start_ms, end_ms


def categorize_bar_by_time(timestamp_ms: int, trade_date: date) -> str | None:
    """Categorize a 30-minute bar by its timestamp into trading session.
    
    Args:
        timestamp_ms: Bar timestamp in UTC milliseconds
        trade_date: The trading date for session window calculation
        
    Returns:
        Session type ('pre', 'reg', 'ah') or None if outside all sessions
    """
    pre_start, pre_end = get_session_window_ms(trade_date, "pre")
    reg_start, reg_end = get_session_window_ms(trade_date, "reg")
    ah_start, ah_end = get_session_window_ms(trade_date, "ah")
    
    if pre_start <= timestamp_ms < pre_end:
        return "pre"
    elif reg_start <= timestamp_ms < reg_end:
        return "reg"
    elif ah_start <= timestamp_ms < ah_end:
        return "ah"
    else:
        return None
