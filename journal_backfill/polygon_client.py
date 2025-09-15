"""Async HTTP client for Polygon.io API with retry logic."""

import asyncio
from datetime import date
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .config import BackfillConfig
from .models import PolygonBar
from .time_windows import get_extended_hours_window_ms


class PolygonAPIError(Exception):
    """Custom exception for Polygon API errors."""
    
    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class PolygonClient:
    """Async HTTP client for Polygon.io API with connection reuse and retry logic."""
    
    def __init__(self, config: BackfillConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None
        
    async def __aenter__(self) -> "PolygonClient":
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=self.config.request_timeout,
            headers={
                "Accept-Encoding": "gzip",
                "User-Agent": "trading-journal-backfill/1.0",
            },
            limits=httpx.Limits(
                max_connections=self.config.max_concurrent_requests * 2,
                max_keepalive_connections=self.config.max_concurrent_requests,
            ),
        )
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=0.4, max=3.0),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError, PolygonAPIError)),
    )
    async def _request_with_retry(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Make HTTP request with automatic retry on failure."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")
        
        try:
            response = await self._client.get(url, params=params)
            
            # Handle rate limiting and server errors
            if response.status_code == 429:
                # Add small jitter for rate limiting
                await asyncio.sleep(0.1 + (asyncio.get_event_loop().time() % 0.1))
                raise PolygonAPIError(f"Rate limited: {response.status_code}", response.status_code)
            
            if response.status_code >= 500:
                raise PolygonAPIError(f"Server error: {response.status_code}", response.status_code)
            
            response.raise_for_status()
            
            data = response.json()
            
            # Check for API-level errors
            if data.get("status") == "ERROR":
                error_msg = data.get("error", "Unknown API error")
                raise PolygonAPIError(f"API error: {error_msg}")
            
            return data
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 500, 502, 503, 504):
                raise PolygonAPIError(f"Retryable HTTP error: {e.response.status_code}", e.response.status_code)
            raise PolygonAPIError(f"HTTP error: {e.response.status_code}", e.response.status_code)
        
        except httpx.TimeoutException as e:
            raise PolygonAPIError(f"Request timeout: {e}")
    
    async def get_30min_aggregates(self, symbol: str, trade_date: date) -> list[PolygonBar]:
        """Fetch 30-minute aggregates for extended hours (04:00-20:00 ET).
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            trade_date: Trading date
            
        Returns:
            List of 30-minute bars for the extended hours window
            
        Raises:
            PolygonAPIError: If API request fails
        """
        from_ms, to_ms = get_extended_hours_window_ms(trade_date)
        
        url = f"{self.config.base_url}/aggs/ticker/{symbol}/range/30/minute/{from_ms}/{to_ms}"
        params = {
            "adjusted": str(self.config.adjusted).lower(),
            "sort": "asc",
            "limit": 1000,
            "apikey": self.config.polygon_api_key,
        }
        
        data = await self._request_with_retry(url, params)
        
        results = data.get("results", []) or []
        return [PolygonBar.from_dict(bar_data) for bar_data in results]
    
    async def get_daily_aggregate(self, symbol: str, trade_date: date) -> PolygonBar | None:
        """Fetch daily aggregate for a single trading day.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            trade_date: Trading date
            
        Returns:
            Daily bar or None if no data available
            
        Raises:
            PolygonAPIError: If API request fails
        """
        date_str = trade_date.isoformat()
        url = f"{self.config.base_url}/aggs/ticker/{symbol}/range/1/day/{date_str}/{date_str}"
        params = {
            "adjusted": str(self.config.adjusted).lower(),
            "sort": "asc",
            "limit": 1,
            "apikey": self.config.polygon_api_key,
        }
        
        data = await self._request_with_retry(url, params)
        
        results = data.get("results", []) or []
        if not results:
            return None
        
        return PolygonBar.from_dict(results[0])
    
    async def fetch_symbol_data(self, symbol: str, trade_date: date) -> tuple[list[PolygonBar], PolygonBar | None]:
        """Fetch both 30-minute aggregates and daily aggregate for a symbol.
        
        This method makes both API calls concurrently for efficiency.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            trade_date: Trading date
            
        Returns:
            Tuple of (30min_bars, daily_bar)
            
        Raises:
            PolygonAPIError: If either API request fails
        """
        bars_task = self.get_30min_aggregates(symbol, trade_date)
        daily_task = self.get_daily_aggregate(symbol, trade_date)
        
        bars, daily = await asyncio.gather(bars_task, daily_task)
        return bars, daily
