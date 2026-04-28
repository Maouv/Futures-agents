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
_config_cache: dict | None = None


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
        with open(CONFIG_FILE) as f:
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


def load_pairs() -> list[str]:
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


def _coerce_value(value, target_type):
    """Coerce a single config value to the expected type.

    Handles common JSON issues where numbers are stored as strings.
    Returns the original value if coercion fails (with a warning).
    """
    if isinstance(value, target_type):
        return value
    try:
        if target_type is bool:
            if isinstance(value, str):
                return value.lower() in ('true', '1', 'yes')
            return bool(value)
        return target_type(value)
    except (ValueError, TypeError):
        logger.warning(
            f"config.json: cannot coerce {value!r} to {target_type.__name__}, keeping original"
        )
        return value


def _coerce_config(config: dict, schema: dict) -> dict:
    """
    Coerce config dict values to match the types defined in a schema dict.

    Recursively handles nested dicts. For scalar values, coerces to the type
    of the corresponding schema value. Keys not present in schema are passed
    through unchanged.

    This ensures that JSON config values like "100" (string) are properly
    converted to their expected types (int, float, bool) before consumption
    by downstream code.
    """
    result = dict(config)
    for key, default in schema.items():
        if key not in result:
            result[key] = default
            continue
        if isinstance(default, dict) and isinstance(result[key], dict):
            result[key] = _coerce_config(result[key], default)
        elif not isinstance(default, dict):
            result[key] = _coerce_value(result[key], type(default))
    return result


def load_system_config() -> dict:
    """Load system section from config.json with type coercion. Fallback to DEFAULT_SYSTEM."""
    data = _load_config()
    system = data.get("system", {})
    merged = {**DEFAULT_SYSTEM, **system}
    return _coerce_config(merged, DEFAULT_SYSTEM)


def load_trading_config() -> dict:
    """Load trading section from config.json with type coercion. Fallback to DEFAULT_TRADING."""
    data = _load_config()
    trading = data.get("trading", {})
    merged = {**DEFAULT_TRADING, **trading}
    return _coerce_config(merged, DEFAULT_TRADING)


def load_trailing_stop_config() -> dict:
    """Load trailing_stop sub-section from config.json with type coercion."""
    trading = load_trading_config()
    default_ts = DEFAULT_TRADING["trailing_stop"]
    user_ts = trading.get("trailing_stop", {})
    merged = {**default_ts, **user_ts}
    return _coerce_config(merged, default_ts)


def load_llm_config() -> dict:
    """Load llm section from config.json with type coercion. Fallback to DEFAULT_LLM."""
    data = _load_config()
    llm = data.get("llm", {})
    result = {}
    for provider, defaults in DEFAULT_LLM.items():
        provider_config = llm.get(provider, {})
        merged = {**defaults, **provider_config}
        result[provider] = _coerce_config(merged, defaults)
    # Pass-through analyst_providers as-is (list of dicts, no coercion needed)
    if 'analyst_providers' in llm:
        result['analyst_providers'] = llm['analyst_providers']
    return result


def load_secrets_config() -> dict:
    """Load secrets section from config.json. ${ENV_VAR} resolved by _load_config()."""
    data = _load_config()
    secrets = data.get("secrets", {})
    return {**DEFAULT_SECRETS, **secrets}

