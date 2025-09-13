from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator


class SymbolIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16)
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    shares_float: float | None = None
    float_asof: date | None = None

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.strip().upper()


class TradeIn(BaseModel):
    profile_id: int = 1
    trade_date: date
    symbol: str
    side: str
    size: int | None = None
    entry: float | None = None
    exit: float | None = None
    pnl: float | None = None
    return_pct: float | None = None
    notes: str | None = None

    prev_close: float | None = None
    o: float | None = None
    h: float | None = None
    low: float | None = None
    c: float | None = None
    v: int | None = None

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("side")
    @classmethod
    def clean_side(cls, v: str) -> str:
        return (v or "").strip().upper()[:5]


class DailyPriceIn(BaseModel):
    symbol: str
    date: date
    o: float
    h: float
    low: float
    c: float
    v: int

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.strip().upper()
