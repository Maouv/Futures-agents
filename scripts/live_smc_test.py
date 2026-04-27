"""
live_smc_test.py — Fetch live OHLCV dari Binance Futures lalu jalankan SMC indicators.

Usage:
    python scripts/live_smc_test.py                              # default: BTCUSDT 15m 200 candles
    python scripts/live_smc_test.py --symbol ETHUSDT
    python scripts/live_smc_test.py --symbol BTCUSDT --timeframe 4h --limit 500
    python scripts/live_smc_test.py --symbol BTCUSDT --swing-ob 5 --swing-bos 10

Parameter swing:
    --swing-ob   swing untuk Order Block detection (default: 5)
                 Kecil = tangkap internal OB + major OB
                 Besar = major OB saja
    --swing-bos  swing untuk BOS/CHOCH & bias (default: 10)
                 Kecil = bias sensitif, sering ganti
                 Besar = bias stabil, ikuti struktur mayor

OB lama (HTF) tetap ditampilkan semua — OB dari bulan lalu di 4h/1d
tetap valid sebagai acuan institusional.
"""

import argparse
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
import pandas as pd

from src.config.settings import settings
from src.indicators.luxalgo_smc import detect_order_blocks, detect_fvg, detect_bos_choch


# ── CLI Args ─────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Live SMC test dari Binance Futures")
    p.add_argument("--symbol",    default="BTCUSDT", help="Trading pair (default: BTCUSDT)")
    p.add_argument("--timeframe", default="15m",     help="Timeframe: 1m 5m 15m 1h 4h 1d (default: 15m)")
    p.add_argument("--limit",     type=int, default=200, help="Jumlah candle/bars (default: 200, max: 1500)")
    p.add_argument("--swing-ob",  type=int, default=5,   dest="swing_ob",
                   help="Swing length untuk OB detection (default: 5)")
    p.add_argument("--swing-bos", type=int, default=10,  dest="swing_bos",
                   help="Swing length untuk BOS/CHOCH & bias (default: 10)")
    return p.parse_args()


# ── Fetch OHLCV ──────────────────────────────────────────────────────────────
def fetch_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    exchange = ccxt.binanceusdm({
        "apiKey": settings.BINANCE_API_KEY.get_secret_value(),
        "secret": settings.BINANCE_API_SECRET.get_secret_value(),
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })

    print(f"\n[FETCH] {symbol} {timeframe} — {limit} candles dari Binance Futures...")
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")

    print(f"[FETCH] ✅ Dapat {len(df)} candles | {df.index[0]} → {df.index[-1]}")
    print(f"[FETCH] Close terakhir: {df['close'].iloc[-1]:,.2f} USDT")
    return df


# ── Debug: Order Blocks ──────────────────────────────────────────────────────
def debug_order_blocks(df: pd.DataFrame, obs: list, n_show: int = 10):
    print(f"\n{'='*60}")
    print(f"[OB] Order Blocks ditemukan: {len(obs)}")
    print(f"{'='*60}")

    if not obs:
        print("[OB] Tidak ada OB yang terdeteksi.")
        return

    bullish = [o for o in obs if o.bias == 1]
    bearish = [o for o in obs if o.bias == -1]
    print(f"[OB] Bullish: {len(bullish)} | Bearish: {len(bearish)}")
    print(f"[OB] Mitigated: {sum(o.mitigated for o in obs)} / {len(obs)}")

    recent = sorted(obs, key=lambda o: o.index, reverse=True)[:n_show]
    print(f"\n[OB] {min(n_show, len(obs))} OB terbaru:")
    print(f"  {'IDX':>5}  {'TIME':>25}  {'BIAS':>7}  {'HIGH':>12}  {'LOW':>12}  {'MITIGATED':>10}")
    print(f"  {'-'*80}")

    for ob in recent:
        try:
            ts = str(df.index[ob.index])[:19]
        except IndexError:
            ts = "N/A"
        bias_str = "BULLISH" if ob.bias == 1 else "BEARISH"
        mit_str  = "✅ YES" if ob.mitigated else "❌ NO"
        print(f"  {ob.index:>5}  {ts:>25}  {bias_str:>7}  {ob.high:>12,.2f}  {ob.low:>12,.2f}  {mit_str:>10}")

    current_price = df["close"].iloc[-1]
    active = [o for o in obs if not o.mitigated]
    print(f"\n[OB] Harga sekarang: {current_price:,.2f}")
    print(f"[OB] Active (unmitigated) OBs: {len(active)}")

    nearest_bull = None
    nearest_bear = None
    for o in active:
        if o.bias == 1 and o.low < current_price:
            if nearest_bull is None or o.low > nearest_bull.low:
                nearest_bull = o
        if o.bias == -1 and o.high > current_price:
            if nearest_bear is None or o.high < nearest_bear.high:
                nearest_bear = o

    if nearest_bull:
        try:
            ts = str(df.index[nearest_bull.index])[:19]
        except IndexError:
            ts = "N/A"
        dist = current_price - nearest_bull.high
        print(f"[OB] ➡️  Nearest Bullish OB: {nearest_bull.high:,.2f}–{nearest_bull.low:,.2f} @ {ts} (jarak: {dist:,.2f})")
    else:
        print("[OB] ➡️  Tidak ada active Bullish OB di bawah harga")

    if nearest_bear:
        try:
            ts = str(df.index[nearest_bear.index])[:19]
        except IndexError:
            ts = "N/A"
        dist = nearest_bear.low - current_price
        print(f"[OB] ➡️  Nearest Bearish OB: {nearest_bear.high:,.2f}–{nearest_bear.low:,.2f} @ {ts} (jarak: {dist:,.2f})")
    else:
        print("[OB] ➡️  Tidak ada active Bearish OB di atas harga")


# ── Debug: Fair Value Gaps ───────────────────────────────────────────────────
def debug_fvg(df: pd.DataFrame, fvgs: list, n_show: int = 10):
    print(f"\n{'='*60}")
    print(f"[FVG] Fair Value Gaps ditemukan: {len(fvgs)}")
    print(f"{'='*60}")

    if not fvgs:
        print("[FVG] Tidak ada FVG yang terdeteksi.")
        return

    bullish = [f for f in fvgs if f.bias == 1]
    bearish = [f for f in fvgs if f.bias == -1]
    filled  = [f for f in fvgs if f.filled]
    print(f"[FVG] Bullish: {len(bullish)} | Bearish: {len(bearish)}")
    print(f"[FVG] Filled: {len(filled)} / {len(fvgs)} | Unfilled: {len(fvgs) - len(filled)}")

    recent = sorted(fvgs, key=lambda f: f.index, reverse=True)[:n_show]
    print(f"\n[FVG] {min(n_show, len(fvgs))} FVG terbaru:")
    print(f"  {'IDX':>5}  {'TIME':>25}  {'BIAS':>7}  {'TOP':>12}  {'BOTTOM':>12}  {'GAP':>8}  {'FILLED':>8}")
    print(f"  {'-'*90}")

    for fvg in recent:
        try:
            ts = str(df.index[fvg.index])[:19]
        except IndexError:
            ts = "N/A"
        bias_str = "BULLISH" if fvg.bias == 1 else "BEARISH"
        gap      = fvg.top - fvg.bottom
        fil_str  = "✅ YES" if fvg.filled else "❌ NO"
        print(f"  {fvg.index:>5}  {ts:>25}  {bias_str:>7}  {fvg.top:>12,.2f}  {fvg.bottom:>12,.2f}  {gap:>8,.2f}  {fil_str:>8}")

    current_price = df["close"].iloc[-1]
    active = [f for f in fvgs if not f.filled]
    print(f"\n[FVG] Harga sekarang: {current_price:,.2f}")
    print(f"[FVG] Active (unfilled) FVGs: {len(active)}")

    nearest_bull = None
    nearest_bear = None
    for f in active:
        if f.bias == 1 and f.top < current_price:
            if nearest_bull is None or f.top > nearest_bull.top:
                nearest_bull = f
        if f.bias == -1 and f.bottom > current_price:
            if nearest_bear is None or f.bottom < nearest_bear.bottom:
                nearest_bear = f

    if nearest_bull:
        try:
            ts = str(df.index[nearest_bull.index])[:19]
        except IndexError:
            ts = "N/A"
        dist = current_price - nearest_bull.top
        print(f"[FVG] ➡️  Nearest Bullish FVG: {nearest_bull.top:,.2f}–{nearest_bull.bottom:,.2f} @ {ts} (jarak: {dist:,.2f})")
    else:
        print("[FVG] ➡️  Tidak ada active Bullish FVG di bawah harga")

    if nearest_bear:
        try:
            ts = str(df.index[nearest_bear.index])[:19]
        except IndexError:
            ts = "N/A"
        dist = nearest_bear.bottom - current_price
        print(f"[FVG] ➡️  Nearest Bearish FVG: {nearest_bear.top:,.2f}–{nearest_bear.bottom:,.2f} @ {ts} (jarak: {dist:,.2f})")
    else:
        print("[FVG] ➡️  Tidak ada active Bearish FVG di atas harga")


# ── Debug: BOS/CHOCH ─────────────────────────────────────────────────────────
def debug_bos_choch(df: pd.DataFrame, signals: list):
    print(f"\n{'='*60}")
    print(f"[BOS/CHOCH] Signals ditemukan: {len(signals)}")
    print(f"{'='*60}")

    if not signals:
        print("[BOS/CHOCH] Tidak ada sinyal.")
        return

    bos   = [s for s in signals if s.type == "BOS"]
    choch = [s for s in signals if s.type == "CHOCH"]
    print(f"[BOS/CHOCH] BOS: {len(bos)} | CHOCH: {len(choch)}")

    recent = sorted(signals, key=lambda s: s.index, reverse=True)[:5]
    print("\n[BOS/CHOCH] 5 sinyal terbaru:")
    print(f"  {'IDX':>5}  {'TIME':>25}  {'TYPE':>6}  {'BIAS':>7}  {'LEVEL':>12}")
    print(f"  {'-'*65}")
    for s in recent:
        try:
            ts = str(df.index[s.index])[:19]
        except IndexError:
            ts = "N/A"
        bias_str = "BULLISH" if s.bias == 1 else "BEARISH"
        print(f"  {s.index:>5}  {ts:>25}  {s.type:>6}  {bias_str:>7}  {s.level:>12,.2f}")

    last = signals[-1]
    bias_label = "BULLISH 🟢" if last.bias == 1 else "BEARISH 🔴"
    print(f"\n[BOS/CHOCH] ➡️  Current market bias: {bias_label} (dari {last.type} @ index {last.index})")


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()

    print(f"\n{'='*60}")
    print(f"  SMC Live Test — {args.symbol} {args.timeframe}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{'='*60}")

    # 1. Fetch data
    df = fetch_ohlcv(args.symbol, args.timeframe, args.limit)
    df_plain = df.reset_index(drop=True)

    # 2. Jalankan indikator dengan swing terpisah
    print("\n[SMC] Running indicators...")
    print(f"[SMC] OB swing_length={args.swing_ob} | BOS swing_length={args.swing_bos}")
    obs     = detect_order_blocks(df_plain, swing_length=args.swing_ob)
    fvgs    = detect_fvg(df_plain)
    signals = detect_bos_choch(df_plain, swing_length=args.swing_bos)
    print("[SMC] ✅ Done")

    # 3. Debug output
    debug_order_blocks(df, obs)
    debug_fvg(df, fvgs)
    debug_bos_choch(df, signals)

    print(f"\n{'='*60}")
    print(f"  SUMMARY — {args.symbol} {args.timeframe}")
    print(f"  Candles   : {len(df)}")
    print(f"  Swing OB  : {args.swing_ob} | Swing BOS: {args.swing_bos}")
    print(f"  OB        : {len(obs)} ({sum(1 for o in obs if not o.mitigated)} active)")
    print(f"  FVG       : {len(fvgs)} ({sum(1 for f in fvgs if not f.filled)} unfilled)")
    print(f"  BOS/CHOCH : {len(signals)}")
    bias = signals[-1].bias if signals else 0
    print(f"  Bias      : {'BULLISH 🟢' if bias == 1 else 'BEARISH 🔴' if bias == -1 else 'NEUTRAL ⚪'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
