from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase): ...


class Symbol(Base):
    __tablename__ = "symbols"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    sector: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(64))
    float: Mapped[float | None] = mapped_column(Float)
    float_asof: Mapped[date | None] = mapped_column(Date)


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"), index=True)
    side: Mapped[str] = mapped_column(String(5))  # LONG/SHORT or B/S
    size: Mapped[int | None] = mapped_column(Integer)
    entry: Mapped[float | None] = mapped_column(Float)
    exit: Mapped[float | None] = mapped_column(Float)
    pnl: Mapped[float | None] = mapped_column(Float)
    return_pct: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(String(512))

    prev_close: Mapped[float | None] = mapped_column(Float)
    o: Mapped[float | None] = mapped_column(Float)
    h: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    c: Mapped[float | None] = mapped_column(Float)
    v: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("profile_id", "symbol", "trade_date", name="uq_trade_identity"),
        Index("ix_trade_profile_symbol_date", "profile_id", "symbol", "trade_date"),
    )


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    o: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    c: Mapped[float] = mapped_column(Float)
    v: Mapped[int] = mapped_column(Integer)

    __table_args__ = (Index("ix_dp_symbol_date", "symbol", "date"),)
