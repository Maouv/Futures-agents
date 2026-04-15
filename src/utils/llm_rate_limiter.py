"""
llm_rate_limiter.py — Provider-agnostic rate limiter untuk LLM API calls.
Menggunakan threading.Semaphore untuk max concurrent in-flight requests
+ sliding window untuk RPM limit.
Thread-safe untuk digunakan dari APScheduler background thread.
"""
import threading
import time
from collections import deque

from src.utils.logger import logger


class LLMRateLimiter:
    """
    Rate limiter untuk LLM API calls.
    - Semaphore: mengontrol max concurrent in-flight requests
    - Sliding window: mengontrol requests per minute (RPM)
    - Thread-safe untuk digunakan dari APScheduler background thread

    Usage:
        limiter = LLMRateLimiter(max_concurrent=2, rpm=30)
        limiter.acquire()
        try:
            response = client.chat.completions.create(...)
        finally:
            limiter.release()

        # Atau sebagai context manager:
        with limiter:
            response = client.chat.completions.create(...)
    """

    def __init__(self, max_concurrent: int, rpm: int) -> None:
        self.max_concurrent = max_concurrent
        self.rpm = rpm
        self._semaphore = threading.Semaphore(max_concurrent)
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

    def acquire(self) -> None:
        """Block sampai slot tersedia (semaphore + RPM check)."""
        # Step 1: Acquire semaphore (max concurrent in-flight)
        self._semaphore.acquire()

        # Step 2: Wait if RPM limit reached (sliding window)
        with self._condition:
            while True:
                now = time.monotonic()

                # Buang timestamps di luar window (60 detik)
                while self._timestamps and self._timestamps[0] <= now - 60.0:
                    self._timestamps.popleft()
                    self._condition.notify()

                if len(self._timestamps) < self.rpm:
                    # Slot RPM tersedia — record timestamp
                    self._timestamps.append(now)
                    return

                # Hitung waktu tunggu sampai timestamp tertua expired
                sleep_time = self._timestamps[0] + 60.0 - now
                if sleep_time > 0:
                    logger.warning(f"LLM RPM limit reached. Waiting {sleep_time:.2f}s")
                    self._condition.wait(timeout=sleep_time)

    def release(self) -> None:
        """Release slot setelah response diterima."""
        self._semaphore.release()

    def __enter__(self) -> None:
        self.acquire()
        return None

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
        return None


# ── Singleton instances per provider ──────────────────────────────────────
# Import settings di sini untuk menghindari circular import saat module load.
# Settings sudah initialized saat import terjadi di runtime.

def _get_cerebras_limiter() -> LLMRateLimiter:
    """Lazy singleton untuk Cerebras rate limiter."""
    from src.config.settings import settings
    return LLMRateLimiter(
        max_concurrent=settings.LLM_CEREBRAS_MAX_CONCURRENT,
        rpm=settings.LLM_CEREBRAS_RPM,
    )


def _get_groq_limiter() -> LLMRateLimiter:
    """Lazy singleton untuk Groq rate limiter."""
    from src.config.settings import settings
    return LLMRateLimiter(
        max_concurrent=settings.LLM_GROQ_MAX_CONCURRENT,
        rpm=settings.LLM_GROQ_RPM,
    )


class _LazyLimiter:
    """Lazy proxy — limiter hanya dibuat saat pertama kali diakses."""
    def __init__(self, factory):
        self._factory = factory
        self._instance: LLMRateLimiter | None = None
        self._lock = threading.Lock()

    @property
    def limiter(self) -> LLMRateLimiter:
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = self._factory()
        return self._instance

    def acquire(self) -> None:
        self.limiter.acquire()

    def release(self) -> None:
        self.limiter.release()

    def __enter__(self) -> None:
        self.acquire()
        return None

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
        return None


# Singleton proxies — import ini di agent files
cerebras_limiter = _LazyLimiter(_get_cerebras_limiter)
groq_limiter = _LazyLimiter(_get_groq_limiter)
