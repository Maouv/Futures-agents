"""
rate_limiter.py — Sliding window rate limiter untuk semua HTTP calls ke Binance.
MAX 800 request/menit sesuai PRD FR-1.1.
Thread-safe menggunakan threading.Lock.
"""
import threading
import time
from collections import deque
from typing import Callable, TypeVar, Any

from src.utils.logger import logger

T = TypeVar("T")


class RateLimiter:
    """
    Sliding window rate limiter.

    Usage:
        limiter = RateLimiter(max_calls=800, period=60)

        @limiter.limit
        def fetch_data():
            ...
    """

    def __init__(self, max_calls: int = 800, period: float = 60.0) -> None:
        self.max_calls = max_calls
        self.period = period
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def wait_if_needed(self) -> None:
        """Block sampai slot tersedia dalam window."""
        with self._lock:
            now = time.monotonic()

            # Buang timestamps di luar window
            while self._calls and self._calls[0] <= now - self.period:
                self._calls.popleft()

            if len(self._calls) >= self.max_calls:
                # Hitung waktu tunggu
                sleep_time = self._calls[0] + self.period - now
                if sleep_time > 0:
                    logger.warning(f"Rate limit reached. Waiting {sleep_time:.2f}s")
                    # Release lock sebelum sleep agar thread lain bisa cek
                    self._lock.release()
                    time.sleep(sleep_time)
                    self._lock.acquire()
                    # Re-clean setelah sleep
                    now = time.monotonic()
                    while self._calls and self._calls[0] <= now - self.period:
                        self._calls.popleft()

            self._calls.append(time.monotonic())

    def limit(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator untuk membungkus fungsi dengan rate limiting."""
        def wrapper(*args: Any, **kwargs: Any) -> T:
            self.wait_if_needed()
            return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        return wrapper


# Singleton instance — import ini di ohlcv_fetcher
binance_limiter = RateLimiter(max_calls=800, period=60.0)
