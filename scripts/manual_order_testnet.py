#!/usr/bin/env python3
"""
Manual Order Script — Binance Futures TESTNET only.

Usage:
    source venv/bin/activate
    python -m scripts.manual_order_testnet --pair BTCUSDT --entry 84000

SL dihitung dari ATR H4, TP dari R:R ratio.
Direction (LONG/SHORT) ditentukan otomatis dari TrendAgent bias.
Trading params dibaca dari pairs.json ["trading"] section.
Script SELALU force testnet — tidak bisa jalan di mainnet.
"""

import argparse
import sys
from pathlib import Path

# Tambah project root ke sys.path agar `src.*` import jalan
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.math.trend_agent import TrendAgent  # noqa: E402
from src.config.config_loader import load_trading_config  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.data.ohlcv_fetcher import fetch_ohlcv  # noqa: E402
from src.indicators.helpers import calculate_atr  # noqa: E402
from src.utils.exchange import get_exchange, place_algo_order, reset_exchange  # noqa: E402
from src.utils.logger import logger  # noqa: E402


def force_testnet() -> None:
    """
    Force exchange ke testnet, tidak peduli apa yang ada di .env.
    Override settings lalu reset singleton agar exchange baru pakai config testnet.
    """
    if not settings.USE_TESTNET:
        logger.info("USE_TESTNET=False di .env, forcing to True untuk script ini")
        settings.USE_TESTNET = True
        reset_exchange()


def get_trend_bias(symbol: str) -> int:
    """Run TrendAgent di H4, return bias (1=BULLISH, -1=BEARISH, 0=RANGING)."""
    df_h4 = fetch_ohlcv(symbol, "4h")
    if df_h4 is None or df_h4.empty:
        logger.error(f"Gagal fetch H4 data untuk {symbol}")
        sys.exit(1)

    agent = TrendAgent()
    result = agent.run(df_h4)
    logger.info(f"TrendAgent: {result.bias_label} | confidence={result.confidence:.2f} | {result.reason}")
    return result.bias


def calculate_sl_tp(entry: float, bias: int, symbol: str, rr_ratio: float) -> tuple[float, float, float]:
    """
    Hitung SL/TP pakai logika yang sama dengan RiskAgent:
      - SL = entry ± (1.0 * ATR_H4)
      - TP = entry ± (risk_distance * R:R ratio)

    Returns (sl_price, tp_price, risk_distance).
    """
    df_h4 = fetch_ohlcv(symbol, "4h")
    if df_h4 is None or df_h4.empty:
        logger.error("Gagal fetch H4 data untuk ATR kalkulasi")
        sys.exit(1)

    atr_series = calculate_atr(df_h4, period=14)
    atr = atr_series.iloc[-1]
    logger.info(f"ATR(14) H4 = {atr:.4f}")

    if bias == 1:  # BULLISH → LONG
        sl_price = entry - atr
        risk_distance = entry - sl_price
        tp_price = entry + risk_distance * rr_ratio
    else:  # BEARISH → SHORT
        sl_price = entry + atr
        risk_distance = sl_price - entry
        tp_price = entry - risk_distance * rr_ratio

    return sl_price, tp_price, risk_distance


def place_limit_order(symbol: str, side: str, entry: float, quantity: float) -> dict:
    """Place limit order via ccxt (standard endpoint, bukan algo)."""
    exchange = get_exchange()
    result = exchange.create_limit_order(symbol, side, quantity, entry)
    logger.info(f"Limit order placed: {side} {quantity} {symbol} @ {entry}")
    return result


def place_sl_tp_algo(symbol: str, side: str, sl_price: float, tp_price: float, quantity: float) -> tuple[dict, dict]:
    """
    Place SL + TP via Algo Order API.
    - SL: STOP_MARKET, opposite side, reduce-only
    - TP: TAKE_PROFIT_MARKET, opposite side, reduce-only
    """
    close_side = "SELL" if side == "buy" else "BUY"

    sl_result = place_algo_order(
        symbol=symbol,
        side=close_side,
        order_type="STOP_MARKET",
        trigger_price=sl_price,
        quantity=quantity,
        reduce_only=True,
    )
    logger.info(f"SL algo placed: STOP_MARKET {close_side} {symbol} trigger={sl_price}")

    tp_result = place_algo_order(
        symbol=symbol,
        side=close_side,
        order_type="TAKE_PROFIT_MARKET",
        trigger_price=tp_price,
        quantity=quantity,
        reduce_only=True,
    )
    logger.info(f"TP algo placed: TAKE_PROFIT_MARKET {close_side} {symbol} trigger={tp_price}")

    return sl_result, tp_result


def main():
    parser = argparse.ArgumentParser(description="Manual order — TESTNET only (auto-forced)")
    parser.add_argument("--pair", required=True, help="Trading pair, e.g. BTCUSDT")
    parser.add_argument("--entry", required=True, type=float, help="Entry price untuk limit order")
    args = parser.parse_args()

    symbol = args.pair.upper().strip()
    entry_price = args.entry

    if not symbol.endswith("USDT"):
        logger.error(f"Pair harus berakhiran USDT, dapat: {symbol}")
        sys.exit(1)

    # Load config dari pairs.json
    cfg = load_trading_config()
    logger.info(f"Config dari pairs.json: leverage={cfg['leverage']}x, risk=${cfg['risk_per_trade_usd']}, R:R=1:{cfg['risk_reward_ratio']}")

    # Force testnet
    force_testnet()

    # --- Step 1: Trend bias ---
    logger.info(f"=== Manual Order (TESTNET): {symbol} @ {entry_price} ===")
    bias = get_trend_bias(symbol)

    if bias == 0:
        logger.warning("Trend RANGING — tidak ada bias jelas. Tetap lanjut? (y/n)")
        if input("> ").strip().lower() != "y":
            logger.info("Dibatalkan.")
            sys.exit(0)

    # --- Step 2: Determine direction ---
    if bias == 1:
        direction = "LONG"
        side = "buy"
    else:
        direction = "SHORT"
        side = "sell"

    # --- Step 3: Calculate SL/TP ---
    rr_ratio = cfg["risk_reward_ratio"]
    sl_price, tp_price, risk_distance = calculate_sl_tp(entry_price, bias, symbol, rr_ratio)

    # Position size: risk_usd / risk_distance (sama dengan RiskAgent)
    risk_usd = cfg["risk_per_trade_usd"]
    position_size = risk_usd / risk_distance
    leverage = cfg["leverage"]

    # --- Summary ---
    logger.info("=" * 50)
    logger.info(f"  Direction : {direction}")
    logger.info(f"  Entry     : {entry_price}")
    logger.info(f"  SL        : {sl_price:.4f}")
    logger.info(f"  TP        : {tp_price:.4f}")
    logger.info(f"  R:R       : 1:{rr_ratio}")
    logger.info(f"  Size      : {position_size:.6f}")
    logger.info(f"  Risk USD  : ${risk_usd:.2f}")
    logger.info(f"  Leverage  : {leverage}x")
    logger.info("=" * 50)

    # --- Confirm ---
    logger.info("Execute order? (ya/tidak)")
    if input("> ").strip().lower() != "ya":
        logger.info("Dibatalkan.")
        sys.exit(0)

    # --- Step 4: Set leverage + margin type ---
    exchange = get_exchange()
    try:
        exchange.set_leverage(leverage, symbol)
        logger.info(f"Leverage set to {leverage}x for {symbol}")
    except Exception as e:
        logger.warning(f"Set leverage gagal (mungkin sudah sama): {e}")

    try:
        exchange.set_margin_mode(cfg["margin_type"], symbol)
        logger.info(f"Margin mode set to {cfg['margin_type']} for {symbol}")
    except Exception as e:
        logger.warning(f"Set margin mode gagal (mungkin sudah sama): {e}")

    # --- Step 5: Place limit order ---
    order = place_limit_order(symbol, side, entry_price, position_size)
    logger.info(f"Order response: {order.get('id', order)}")

    # --- Step 6: Place SL/TP algo orders ---
    try:
        sl_result, tp_result = place_sl_tp_algo(symbol, side, sl_price, tp_price, position_size)
        logger.info(f"SL algoId: {sl_result.get('algoId', 'N/A')}")
        logger.info(f"TP algoId: {tp_result.get('algoId', 'N/A')}")
    except Exception as e:
        logger.error(f"SL/TP algo gagal: {e}")
        logger.warning("Limit order sudah terpasang TANPA SL/TP — pasang manual di Binance!")

    logger.info("Selesai.")


if __name__ == "__main__":
    main()
