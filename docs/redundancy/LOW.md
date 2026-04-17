# Low Severity Redundancy

## 1. LLM client creation pattern diulang 3x

```python
client = openai.OpenAI(
    api_key=settings.XXX_API_KEY.get_secret_value(),
    base_url=str(settings.XXX_BASE_URL).replace('/chat/completions', ''),
    timeout=settings.XXX_TIMEOUT_SEC,
)
```

| File | Fungsi |
|------|--------|
| `src/agents/llm/analyst_agent.py:84-88` | `run_analyst()` |
| `src/agents/llm/commander_agent.py:36-40` | `run_commander()` |
| `src/agents/llm/concierge_agent.py:27-31` | `run_concierge()` |

**Note:** Beda provider beda API key + base_url, tapi struktur creation identik. Low severity karena masing-masing beda config dan jarang berubah bersamaan.

---

## 2. `model_post_init` di settings.py — 3 block identik

```python
if self.CEREBRAS_API_KEY is None:
    val = secrets.get('cerebras_api_key', '')
    if val:
        object.__setattr__(self, 'CEREBRAS_API_KEY', SecretStr(val))
```

Diulang untuk CEREBRAS_API_KEY, GROQ_API_KEY, CONCIERGE_API_KEY.

| File | Line |
|------|------|
| `src/config/settings.py` | 79-95 |

**Fix:** Loop over mapping `{'CEREBRAS_API_KEY': 'cerebras_api_key', ...}`.

---

## 3. Validator duplikat di settings.py

`validate_production_credentials` dan `validate_testnet_credentials` punya struktur identik — keduanya load system config, cek mode, raise ValueError.

| File | Line |
|------|------|
| `src/config/settings.py` | 37-69 |

**Fix:** Single validator dengan parameter.

---

## 4. OHLCV Candle model — 3 class identik

`OHLCVCandle15m`, `OHLCVCandleH1`, `OHLCVCandleH4` hanya beda `__tablename__` dan index name.

| File | Line |
|------|------|
| `src/data/storage.py` | 60-78 |

**Fix:** Factory function `make_ohlcv_table(table_name, index_name)`.

---

## 5. `_ensure_volume()` deprecated di luxalgo_smc.py

Fungsi ini sudah digantikan `_prepare_df()` tapi belum dihapus.

| File | Line |
|------|------|
| `src/indicators/luxalgo_smc.py` | 85-89 |

**Fix:** Hapus fungsi.
