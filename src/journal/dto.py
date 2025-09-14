from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SymbolIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16)
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    float: Optional[float] = None
    float_asof: Optional[date] = None

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.strip().upper()


class TradeIn(BaseModel):
    profile_id: int = 1
    trade_date: date
    symbol: str
    side: str
    size: Optional[int] = None
    entry: Optional[float] = None
    exit: Optional[float] = None
    pnl: Optional[float] = None
    return_pct: Optional[float] = None
    notes: Optional[str] = None

    prev_close: Optional[float] = None

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


class ProfileIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=512)
    is_active: bool = True
    default_csv_format: Optional[str] = Field(None, max_length=32)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return v.strip()


class ProfileOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    default_csv_format: Optional[str] = None

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=512)
    is_active: Optional[bool] = None
    default_csv_format: Optional[str] = Field(None, max_length=32)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else None
