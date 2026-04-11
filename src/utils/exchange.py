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
            "apiKey": settings.BINANCE_API_KEY.get_secret_value() if settings.BINANCE_API_KEY else "",
            "secret": settings.BINANCE_API_SECRET.get_secret_value() if settings.BINANCE_API_SECRET else "",
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


def place_algo_order(
    symbol: str,
    side: str,
    order_type: str,
    trigger_price: float,
    quantity: float,
    reduce_only: bool = True,
) -> dict:
    """
    Place conditional order (SL/TP) via Binance Algo Order API.

    Sejak Des 2025, Binance memigrasikan STOP_MARKET, TAKE_PROFIT_MARKET, dll
    dari endpoint lama (/fapi/v1/order) ke Algo Order API (/fapi/v1/algoOrder).
    ccxt belum support endpoint ini secara native, jadi kita panggil langsung.

    Args:
        symbol: Trading pair, e.g. 'BTCUSDT'
        side: 'BUY' atau 'SELL'
        order_type: 'STOP_MARKET' atau 'TAKE_PROFIT_MARKET'
        trigger_price: Harga trigger (sebelumnya 'stopPrice')
        quantity: Jumlah kontrak
        reduce_only: True untuk reduce-only (SL/TP selalu reduce)

    Returns:
        dict response dari Binance API (berisi 'algoId')

    Raises:
        ccxt.ExchangeError: Jika order gagal
    """
    import time
    import hashlib
    import hmac
    import urllib.parse

    exchange = get_exchange()

    params = {
        'symbol': symbol,
        'side': side.upper(),
        'algoType': 'CONDITIONAL',
        'type': order_type,
        'triggerPrice': exchange.price_to_precision(symbol, trigger_price),
        'quantity': exchange.amount_to_precision(symbol, quantity),
        'workingType': 'MARK_PRICE',
        'reduceOnly': 'true' if reduce_only else 'false',
        'timestamp': int(time.time() * 1000),
    }

    # Build query string + HMAC signature (Binance auth)
    query = urllib.parse.urlencode(params)
    signature = hmac.new(
        exchange.secret.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()
    query += f'&signature={signature}'

    # Determine base URL (testnet vs mainnet)
    if settings.USE_TESTNET:
        base_url = 'https://testnet.binancefuture.com'
    else:
        base_url = 'https://fapi.binance.com'

    url = f'{base_url}/fapi/v1/algoOrder?{query}'

    import requests as http_requests
    headers = {'X-MBX-APIKEY': exchange.apiKey}
    response = http_requests.post(url, headers=headers, timeout=10)

    result = response.json()
    if response.status_code != 200 or 'code' in result:
        raise ccxt.ExchangeError(
            f"Algo order failed: {result.get('msg', str(result))}"
        )

    logger.debug(f"Algo order placed: {order_type} {side} {symbol} trigger={trigger_price}")
    return result


def cancel_algo_order(
    algo_order_id: str,
    symbol: str,
) -> dict:
    """
    Cancel conditional order via Binance Algo Order API.

    Args:
        algo_order_id: ID dari algo order yang akan di-cancel
        symbol: Trading pair, e.g. 'BTCUSDT'

    Returns:
        dict response dari Binance API
    """
    import time
    import hashlib
    import hmac
    import urllib.parse

    exchange = get_exchange()

    params = {
        'algoId': algo_order_id,
        'symbol': symbol,
        'timestamp': int(time.time() * 1000),
    }

    query = urllib.parse.urlencode(params)
    signature = hmac.new(
        exchange.secret.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()
    query += f'&signature={signature}'

    if settings.USE_TESTNET:
        base_url = 'https://testnet.binancefuture.com'
    else:
        base_url = 'https://fapi.binance.com'

    url = f'{base_url}/fapi/v1/algoOrder?{query}'

    import requests as http_requests
    headers = {'X-MBX-APIKEY': exchange.apiKey}
    response = http_requests.delete(url, headers=headers, timeout=10)

    result = response.json()
    if response.status_code != 200 or ('code' in result and result.get('code') != 200):
        raise ccxt.ExchangeError(
            f"Cancel algo order failed: {result.get('msg', str(result))}"
        )

    logger.debug(f"Algo order cancelled: {algo_order_id}")
    return result


def get_ws_base_url() -> str:
    """
    Return WebSocket base URL berdasarkan settings.USE_TESTNET.
    Digunakan oleh ws_user_stream.py untuk koneksi User Data Stream.
    """
    if settings.USE_TESTNET:
        return str(settings.BINANCE_TESTNET_WS_URL)
    return str(settings.BINANCE_WS_URL)
