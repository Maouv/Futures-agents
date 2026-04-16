"""
config_loader.py — Loader for config.json (formerly pairs.json).
Single source of truth for all non-secret configuration.

Sections:
  - pairs: List of trading pairs
  - system: Execution mode, URLs, Telegram chat ID
  - trading: Leverage, risk, position params
  - secrets: ${ENV_VAR} references resolved from .env
  - llm: Per-provider LLM config (Cerebras, Groq, Concierge)

Env var interpolation: "${CEREBRAS_API_KEY}" → resolved from .env at load time.
"""
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from src.utils.logger import logger

CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "config.json"

# Pattern for ${ENV_VAR} interpolation
_ENV_VAR_PATTERN = re.compile(r'\$\{(\w+)\}')


def _resolve_env_vars(value):
    """Recursively resolve ${ENV_VAR} references in config values."""
    if isinstance(value, str):
        def _replace(match):
            env_key = match.group(1)
            env_val = os.getenv(env_key, "")
            if not env_val:
                logger.warning(f"config.json: env var ${{{env_key}}} is empty or not set")
            return env_val
        return _ENV_VAR_PATTERN.sub(_replace, value)
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


# ── Config cache (avoid re-reading file on every property access) ──────────────
_config_cache: Optional[dict] = None


def _load_config() -> dict:
    """Load and parse config.json with caching. Returns empty dict if file not found."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    if not CONFIG_FILE.exists():
        logger.warning(f"config.json not found at {CONFIG_FILE}. Using defaults.")
        _config_cache = {}
        return _config_cache

    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        _config_cache = _resolve_env_vars(data)
        return _config_cache
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config.json: {e}. Using defaults.")
        _config_cache = {}
        return _config_cache


def reload_config() -> None:
    """Force reload config.json on next access. Call after editing config.json."""
    global _config_cache
    _config_cache = None


def set_config_override(config: dict) -> None:
    """Set config cache directly (for testing). Call reload_config() to clear."""
    global _config_cache
    _config_cache = config


def load_pairs() -> List[str]:
    """
    Load list of trading pairs from config.json.
    Fallback to ['BTCUSDT'] if file not found or empty.
    """
    data = _load_config()
    pairs = data.get("pairs", [])

    if not pairs:
        logger.warning("config.json: no pairs found. Falling back to BTCUSDT only.")
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


# ── Default values for backward compatibility ──────────────────────────────────

DEFAULT_SYSTEM = {
    "execution_mode": "paper",
    "use_testnet": False,
    "environment": "production",
    "confirm_mainnet": False,
    "telegram_chat_id": "",
    "binance_rest_url": "https://fapi.binance.com",
    "binance_ws_url": "wss://fstream.binance.com/ws",
    "binance_testnet_url": "https://testnet.binancefuture.com",
    "binance_testnet_ws_url": "wss://stream.binancefuture.com/ws",
}

DEFAULT_TRADING = {
    "leverage": 10,
    "margin_type": "isolated",
    "risk_per_trade_usd": 10.0,
    "risk_reward_ratio": 2.0,
    "max_open_positions": 1,
    "order_expiry_candles": 48,
    "disable_session_filter": True,
    "trailing_stop": {
        "enabled": False,
        "steps": [
            {"profit_pct": 1.0, "new_sl_pct": 0.0},
            {"profit_pct": 2.0, "new_sl_pct": 0.5},
            {"profit_pct": 3.0, "new_sl_pct": 1.0},
        ],
    },
}

DEFAULT_LLM = {
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1/chat/completions",
        "model": "qwen-3-235b-a22b-instruct-2507",
        "max_concurrent": 2,
        "rpm": 30,
        "min_interval": 3.0,
        "retry_on_429": 2,
        "timeout_sec": 45,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.1-8b-instant",
        "max_concurrent": 3,
        "rpm": 30,
        "min_interval": 1.0,
        "timeout_sec": 45,
    },
    "concierge": {
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "openai/gpt-oss-120b",
        "timeout_sec": 600,
        "max_tokens": 5000,
    },
}

DEFAULT_SECRETS = {
    "cerebras_api_key": "",
    "groq_api_key": "",
    "concierge_api_key": "",
}


def load_system_config() -> Dict:
    """Load system section from config.json. Fallback to DEFAULT_SYSTEM."""
    data = _load_config()
    system = data.get("system", {})
    return {**DEFAULT_SYSTEM, **system}


def load_trading_config() -> Dict:
    """Load trading section from config.json. Fallback to DEFAULT_TRADING."""
    data = _load_config()
    trading = data.get("trading", {})
    return {**DEFAULT_TRADING, **trading}


def load_trailing_stop_config() -> Dict:
    """Load trailing_stop sub-section from config.json trading section."""
    trading = load_trading_config()
    default_ts = DEFAULT_TRADING["trailing_stop"]
    user_ts = trading.get("trailing_stop", {})
    return {**default_ts, **user_ts}


def load_llm_config() -> Dict:
    """Load llm section from config.json. Fallback to DEFAULT_LLM."""
    data = _load_config()
    llm = data.get("llm", {})
    result = {}
    for provider, defaults in DEFAULT_LLM.items():
        provider_config = llm.get(provider, {})
        result[provider] = {**defaults, **provider_config}
    return result


def load_secrets_config() -> Dict:
    """Load secrets section from config.json. ${ENV_VAR} resolved by _load_config()."""
    data = _load_config()
    secrets = data.get("secrets", {})
    return {**DEFAULT_SECRETS, **secrets}
