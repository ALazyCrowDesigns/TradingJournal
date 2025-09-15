"""Configuration management for backfill service."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env file if present
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)


@dataclass(frozen=True)
class SessionWindows:
    """Trading session time windows in America/New_York timezone."""
    
    # Session windows as (hour, minute) tuples in ET
    PRE_START = (4, 0)      # 04:00 ET
    PRE_END = (9, 30)       # 09:30 ET (exclusive)
    REG_START = (9, 30)     # 09:30 ET
    REG_END = (16, 0)       # 16:00 ET (exclusive)
    AH_START = (16, 0)      # 16:00 ET
    AH_END = (20, 0)        # 20:00 ET (exclusive)


@dataclass(frozen=True)
class BackfillConfig:
    """Configuration for the backfill service."""
    
    # API Configuration
    polygon_api_key: str
    
    # Concurrency Configuration
    max_concurrent_requests: int = 12
    batch_size: int = 300
    
    # HTTP Configuration
    request_timeout: int = 30
    max_retries: int = 5
    retry_initial_wait: float = 0.4
    retry_max_wait: float = 3.0
    
    # Database Configuration
    db_url: str = "sqlite:///journal.sqlite3"
    
    # Polygon API Configuration
    base_url: str = "https://api.polygon.io/v2"
    adjusted: bool = False  # Use unadjusted prices to match trade-day prints
    
    # Session windows
    sessions: SessionWindows = SessionWindows()
    
    @classmethod
    def from_env(cls) -> "BackfillConfig":
        """Create configuration from environment variables."""
        api_key = os.getenv("POLYGON_API_KEY")
        if not api_key:
            raise ValueError(
                "POLYGON_API_KEY environment variable is required. "
                "Set it in your .env file or environment."
            )
        
        return cls(
            polygon_api_key=api_key,
            max_concurrent_requests=int(os.getenv("BACKFILL_CONCURRENCY", "12")),
            batch_size=int(os.getenv("BACKFILL_BATCH_SIZE", "300")),
            request_timeout=int(os.getenv("BACKFILL_TIMEOUT", "30")),
            db_url=os.getenv("BACKFILL_DB_URL", "sqlite:///journal.sqlite3"),
        )
