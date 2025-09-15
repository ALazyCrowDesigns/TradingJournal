"""Data models for backfill operations."""

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class PolygonBar:
    """Represents a single bar from Polygon.io aggregates API.
    
    Attributes:
        t: Timestamp in milliseconds (UTC)
        o: Open price
        h: High price
        l: Low price
        c: Close price
        v: Volume (shares)
    """
    t: int  # timestamp in ms
    o: float  # open
    h: float  # high
    l: float  # low
    c: float  # close
    v: int  # volume
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolygonBar":
        """Create PolygonBar from API response dictionary."""
        return cls(
            t=int(data["t"]),
            o=float(data["o"]),
            h=float(data["h"]),
            l=float(data["l"]),
            c=float(data["c"]),
            v=int(data["v"]),
        )


@dataclass
class SessionMetrics:
    """Metrics computed for a specific trading session."""
    high: float | None = None
    low: float | None = None
    
    def update_from_bar(self, bar: PolygonBar) -> None:
        """Update session metrics with a new bar."""
        if self.high is None or bar.h > self.high:
            self.high = bar.h
        if self.low is None or bar.l < self.low:
            self.low = bar.l


@dataclass
class BackfillRow:
    """Complete backfill data for a (symbol, trade_date) pair.
    
    This represents all the data we want to persist to the database
    for a single symbol on a single trading day.
    """
    symbol: str
    trade_date: date
    
    # Premarket metrics (04:00-09:30 ET)
    pre_high: float | None = None
    pre_low: float | None = None
    
    # Daily OHLC (authoritative from daily aggregate)
    open_price: float | None = None
    hod: float | None = None  # High of day
    lod: float | None = None  # Low of day
    
    # After-hours metrics (16:00-20:00 ET)
    ah_high: float | None = None
    ah_low: float | None = None
    
    # Volume (shares, from daily aggregate only)
    day_volume: int | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "symbol": self.symbol,
            "trade_date": self.trade_date,  # Keep as date object for SQLAlchemy
            "pre_high": self.pre_high,
            "pre_low": self.pre_low,
            "open_price": self.open_price,
            "hod": self.hod,
            "lod": self.lod,
            "ah_high": self.ah_high,
            "ah_low": self.ah_low,
            "day_volume": self.day_volume,
        }


@dataclass
class BackfillRequest:
    """Request for backfilling a specific symbol and date."""
    symbol: str
    trade_date: date
    
    def __str__(self) -> str:
        return f"{self.symbol}:{self.trade_date.isoformat()}"
