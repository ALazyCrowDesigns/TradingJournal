"""Database operations for backfill data persistence."""

from typing import Any

from sqlalchemy import (
    Column,
    Date,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    text,
)
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .config import BackfillConfig
from .models import BackfillRow

# Define the backfill table schema
metadata = MetaData()

backfill_table = Table(
    "backfill_data",
    metadata,
    Column("symbol", String(16), nullable=False, primary_key=True),
    Column("trade_date", Date, nullable=False, primary_key=True),
    Column("pre_high", Float, nullable=True),
    Column("pre_low", Float, nullable=True),
    Column("open_price", Float, nullable=True),
    Column("hod", Float, nullable=True),
    Column("lod", Float, nullable=True),
    Column("ah_high", Float, nullable=True),
    Column("ah_low", Float, nullable=True),
    Column("day_volume", Integer, nullable=True),
)

# SQL for manual table creation (if needed)
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS backfill_data (
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    pre_high REAL,
    pre_low REAL,
    open_price REAL,
    hod REAL,
    lod REAL,
    ah_high REAL,
    ah_low REAL,
    day_volume INTEGER,
    PRIMARY KEY (symbol, trade_date)
);
"""


class BackfillDatabase:
    """Database operations for backfill data."""
    
    def __init__(self, config: BackfillConfig) -> None:
        self.config = config
        self.engine = self._create_engine()
        
    def _create_engine(self) -> Engine:
        """Create SQLAlchemy engine with optimized SQLite settings."""
        engine = create_engine(
            self.config.db_url,
            echo=False,  # Set to True for SQL debugging
            pool_pre_ping=True,
        )
        
        # Configure SQLite for optimal performance
        with engine.connect() as conn:
            # Enable WAL mode for better concurrency
            conn.execute(text("PRAGMA journal_mode=WAL"))
            # Faster synchronous mode (still safe)
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            # Store temporary tables in memory
            conn.execute(text("PRAGMA temp_store=MEMORY"))
            # Increase cache size (negative value = KB)
            conn.execute(text("PRAGMA cache_size=-64000"))  # 64MB
            conn.commit()
        
        return engine
    
    def create_tables(self) -> None:
        """Create the backfill table if it doesn't exist."""
        metadata.create_all(self.engine)
    
    def upsert_batch(self, rows: list[BackfillRow]) -> int:
        """Insert or update backfill rows in batch.
        
        Uses SQLite's INSERT OR REPLACE (UPSERT) functionality to handle
        conflicts on the (symbol, trade_date) primary key.
        
        Args:
            rows: List of BackfillRow objects to upsert
            
        Returns:
            Number of rows affected
        """
        if not rows:
            return 0
        
        # Convert rows to dictionaries
        data = [row.to_dict() for row in rows]
        
        with Session(self.engine) as session:
            # Use SQLite's INSERT OR REPLACE for UPSERT behavior
            stmt = insert(backfill_table)
            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "trade_date"],
                set_={
                    "pre_high": stmt.excluded.pre_high,
                    "pre_low": stmt.excluded.pre_low,
                    "open_price": stmt.excluded.open_price,
                    "hod": stmt.excluded.hod,
                    "lod": stmt.excluded.lod,
                    "ah_high": stmt.excluded.ah_high,
                    "ah_low": stmt.excluded.ah_low,
                    "day_volume": stmt.excluded.day_volume,
                }
            )
            
            result = session.execute(upsert_stmt, data)
            session.commit()
            
            return result.rowcount or len(data)
    
    def batch_upsert_chunked(self, rows: list[BackfillRow]) -> int:
        """Upsert rows in chunks for large datasets.
        
        Args:
            rows: List of BackfillRow objects to upsert
            
        Returns:
            Total number of rows affected
        """
        total_affected = 0
        batch_size = self.config.batch_size
        
        for i in range(0, len(rows), batch_size):
            chunk = rows[i:i + batch_size]
            affected = self.upsert_batch(chunk)
            total_affected += affected
        
        return total_affected
    
    def get_existing_data(self, symbol_dates: list[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
        """Get existing backfill data for symbol-date pairs.
        
        Args:
            symbol_dates: List of (symbol, trade_date_iso) tuples
            
        Returns:
            Dictionary mapping (symbol, trade_date) to existing row data
        """
        if not symbol_dates:
            return {}
        
        with Session(self.engine) as session:
            # Build WHERE clause for multiple symbol-date pairs
            conditions = []
            for symbol, trade_date in symbol_dates:
                conditions.append(f"(symbol = '{symbol}' AND trade_date = '{trade_date}')")
            
            where_clause = " OR ".join(conditions)
            query = f"SELECT * FROM backfill_data WHERE {where_clause}"
            
            result = session.execute(text(query))
            
            existing = {}
            for row in result:
                key = (row.symbol, row.trade_date)
                existing[key] = dict(row._mapping)
            
            return existing
    
    def count_records(self) -> int:
        """Count total number of backfill records."""
        with Session(self.engine) as session:
            result = session.execute(text("SELECT COUNT(*) FROM backfill_data"))
            return result.scalar() or 0
    
    def get_symbols_count(self) -> int:
        """Count distinct symbols in backfill data."""
        with Session(self.engine) as session:
            result = session.execute(text("SELECT COUNT(DISTINCT symbol) FROM backfill_data"))
            return result.scalar() or 0
    
    def cleanup_old_data(self, days_to_keep: int = 365) -> int:
        """Remove backfill data older than specified days.
        
        Args:
            days_to_keep: Number of days of data to retain
            
        Returns:
            Number of rows deleted
        """
        with Session(self.engine) as session:
            query = text("""
                DELETE FROM backfill_data 
                WHERE trade_date < date('now', '-{} days')
            """.format(days_to_keep))
            
            result = session.execute(query)
            session.commit()
            
            return result.rowcount or 0
