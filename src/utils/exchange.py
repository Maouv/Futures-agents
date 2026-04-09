"""
exchange.py — Centralized ccxt exchange factory for Binance Futures.

Single source of truth untuk pembuatan exchange instance.
Semua modul (ohlcv_fetcher, execution_agent, ws_user_stream) WAJIB
menggunakan get_exchange() dari sini. DILARANG membuat ccxt.binanceusdm() langsung.

Features:
- Singleton pattern: satu instance dipakai semua modul
- Testnet/mainnet switching dari settings
- recvWindow=60000ms (Binance max) + adjustForTimeDifference=True
- reset_exchange() untuk force recreate saat connection error
"""
import threading
from typing import Optional

import ccxt

from src.config.settings import settings
from src.utils.logger import logger


# ── Singleton State ─────────────────────────────────────────────────────────
_exchange_instance: Optional[ccxt.binanceusdm] = None
_exchange_lock = threading.Lock()


def _create_exchange() -> ccxt.binanceusdm:
    """
    Factory function untuk ccxt exchange instance.
    Otomatis switch ke testnet jika settings.USE_TESTNET = True.

    recvWindow set to 60000ms (max allowed by Binance API).
    adjustForTimeDifference=True enables ccxt to auto-sync with Binance server time.
    """
    base_config = {
        "options": {
            "defaultType": "future",
        },
        "recvWindow": 60000,
        "adjustForTimeDifference": True,
    }

    if settings.USE_TESTNET:
        config = {
            **base_config,
            "apiKey": settings.BINANCE_TESTNET_KEY.get_secret_value(),
            "secret": settings.BINANCE_TESTNET_SECRET.get_secret_value(),
            "urls": {
                "api": {
                    "public": str(settings.BINANCE_TESTNET_URL),
                    "private": str(settings.BINANCE_TESTNET_URL),
                }
            },
            "options": {
                **base_config.get("options", {}),
                "fetchCurrencies": False,
            },
        }
        exchange = ccxt.binanceusdm(config)
        exchange.set_sandbox_mode(True)
        logger.debug("Exchange: Binance Futures TESTNET")
    else:
        config = {
            **base_config,
            "apiKey": settings.BINANCE_API_KEY.get_secret_value(),
            "secret": settings.BINANCE_API_SECRET.get_secret_value(),
        }
        exchange = ccxt.binanceusdm(config)
        logger.debug("Exchange: Binance Futures PRODUCTION")

    return exchange


def get_exchange() -> ccxt.binanceusdm:
    """
    Get or create singleton ccxt exchange instance.
    Thread-safe menggunakan Lock.

    Returns:
        ccxt.binanceusdm instance yang sudah dikonfigurasi.
    """
    global _exchange_instance

    if _exchange_instance is not None:
        return _exchange_instance

    with _exchange_lock:
        # Double-check setelah acquire lock
        if _exchange_instance is None:
            _exchange_instance = _create_exchange()

    return _exchange_instance


def reset_exchange() -> None:
    """
    Force recreate exchange instance pada pemanggilan get_exchange() berikutnya.
    Panggil saat encounter ExchangeNotAvailable atau NetworkError untuk clear stale state.
    """
    global _exchange_instance

    with _exchange_lock:
        old = _exchange_instance
        _exchange_instance = None

    if old is not None:
        try:
            old.close()
        except Exception:
            pass

    logger.info("Exchange instance reset. New instance will be created on next get_exchange().")


def get_ws_base_url() -> str:
    """
    Return WebSocket base URL berdasarkan settings.USE_TESTNET.
    Digunakan oleh ws_user_stream.py untuk koneksi User Data Stream.
    """
    if settings.USE_TESTNET:
        return str(settings.BINANCE_TESTNET_WS_URL)
    return str(settings.BINANCE_WS_URL)
