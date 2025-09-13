"""
Caching service for performance optimization.
Uses in-memory caching with TTL support.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from threading import RLock
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


@dataclass
class CacheEntry:
    value: Any
    expiry_time: float


class TTLCache:
    """Thread-safe TTL cache implementation"""

    def __init__(self, max_size: int = 1000, default_ttl: int = 300) -> None:
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = RLock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._cache:
                return None

            entry = self._cache[key]
            if time.time() > entry.expiry_time:
                del self._cache[key]
                return None

            # Move to end (LRU)
            self._cache.move_to_end(key)
            return entry.value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        with self._lock:
            ttl = ttl or self._default_ttl
            expiry_time = time.time() + ttl

            # Remove oldest if at capacity
            if len(self._cache) >= self._max_size and key not in self._cache:
                self._cache.popitem(last=False)

            self._cache[key] = CacheEntry(value, expiry_time)
            self._cache.move_to_end(key)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        """Invalidate all keys starting with prefix"""
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for key in keys_to_remove:
                del self._cache[key]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"size": len(self._cache), "max_size": self._max_size}


# Global cache instance
_cache = TTLCache()


def cached(
    ttl: int = 300, key_prefix: str = "", invalidate_on: list[str] | None = None
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator for caching function results.

    Args:
        ttl: Time to live in seconds
        key_prefix: Prefix for cache keys
        invalidate_on: List of method names that invalidate this cache
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Build cache key
            cache_key = f"{key_prefix}:{func.__name__}:{args}:{kwargs}"

            # Try to get from cache
            cached_value = _cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            # Compute and cache
            result = func(*args, **kwargs)
            _cache.set(cache_key, result, ttl)
            return result

        # Add invalidation helper
        wrapper.invalidate = lambda: _cache.invalidate_prefix(f"{key_prefix}:{func.__name__}")
        return wrapper

    return decorator


def invalidate_cache(prefix: str | None = None) -> None:
    """Invalidate cache entries"""
    if prefix:
        _cache.invalidate_prefix(prefix)
    else:
        _cache.clear()


# Performance monitoring
def get_cache_stats() -> dict[str, int]:
    """Get cache statistics"""
    return _cache.stats()
