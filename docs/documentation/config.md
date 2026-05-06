# Config & Secrets

Read this when: working in `src/config/`, editing `config.json`, or adding new config keys.

## Two Sources of Truth

```
.env          → secrets only (API keys, bot token)
config.json   → all non-secret config (pairs, system, trading, llm settings)
```

Access everything via `settings.XXX` — never read `config.json` or `.env` directly.

## settings.py Pattern

`settings.py` holds only secrets as `SecretStr`. Everything else is a `@property` that delegates to `config_loader.py`:

```python
# Secrets — declared as SecretStr fields, loaded from .env
settings.BINANCE_API_KEY        → SecretStr
settings.CEREBRAS_API_KEY       → SecretStr

# Non-secrets — @property delegating to config_loader
settings.EXECUTION_MODE         → str ('paper', 'testnet', 'live')
settings.USE_TESTNET            → bool
settings.RISK_PER_TRADE_USD     → float
settings.FUTURES_DEFAULT_LEVERAGE → int
settings.ANALYST_PROVIDERS      → list
```

SCREAMING_CASE on `@property` is intentional — N802 is ignored for this file.

## config.json Sections

```
pairs[]             → trading pairs e.g. ["BTCUSDT", "ETHUSDT"]
system{}            → execution_mode, use_testnet, confirm_mainnet, telegram_chat_id, URLs
trading{}           → leverage, margin_type, risk_per_trade_usd, rr_ratio, max_open_positions
                      order_expiry_candles, disable_session_filter, trailing_stop{}
llm{}               → per-provider config (cerebras, groq, concierge) + analyst_providers[]
secrets{}           → ${ENV_VAR} references — resolved from .env at load time
```

## How to Add Config

New secret:
```python
# 1. Add to .env
NEW_API_KEY=xxx

# 2. Declare in settings.py as SecretStr
NEW_API_KEY: SecretStr | None = Field(None, description="...")

# 3. Access via
settings.NEW_API_KEY.get_secret_value()
```

New non-secret:
```python
# 1. Add to config.json under the correct section
# 2. Add loader function in config_loader.py if new section
# 3. Add @property in settings.py delegating to config_loader
# 4. Access via settings.NEW_KEY
```

## Env Var Interpolation

`config.json` supports `${ENV_VAR}` syntax in the `secrets{}` section — resolved at load time from `.env`. Never put raw secret values in `config.json`.

## Mode Switch

Changing `execution_mode` or `use_testnet` without restarting keeps stale exchange state.
Always restart bot after any mode change.
`confirm_mainnet` must be `true` before going live on mainnet — bot will refuse to execute if false.

