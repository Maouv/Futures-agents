# src/backtest/_engine_helpers.py
"""
_engine_helpers.py — Pure helper functions untuk BacktestEngine.

Di-extract dari engine.py untuk menjaga BacktestEngine sebagai orchestrator saja.
Semua fungsi di sini adalah pure functions (tidak butuh self) sehingga lebih
mudah di-unit test secara terpisah.

Dipanggil oleh: src/backtest/engine.py
"""
from src.backtest.metrics import TradeResult


def check_exit_conditions(
    position: dict,
    candle_high: float,
    candle_low: float,
    current_close: float,
    current_time: int,
    i: int,
    max_hold_candles: int,
) -> dict | None:
    """
    Cek apakah posisi harus ditutup pada candle saat ini.

    FIX Bug #3: Menggunakan HIGH/LOW candle, bukan close price.
    Ini lebih realistis — SL/TP bisa kena di tengah candle.

    Catatan: jika dalam 1 candle baik TP maupun SL bisa kena (spike),
    kita asumsikan SL yang kena dulu (worst case, lebih konservatif).

    Args:
        position: Dict posisi aktif berisi side, tp_price, sl_price, entry_index.
        candle_high: High candle saat ini.
        candle_low: Low candle saat ini.
        current_close: Close candle saat ini (untuk TIMEOUT exit).
        current_time: Timestamp candle saat ini.
        i: Index candle saat ini di DataFrame.
        max_hold_candles: Batas maksimum candle sebelum timeout.

    Returns:
        Dict {'price': float, 'reason': str} jika exit, None jika masih hold.
    """
    side = position['side']
    tp_price = position['tp_price']
    sl_price = position['sl_price']
    entry_idx = position['entry_index']

    candles_held = i - entry_idx

    if side == "LONG":
        # Worst case: cek SL dulu
        if candle_low <= sl_price:
            return {'price': sl_price, 'reason': 'SL'}
        if candle_high >= tp_price:
            return {'price': tp_price, 'reason': 'TP'}
    else:  # SHORT
        if candle_high >= sl_price:
            return {'price': sl_price, 'reason': 'SL'}
        if candle_low <= tp_price:
            return {'price': tp_price, 'reason': 'TP'}

    # Timeout
    if candles_held >= max_hold_candles:
        return {'price': current_close, 'reason': 'TIMEOUT'}

    return None


def build_trade_result(
    position: dict,
    exit_price: float,
    exit_time: int,
    exit_reason: str,
    exit_index: int,
    fee_rate: float,
    slippage: float,
    balance_at_entry: float,
) -> TradeResult:
    """
    Hitung PnL dan bangun TradeResult dari data posisi dan exit.

    Hitung dengan slippage dan fee dinamis.
    Fee formula: position_size × price × fee_rate (per side).

    Args:
        position: Dict posisi berisi entry_price, side, size, dan metadata.
        exit_price: Harga exit (SL/TP/TIMEOUT).
        exit_time: Timestamp exit.
        exit_reason: 'SL', 'TP', atau 'TIMEOUT'.
        exit_index: Index candle exit.
        fee_rate: Fee rate per side (e.g. 0.0005 untuk 0.05%).
        slippage: Slippage rate per side (e.g. 0.001 untuk 0.1%).
        balance_at_entry: Balance saat entry (untuk hitung pnl_percent).

    Returns:
        TradeResult dengan semua field terisi.
    """
    entry_price = position['entry_price']
    side = position['side']
    size = position['size']

    # Apply slippage
    if side == "LONG":
        actual_entry = entry_price * (1 + slippage)
        actual_exit = exit_price * (1 - slippage)
        pnl = (actual_exit - actual_entry) * size
    else:
        actual_entry = entry_price * (1 - slippage)
        actual_exit = exit_price * (1 + slippage)
        pnl = (actual_entry - actual_exit) * size

    # Fee dinamis: (qty × harga) × tarif — dua sisi
    fee_entry = size * actual_entry * fee_rate
    fee_exit = size * actual_exit * fee_rate
    total_fee = fee_entry + fee_exit

    net_pnl = pnl - total_fee
    pnl_percent = (net_pnl / balance_at_entry) * 100

    candles_held = exit_index - position['entry_index']

    return TradeResult(
        entry_time=position['entry_time'],
        exit_time=exit_time,
        entry_price=actual_entry,
        exit_price=actual_exit,
        side=side,
        size=size,
        pnl=net_pnl,
        pnl_percent=pnl_percent,
        fee=total_fee,
        exit_reason=exit_reason,
        sl_price=position['sl_price'],
        tp_price=position['tp_price'],
        candles_held=candles_held,
        atr=position.get('atr', 0.0),
        ob_high=position.get('ob_high', 0.0),
        ob_low=position.get('ob_low', 0.0),
        trend_bias=position.get('trend_bias', 'RANGING'),
        confidence=position.get('confidence', 0),
    )
