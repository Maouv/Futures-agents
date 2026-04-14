"""
pairs.py — Loader untuk konfigurasi trading pairs dan params dari pairs.json.
Tinggal edit pairs.json di root project, restart bot, langsung aktif.
"""
import json
from pathlib import Path
from typing import Dict, List

from src.utils.logger import logger

PAIRS_FILE = Path(__file__).resolve().parent.parent.parent / "pairs.json"


def load_pairs() -> List[str]:
    """
    Load daftar trading pairs dari pairs.json.
    Return list of string, e.g. ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'].
    Fallback ke ['BTCUSDT'] jika file tidak ditemukan.
    """
    if not PAIRS_FILE.exists():
        logger.warning(f"pairs.json not found at {PAIRS_FILE}. Falling back to BTCUSDT only.")
        return ["BTCUSDT"]

    try:
        with open(PAIRS_FILE, "r") as f:
            data = json.load(f)

        pairs = data.get("pairs", [])

        if not pairs:
            logger.warning("pairs.json is empty. Falling back to BTCUSDT only.")
            return ["BTCUSDT"]

        # Validate: must be uppercase, end with USDT
        valid = []
        for p in pairs:
            p = p.strip().upper()
            if not p.endswith("USDT"):
                logger.warning(f"Skipping invalid pair '{p}' (must end with USDT)")
                continue
            valid.append(p)

        if not valid:
            logger.warning("No valid pairs found. Falling back to BTCUSDT only.")
            return ["BTCUSDT"]

        logger.info(f"Loaded {len(valid)} pairs: {', '.join(valid)}")
        return valid

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in pairs.json: {e}. Falling back to BTCUSDT only.")
        return ["BTCUSDT"]


DEFAULT_TRADING = {
    "execution_mode": "paper",
    "leverage": 10,
    "margin_type": "isolated",
    "risk_per_trade_usd": 10.0,
    "risk_reward_ratio": 2.0,
    "max_open_positions": 1,
}


def load_trading_config() -> Dict:
    """
    Load trading params dari pairs.json ["trading"] section.
    Fallback ke DEFAULT_TRADING jika section tidak ada.
    """
    if not PAIRS_FILE.exists():
        return DEFAULT_TRADING.copy()

    try:
        with open(PAIRS_FILE, "r") as f:
            data = json.load(f)

        trading = data.get("trading", {})
        config = {**DEFAULT_TRADING, **trading}
        return config

    except (json.JSONDecodeError, OSError):
        return DEFAULT_TRADING.copy()
