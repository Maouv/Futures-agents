# Config Migration Plan: pairs.json → config.json

**Date**: 2026-04-15
**Status**: Planned

## Problem

Trading params (`RISK_PER_TRADE_USD`, `RISK_REWARD_RATIO`, `FUTURES_DEFAULT_LEVERAGE`, `MAX_OPEN_POSITIONS`, dll.) saat ini dikonfigurasi di `.env` melalui `settings.py`. Ini menyebabkan:

1. **Test failures** — test hardcode default values tapi `.env` override nilainya, assertion gagal
2. **Tidak bisa di-commit** — `.env` di gitignore, jadi config changes tidak bisa di-review/di-version
3. **Duplikasi** — `pairs.json["trading"]` sudah punya trading params tapi tidak dipakai oleh `settings.py`
4. **Tidak rapi** — LLM model names, base URLs, timeout values bukan secret tapi disimpan di `.env`

## Solution

Rename `pairs.json` → `config.json`, restructure menjadi 3 section, dan implementasi env var interpolation.

### Core Design: `config.json` is the SINGLE config file

**`config.json`** berisi SEMUA config (secrets + non-secrets). Untuk secret values, gunakan syntax `${ENV_VAR}` yang di-resolve dari `.env` saat runtime. User bebas memilih:

- `"${CEREBRAS_API_KEY}"` → resolve dari `.env` (aman di-commit, best practice)
- `"csk-abc123"` → hardcode langsung (TIDAK aman di-commit, tapi terserah user)

**`.env`** hanya menyimpan secret values yang di-reference oleh `config.json`. Tidak ada config logic di `.env`.

### Config Resolution Flow

```
1. Load .env → dict of secrets
2. Load config.json → raw dict (may contain "${ENV_VAR}" strings)
3. Resolve: replace "${...}" with .env values
4. Validated config ready for use
```

### Config Location Rule

| Type | File | Contoh | Alasan |
|------|------|--------|--------|
| **All config** | `config.json` | Semua field termasuk api_key | Single source of truth |
| **Secret values** | `.env` | API key values | Tidak masuk git, di-reference via `${...}` |
| **Safety gates** | `config.json` | `confirm_mainnet` | Visible di config, sengaja di-toggle |

### New `config.json` Structure

```json
{
  "pairs": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "SUIUSDT"],

  "system": {
    "execution_mode": "paper",
    "use_testnet": false,
    "environment": "production",
    "confirm_mainnet": false,
    "telegram_chat_id": "5112950656",
    "binance_rest_url": "https://fapi.binance.com",
    "binance_ws_url": "wss://fstream.binance.com/ws",
    "binance_testnet_url": "https://testnet.binancefuture.com",
    "binance_testnet_ws_url": "wss://stream.binancefuture.com/ws"
  },

  "trading": {
    "leverage": 10,
    "margin_type": "isolated",
    "risk_per_trade_usd": 10.0,
    "risk_reward_ratio": 2.0,
    "max_open_positions": 1,
    "order_expiry_candles": 48,
    "disable_session_filter": true
  },

  "secrets": {
    "cerebras_api_key": "${CEREBRAS_API_KEY}",
    "groq_api_key": "${GROQ_API_KEY}",
    "concierge_api_key": "${CONCIERGE_API_KEY}"
  },

  "llm": {
    "cerebras": {
      "base_url": "https://api.cerebras.ai/v1/chat/completions",
      "model": "qwen-3-235b-a22b-instruct-2507",
      "max_concurrent": 2,
      "rpm": 30,
      "retry_on_429": 2,
      "timeout_sec": 45
    },
    "groq": {
      "base_url": "https://api.groq.com/openai/v1/chat/completions",
      "model": "llama-3.1-8b-instant",
      "max_concurrent": 3,
      "rpm": 30,
      "timeout_sec": 45
    },
    "concierge": {
      "base_url": "https://api.groq.com/openai/v1/chat/completions",
      "model": "openai/gpt-oss-120b",
      "timeout_sec": 600,
      "max_tokens": 5000
    }
  }
}
```

**Key design**: `secrets` section uses `${ENV_VAR}` syntax. The config loader resolves these at runtime from `.env`. User can also hardcode values directly (not recommended for git, but supported).

### `.env` (Binance keys + Telegram bot token — NOT in config.json)

```env
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_TESTNET_KEY=
BINANCE_TESTNET_SECRET=
CEREBRAS_API_KEY=
GROQ_API_KEY=
CONCIERGE_API_KEY=
TELEGRAM_BOT_TOKEN=
```

**Note**: Binance keys and Telegram bot token stay in `.env` only — no need to reference them in config.json. Chat ID is hardcoded in config.json (not sensitive).

### Field Migration Map

| Current `settings.py` field | Moves to | Value in config.json |
|---|---|---|
| `BINANCE_API_KEY/SECRET` | `.env` only | Stays — not referenced in config.json |
| `BINANCE_TESTNET_KEY/SECRET` | `.env` only | Stays — not referenced in config.json |
| `TELEGRAM_BOT_TOKEN` | `.env` only | Stays — not referenced in config.json |
| `CEREBRAS_API_KEY` | `config.json["secrets"]` | `"${CEREBRAS_API_KEY}"` (resolved from .env) |
| `GROQ_API_KEY` | `config.json["secrets"]` | `"${GROQ_API_KEY}"` |
| `CONCIERGE_API_KEY` | `config.json["secrets"]` | `"${CONCIERGE_API_KEY}"` |
| `TELEGRAM_CHAT_ID` | `config.json["system"]` | `"5112950656"` (hardcoded, not sensitive) |
| `CONFIRM_MAINNET` | `config.json["system"]` | `false` (hardcoded boolean) |
| `EXECUTION_MODE` | `config.json["system"]` | `"paper"` |
| `USE_TESTNET` | `config.json["system"]` | `false` |
| `ENVIRONMENT` | `config.json["system"]` | `"production"` |
| `BINANCE_REST_URL` | `config.json["system"]` | `"https://fapi.binance.com"` |
| `BINANCE_WS_URL` | `config.json["system"]` | `"wss://fstream.binance.com/ws"` |
| `BINANCE_TESTNET_URL` | `config.json["system"]` | `"https://testnet.binancefuture.com"` |
| `BINANCE_TESTNET_WS_URL` | `config.json["system"]` | `"wss://stream.binancefuture.com/ws"` |
| `FUTURES_DEFAULT_LEVERAGE` | `config.json["trading"]` | `10` |
| `FUTURES_MARGIN_TYPE` | `config.json["trading"]` | `"isolated"` |
| `RISK_PER_TRADE_USD` | `config.json["trading"]` | `10.0` |
| `RISK_REWARD_RATIO` | `config.json["trading"]` | `2.0` |
| `MAX_OPEN_POSITIONS` | `config.json["trading"]` | `1` |
| `ORDER_EXPIRY_CANDLES` | `config.json["trading"]` | `48` |
| `DISABLE_SESSION_FILTER` | `config.json["trading"]` | `true` |
| `CEREBRAS_BASE_URL` | `config.json["llm"]["cerebras"]` | `"https://api.cerebras.ai/v1/chat/completions"` |
| `CEREBRAS_MODEL` | `config.json["llm"]["cerebras"]` | `"qwen-3-235b-a22b-instruct-2507"` |
| `LLM_CEREBRAS_MAX_CONCURRENT` | `config.json["llm"]["cerebras"]` | `2` |
| `LLM_CEREBRAS_RPM` | `config.json["llm"]["cerebras"]` | `30` |
| `LLM_RETRY_ON_429` | `config.json["llm"]["cerebras"]` | `2` |
| `GROQ_BASE_URL` | `config.json["llm"]["groq"]` | `"https://api.groq.com/openai/v1/chat/completions"` |
| `GROQ_MODEL` | `config.json["llm"]["groq"]` | `"llama-3.1-8b-instant"` |
| `LLM_GROQ_MAX_CONCURRENT` | `config.json["llm"]["groq"]` | `3` |
| `LLM_GROQ_RPM` | `config.json["llm"]["groq"]` | `30` |
| `CONCIERGE_BASE_URL` | `config.json["llm"]["concierge"]` | `"https://api.groq.com/openai/v1/chat/completions"` |
| `CONCIERGE_MODEL` | `config.json["llm"]["concierge"]` | `"openai/gpt-oss-120b"` |
| `CONCIERGE_TIMEOUT_SEC` | `config.json["llm"]["concierge"]` | `600` |
| `CONCIERGE_MAX_TOKENS` | `config.json["llm"]["concierge"]` | `5000` |
| `LLM_FAST_TIMEOUT_SEC` | `config.json["llm"]["cerebras"]` + `["groq"]` | `45` (per-provider) |

## Implementation Steps

### Step 1: Rename pairs.json → config.json
- Rename file
- Update `PAIRS_FILE` path in `pairs.py`

### Step 2: Restructure config.json
- Add `system` and `llm` sections
- Move trading params into `trading` section (already exists)

### Step 3: Update pairs.py → config_loader.py
- Rename file to `config_loader.py`
- Add `load_system_config()` and `load_llm_config()` functions
- Keep `load_pairs()` and `load_trading_config()`
- All functions read from `config.json`

### Step 4: Update settings.py
- Remove fields that move to config.json
- Keep only secrets (SecretStr fields) + CONFIRM_MAINNET
- Add `@property` or helper methods that read from config.json for non-secret fields
- Backward compat: if config.json field missing, use hardcoded default (same as current)

### Step 5: Update all consumers
Files that access `settings.RISK_PER_TRADE_USD`, `settings.RISK_REWARD_RATIO`, etc.:
- `src/agents/math/risk_agent.py` (3 refs)
- `src/agents/math/execution_agent.py` (5 refs)
- `src/agents/llm/analyst_agent.py` (1 ref)
- `src/main.py` (1 ref)
- `src/telegram/commands.py` (2 refs)
- `src/data/ohlcv_fetcher.py` (1 ref)
- `src/backtest/engine.py` (3 refs)

Replace `settings.XXX` → `config.XXX` (from config_loader)

### Step 6: Fix tests
- Tests that hardcode default values should read from config, not hardcode
- Tests that construct `Settings()` should only need secret fields in env

### Step 7: Update CLAUDE.md
- Update config section to reflect new structure
- Add config.json schema reference
- Update .env.example note

## Regression Checklist

- [ ] Bot starts successfully with new config.json
- [ ] All secrets still loaded from .env
- [ ] Trading params read from config.json, not .env
- [ ] LLM params read from config.json, not .env
- [ ] Existing tests pass (or are fixed)
- [ ] `settings.XXX` still works for secrets
- [ ] No circular imports between config_loader.py and settings.py
- [ ] Backward compat: bot works with default values even if config.json sections missing

## Files Changed Summary

| File | Action |
|------|--------|
| `pairs.json` | RENAME → `config.json`, restructure |
| `src/config/pairs.py` | RENAME → `config_loader.py`, add new loaders |
| `src/config/settings.py` | Remove non-secret fields |
| `src/agents/math/risk_agent.py` | Update config access |
| `src/agents/math/execution_agent.py` | Update config access |
| `src/agents/llm/analyst_agent.py` | Update config access |
| `src/main.py` | Update config access |
| `src/telegram/commands.py` | Update config access |
| `src/data/ohlcv_fetcher.py` | Update config access |
| `src/backtest/engine.py` | Update config access |
| `.env.example` | Only secrets |
| `CLAUDE.md` | Update config docs |
