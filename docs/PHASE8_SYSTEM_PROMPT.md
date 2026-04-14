# 🤖 PHASE 8 MASTER PROMPT — Go Live & User Data WebSocket
# Untuk: Claude Code
# Prasyarat: Phase 0–7 (kode RL) selesai. Paper trade standalone TIDAK diperlukan.

---

## BRIEFING PHASE 8

Mengubah bot dari paper mode ke live trading di Binance Futures (USD-M).
Phase ini sekaligus menggantikan paper trade standalone — data closed trades dari Testnet
akan dipakai sebagai training data RL di Phase 7.

**WAJIB BACA sebelum mulai:**
- `CLAUDE.md` — terutama section KOREKSI ARSITEKTUR dan STATUS ROADMAP
- `IMPLEMENTATION_PLAN.md` Phase 8
- `src/agents/math/execution_agent.py` — guard clause yang harus diupdate
- `src/agents/math/sltp_manager.py` — perlu guard untuk live mode
- `src/main.py` — struktur `TradingBot` class yang sudah ada

---

## 🛑 ATURAN KRITIS PHASE 8 (TIDAK BOLEH DILANGGAR)

1. **DILARANG OCO** — Binance Futures tidak support OCO. Gunakan 2 order terpisah: `stop_market` + `take_profit_market`.
2. **WAJIB set leverage dan margin mode** sebelum setiap entry order.
3. **User Data WebSocket** — hanya dengarkan `ORDER_TRADE_UPDATE`, bukan market data.
4. **Testnet dulu** — `USE_TESTNET=True` minimal 48 jam sebelum switch ke Mainnet.
5. **DILARANG hardcode URL** — semua URL baca dari `settings`. ccxt instance pakai factory function.
6. **Baca `settings.EXECUTION_MODE`**, bukan `os.getenv("EXECUTION_MODE")` langsung.
7. **SLTPManager di-bypass saat live** — SL/TP sudah di server Binance, jangan double-check manual.

---

## 📦 TASK LIST PHASE 8

### Task 8.1 — Update `.env` untuk Live

```env
# Mode live, testnet dulu:
EXECUTION_MODE=live
USE_TESTNET=True

# API key Testnet (dari testnet.binancefuture.com):
BINANCE_TESTNET_KEY=your_testnet_key
BINANCE_TESTNET_SECRET=your_testnet_secret

# Soft launch — mulai konservatif:
FUTURES_DEFAULT_LEVERAGE=2
RISK_PER_TRADE_USD=5
```

---

### Task 8.2 — Update `src/agents/math/execution_agent.py`

Codebase sudah punya guard clause `if os.getenv("EXECUTION_MODE") == "live"` yang return SKIP.
Ganti bagian itu dengan implementasi live execution.

**Signature yang sudah ada (JANGAN diubah):**
```python
def run(
    self,
    symbol: str,
    risk_result: RiskResult,
    reversal_result: ReversalResult,
    trend_result: TrendResult,
    confirmation_confirmed: bool
) -> ExecutionResult:
```

**Implementasi yang diperlukan:**

```python
def run(self, symbol, risk_result, reversal_result, trend_result, confirmation_confirmed):
    
    if settings.EXECUTION_MODE == "live":
        # Validasi tetap dijalankan di live mode
        skip_reason = self._validate_signal(reversal_result, trend_result, confirmation_confirmed)
        if skip_reason:
            return ExecutionResult(action="SKIP", reason=skip_reason)
        return self._execute_live(symbol, risk_result, reversal_result.signal)
    else:
        return self._execute_paper(symbol, risk_result, reversal_result, trend_result, confirmation_confirmed)


def _validate_signal(self, reversal_result, trend_result, confirmation_confirmed):
    """
    Validasi signal sebelum eksekusi. Return reason string jika harus skip, None jika valid.
    Dipakai oleh paper dan live mode.
    """
    if reversal_result.signal == "LONG" and trend_result.bias != 1:
        return f"Trend tidak searah (H4={trend_result.bias_label}, signal=LONG)"
    if reversal_result.signal == "SHORT" and trend_result.bias != -1:
        return f"Trend tidak searah (H4={trend_result.bias_label}, signal=SHORT)"
    if reversal_result.confidence < 60:
        return f"Confidence terlalu rendah ({reversal_result.confidence}%)"
    if not confirmation_confirmed:
        return "Tidak ada konfirmasi di timeframe 15m"
    if reversal_result.signal not in ["LONG", "SHORT"]:
        return f"Signal tidak valid: {reversal_result.signal}"
    return None


def _execute_live(self, symbol: str, risk_result: RiskResult, signal: str) -> ExecutionResult:
    """
    Live execution via Binance Futures.
    Entry Order + 2x Stop/TP Market Order terpisah. DILARANG OCO.
    """
    exchange = self._create_exchange()
    side       = 'buy'  if signal == 'LONG'  else 'sell'
    close_side = 'sell' if signal == 'LONG'  else 'buy'

    try:
        # 1. Set leverage dan margin mode SEBELUM entry
        exchange.set_leverage(settings.FUTURES_DEFAULT_LEVERAGE, symbol)
        exchange.set_margin_mode('isolated', symbol)

        # 2. Entry Order (Market)
        entry_order = exchange.create_order(
            symbol=symbol,
            type='market',
            side=side,
            amount=risk_result.position_size,
        )
        self._log(f"✅ LIVE Entry: {entry_order['id']} | {symbol} {signal} @ ~{risk_result.entry_price:.2f}")

        # 3. Stop Loss (TERPISAH dari TP — DILARANG OCO)
        sl_order = exchange.create_order(
            symbol=symbol,
            type='stop_market',
            side=close_side,
            amount=risk_result.position_size,
            params={
                'stopPrice': risk_result.sl_price,
                'closePosition': True,
            }
        )
        self._log(f"✅ SL Order: {sl_order['id']} @ {risk_result.sl_price:.2f}")

        # 4. Take Profit (TERPISAH dari SL)
        tp_order = exchange.create_order(
            symbol=symbol,
            type='take_profit_market',
            side=close_side,
            amount=risk_result.position_size,
            params={
                'stopPrice': risk_result.tp_price,
                'closePosition': True,
            }
        )
        self._log(f"✅ TP Order: {tp_order['id']} @ {risk_result.tp_price:.2f}")

        # 5. Simpan ke DB dengan status OPEN — WS yang akan update ke CLOSED
        with get_session() as db:
            trade = PaperTrade(
                pair=symbol,
                side=signal,
                entry_price=risk_result.entry_price,
                sl_price=risk_result.sl_price,
                tp_price=risk_result.tp_price,
                size=risk_result.position_size,
                leverage=risk_result.leverage,
                status='OPEN',
                entry_timestamp=datetime.now(timezone.utc),
            )
            db.add(trade)
            db.flush()
            trade_id = trade.id

        return ExecutionResult(action='OPEN', reason='Live trade opened', trade_id=trade_id)

    except ccxt.NetworkError as e:
        self._log_error(f"Network error saat live execution: {e}")
        return ExecutionResult(action='SKIP', reason=f'Network error: {e}')
    except ccxt.ExchangeError as e:
        self._log_error(f"Exchange error saat live execution: {e}")
        return ExecutionResult(action='SKIP', reason=f'Exchange error: {e}')


def _create_exchange(self) -> ccxt.binanceusdm:
    """Factory — otomatis switch testnet/mainnet dari settings."""
    if settings.USE_TESTNET:
        return ccxt.binanceusdm({
            "apiKey": settings.BINANCE_TESTNET_KEY.get_secret_value(),
            "secret": settings.BINANCE_TESTNET_SECRET.get_secret_value(),
            "options": {"defaultType": "future"},
            "urls": {"api": {
                "public":  str(settings.BINANCE_TESTNET_URL),
                "private": str(settings.BINANCE_TESTNET_URL),
            }},
        })
    return ccxt.binanceusdm({
        "apiKey": settings.BINANCE_API_KEY.get_secret_value(),
        "secret": settings.BINANCE_API_SECRET.get_secret_value(),
        "options": {"defaultType": "future"},
    })
```

> **Catatan:** Import yang perlu ditambahkan di atas file:
> `import ccxt`, `from src.config.settings import settings`, `from datetime import datetime, timezone`

---

### Task 8.3 — Buat `src/data/ws_user_stream.py`

File ini belum ada di codebase. Buat baru.

```python
"""
ws_user_stream.py — User Data WebSocket Binance Futures.

HANYA mendengarkan ORDER_TRADE_UPDATE untuk update status trade di DB.
Berjalan di daemon thread — tidak memblokir loop 15 menit utama.

BUKAN market data stream — tidak ada kline/price data di sini.
"""
import asyncio
import json
import threading

import ccxt
import websockets

from src.config.settings import settings
from src.data.storage import PaperTrade, get_session
from src.utils.logger import logger


def _create_exchange() -> ccxt.binanceusdm:
    """Factory — sama seperti di execution_agent, switch testnet/mainnet dari settings."""
    if settings.USE_TESTNET:
        return ccxt.binanceusdm({
            "apiKey": settings.BINANCE_TESTNET_KEY.get_secret_value(),
            "secret": settings.BINANCE_TESTNET_SECRET.get_secret_value(),
            "options": {"defaultType": "future"},
            "urls": {"api": {
                "public":  str(settings.BINANCE_TESTNET_URL),
                "private": str(settings.BINANCE_TESTNET_URL),
            }},
        })
    return ccxt.binanceusdm({
        "apiKey": settings.BINANCE_API_KEY.get_secret_value(),
        "secret": settings.BINANCE_API_SECRET.get_secret_value(),
        "options": {"defaultType": "future"},
    })


def _get_listen_key() -> tuple[str, str]:
    """Dapatkan listen key dan ws_base_url dari Binance."""
    exchange = _create_exchange()
    response = exchange.fapiPrivatePostListenKey()
    listen_key = response['listenKey']

    ws_base = (
        str(settings.BINANCE_TESTNET_WS_URL)
        if settings.USE_TESTNET
        else str(settings.BINANCE_WS_URL)
    )
    return listen_key, ws_base


def _handle_order_update(data: dict) -> None:
    """Update status trade di DB saat order FILLED."""
    order = data.get('o', {})
    status     = order.get('X')   # Order execution status
    symbol     = order.get('s')   # Symbol e.g. 'BTCUSDT'
    order_type = order.get('ot')  # Order type e.g. 'STOP_MARKET'

    if status != 'FILLED':
        return

    logger.info(f"[UserStream] Order FILLED: {symbol} {order_type}")

    with get_session() as db:
        trade = (
            db.query(PaperTrade)
            .filter(PaperTrade.pair == symbol, PaperTrade.status == 'OPEN')
            .first()
        )
        if not trade:
            logger.debug(f"[UserStream] No open trade found for {symbol}, skipping.")
            return

        if order_type in ('STOP_MARKET', 'STOP'):
            close_reason = 'SL'
        elif order_type in ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT'):
            close_reason = 'TP'
        else:
            close_reason = 'MANUAL'

        avg_price = float(order.get('ap', 0))  # Average fill price

        if trade.side == 'LONG':
            pnl = (avg_price - trade.entry_price) * trade.size
        else:
            pnl = (trade.entry_price - avg_price) * trade.size

        trade.status = 'CLOSED'
        trade.pnl = pnl
        trade.close_reason = close_reason

        logger.info(
            f"[UserStream] Trade {trade.id} CLOSED | {close_reason} | "
            f"PnL: ${pnl:.2f} | {symbol} {trade.side}"
        )


async def _listen_user_stream() -> None:
    """Async loop — reconnect otomatis jika disconnect."""
    while True:
        try:
            listen_key, ws_base = _get_listen_key()
            ws_url = f"{ws_base}/{listen_key}"
            logger.info(f"[UserStream] Connecting... ({'TESTNET' if settings.USE_TESTNET else 'MAINNET'})")

            async with websockets.connect(ws_url) as ws:
                logger.info("[UserStream] Connected. Listening for ORDER_TRADE_UPDATE...")
                async for message in ws:
                    data = json.loads(message)
                    if data.get('e') == 'ORDER_TRADE_UPDATE':
                        _handle_order_update(data)

        except Exception as e:
            logger.error(f"[UserStream] Error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)


def start_user_stream() -> threading.Thread:
    """
    Start User Data WebSocket di daemon thread.
    Panggil dari main() saat EXECUTION_MODE='live'.
    """
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_listen_user_stream())

    thread = threading.Thread(target=_run, daemon=True, name="UserDataStream")
    thread.start()
    logger.info("[UserStream] User Data Stream thread started.")
    return thread
```

---

### Task 8.4 — Update `src/agents/math/sltp_manager.py`

Tambahkan guard di bagian awal `check_paper_trades()` agar tidak jalan di live mode.
Codebase sudah punya fungsi ini, cukup tambahkan guard di baris pertama body:

```python
def check_paper_trades(current_prices: Dict[str, float]) -> List[Dict]:
    """
    Paper mode: cek SL/TP manual dari harga close 15m.
    Live mode: skip — Binance server yang eksekusi, WS handler yang update DB.
    """
    # Guard: di live mode, SL/TP sudah diserahkan ke Binance server
    if settings.EXECUTION_MODE == "live":
        logger.debug("SLTP Manager: live mode, skipping manual check.")
        return []

    # ... sisa kode yang sudah ada tetap sama
```

> Import yang perlu ditambahkan: `from src.config.settings import settings`

---

### Task 8.5 — Update `src/main.py`

Codebase sudah pakai struktur `TradingBot` class. Update method `run()` di class itu:

```python
def run(self):
    setup_logger()
    logger.info(f"Starting Futures Agent | Mode: {settings.EXECUTION_MODE.upper()} | Testnet: {settings.USE_TESTNET}")

    init_db()

    # Start User Data WebSocket jika live mode
    if settings.EXECUTION_MODE == 'live':
        from src.data.ws_user_stream import start_user_stream
        start_user_stream()
        logger.info("[Main] User Data Stream started.")

    # Scheduler dan Telegram bot — ikuti struktur yang sudah ada
    # ... (tidak ada perubahan di bagian scheduler dan bot)
```

---

## ✅ CHECKLIST PHASE 8

### Step 1 — Testnet (USE_TESTNET=True)
- [ ] Buat akun di `testnet.binancefuture.com`, ambil API key
- [ ] Isi `BINANCE_TESTNET_KEY` + `BINANCE_TESTNET_SECRET` di `.env`
- [ ] Set `EXECUTION_MODE=live`, `USE_TESTNET=True`, `FUTURES_DEFAULT_LEVERAGE=2`, `RISK_PER_TRADE_USD=5`
- [ ] Implementasi Task 8.2 (execution_agent live mode)
- [ ] Buat Task 8.3 (ws_user_stream.py)
- [ ] Update Task 8.4 (sltp_manager guard)
- [ ] Update Task 8.5 (main.py start_user_stream)
- [ ] Restart bot: `pm2 restart futures-agent` atau `systemctl restart crypto-agent`
- [ ] Cek log — pastikan tidak ada error saat startup dan saat order masuk
- [ ] Verifikasi di Testnet dashboard: entry order + SL order + TP order terbuat
- [ ] Verifikasi WS: saat order FILLED, status trade di DB update ke CLOSED
- [ ] Jalankan minimal **48 jam** di Testnet tanpa error

### Step 2 — Kumpul Data untuk RL (setelah Testnet stabil)
- [ ] Tunggu minimal **100 closed trades** dari Testnet terkumpul di DB
- [ ] Buat `scripts/export_trade_data.py` — export `paper_trades` status CLOSED ke CSV
- [ ] Lanjut ke **Phase 7** (training RL di Google Colab)

### Step 3 — Mainnet (USE_TESTNET=False)
- [ ] Semua test Testnet PASS + RL model sudah diverifikasi (opsional, bisa parallel)
- [ ] Set `USE_TESTNET=False` di `.env`
- [ ] Restart bot
- [ ] Monitor aktif 24 jam pertama
- [ ] Naikkan leverage dan risk secara bertahap setelah yakin stabil

---

## ⚠️ PERINGATAN LIVE TRADING

```
Modal yang digunakan adalah UANG ASLI saat USE_TESTNET=False.
Pastikan:
1. Testnet sudah jalan 48 jam tanpa error
2. Start dengan leverage rendah (2x) dan risk kecil ($5/trade)
3. Monitor aktif di 24 jam pertama Mainnet
4. SL/TP order harus terkonfirmasi masuk di dashboard Binance setelah setiap entry
```

---

## 🔍 TROUBLESHOOTING UMUM

**Error saat `set_margin_mode('isolated')`:**
Bisa terjadi jika posisi sudah ada di pair tersebut dengan margin mode berbeda.
Solusi: tutup posisi dulu, atau gunakan mode yang sama dengan posisi existing.

**Listen key expired (WS disconnect setelah ~1 jam):**
Binance listen key expired setiap 60 menit. Solusi: implementasi keepalive dengan PUT `/fapi/v1/listenKey` setiap 30 menit. Tambahkan di `_listen_user_stream()` jika diperlukan.

**Order SL/TP rejected:**
Pastikan `amount` menggunakan lot size yang valid untuk pair tersebut.
Gunakan `exchange.amount_to_precision(symbol, amount)` sebelum create order.

---
*Phase 8 Master Prompt — Versi 2.0 | Update April 2026*
*Disesuaikan dengan codebase aktual: TradingBot class, settings-based config, paper trade standalone di-skip*

