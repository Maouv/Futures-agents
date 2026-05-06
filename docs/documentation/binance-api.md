# Binance API

Read this when: working in `src/utils/exchange.py`, `src/agents/math/execution_agent.py`, `order_monitor.py`, or debugging live order issues.

## Exchange Singleton

Never instantiate `ccxt.binanceusdm()` directly — always use the singleton:
```python
# Correct
from src.utils.exchange import get_exchange
exchange = get_exchange()

# Wrong
exchange = ccxt.binanceusdm({"apiKey": ..., "secret": ...})
```

After any network error, call `reset_exchange()` before retrying — singleton stores stale state.

## Algo Order Flow

Binance Futures uses a separate Algo Order API for SL/TP — not standard `cancel_order()`.

```
PLACE:  place_algo_order(symbol, side, order_type, trigger_price, quantity, reduce_only)
        → POST /fapi/v1/algoOrder
        → returns dict with key 'algoId' — NOT 'orderId'

CANCEL: cancel_algo_order(algoId, symbol)
        → DELETE /fapi/v1/algoOrder
        → NOT exchange.cancel_order() — wrong endpoint, will fail silently
```

```python
# Correct
result = place_algo_order(symbol="BTCUSDT", side="sell",
                          order_type="STOP_MARKET", trigger_price=65000.0,
                          quantity=0.01, reduce_only=True)
sl_order_id = str(result["algoId"])  # NOT result["orderId"]

# Cancel
cancel_algo_order(algoId=sl_order_id, symbol="BTCUSDT")
```

## Order Status

Binance can return `closed` besides `filled` — both mean executed:
```python
if order_status in ("filled", "closed"):
    # handle fill
```

## Known Error Codes

| Code | Cause | Fix |
|---|---|---|
| -4137 | Stop price already triggered (buy price above trigger) | Skip order, log warning |
| -4120 | Using `/fapi/v1/order` for algo order | Use `place_algo_order()` instead |

## ccxt Version Lock

ccxt is pinned at `4.2.86` — never upgrade. Newer versions block testnet futures API.
Algo API is called manually via `requests`, not via ccxt — ccxt does not support `/fapi/v1/algoOrder`.

## Live vs Testnet

Switching is controlled by `config.json → system.use_testnet`.
After changing `EXECUTION_MODE` or testnet flag, always restart the bot — exchange singleton keeps stale config.
`confirm_mainnet` must be `true` in `config.json` before going live on mainnet, or bot will refuse to execute.

## Reconciliation

`exchange.fetch_positions()` returns unified symbol `'BTC/USDT:USDT'`.
Get raw symbol from `pos['info']['symbol']` (`'BTCUSDT'`) — NOT from `pos['symbol']`.

