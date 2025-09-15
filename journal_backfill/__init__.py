"""
Async backfill service for trading journal data from Polygon.io

This package provides high-throughput async backfilling of:
- Premarket high/low from 30-minute aggregates
- After-hours high/low from 30-minute aggregates  
- Daily OHLC and volume data

Features:
- Async HTTP with connection reuse and HTTP/2
- Configurable concurrency control
- Robust retry logic with exponential backoff
- Batch database operations with UPSERT
- Timezone-aware session windows (ET to UTC)
"""

__version__ = "1.0.0"
