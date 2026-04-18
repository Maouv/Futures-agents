#.

---

## 2. HMAC signing + base_url logic diulang di exchange.py

`place_algo_order()` dan `cancel_algo_order()` keduanya punya:

```python
import time, hashlib, hmac, urllib.parse
query = urllib.parse.urlencode(params)
signature = hmac.new(exchange.secret.encode(), query.encode(), hashlib.sha256).hexdigest()
query += f'&signature={signature}'
if settings.USE_TESTNET:
    base_url = 'https://testnet.binancefuture.com'
else:
    base_url = 'https://fapi.binance.com'
```

| File | Fungsi |
|------|--------|
| `src/utils/exchange.py` | `place_algo_order()` ~L116-192 |
| `src/utils/exchange.py` | `cancel_algo_order()` ~L195-252 |

**Fix:** Extract `_sign_request(params, exchange)` dan `_get_base_url()` helper.

---

## 3. `analyst_agent.py` — LLM call + JSON parse diulang 2x

Initial call dan retry call identik:

```python
response = client.chat.completions.create(model=settings.CEREBRAS_MODEL, messages=[...], temperature=0.0, ...)
raw = response.choices[0].message.content
data = json.loads(raw)
return AnalystDecision(action=data.get('action', 'SKIP'), ...)
```

| File | Line |
|------|------|
| `src/agents/llm/analyst_agent.py` | 114-128 (initial) |
| `src/agents/llm/analyst_agent.py` | 140-155 (retry) |

**Fix:** Extract `_call_cerebras(prompt, client) -> AnalystDecision` method.

---

## 4. `cmd_get_performance` dan `cmd_get_trade_history` — mode resolution identik

Kedua fungsi punya block yang sama persis:

```python
if mode == "":
    if settings.EXECUTION_MODE != "live":
        mode = "paper"
    else:
        mode = "testnet" if settings.USE_TESTNET else "mainnet"
elif mode not in ('paper', 'testnet', 'mainnet'):
    return "Gunakan: /xxx [paper|testnet|mainnet]"
```

| File | Fungsi |
|------|--------|
| `src/telegram/commands.py` | `cmd_get_performance()` ~L183-192 |
| `src/telegram/commands.py` | `cmd_get_trade_history()` ~L213-221 |

**Fix:** Pakai `get_current_mode()` utility yang sama dengan issue HIGH #1 dan #5.

---

## 5. Session query + mode filter pattern diulang

Pola `db.query(PaperTrade).filter(status==X, execution_mode==Y)` muncul di hampir setiap file yang akses DB:

| File | Fungsi |
|------|--------|
| `src/telegram/commands.py` | `cmd_menu()`, `cmd_get_open_trades()`, `cmd_get_performance()`, `cmd_get_trade_history()` |
| `src/agents/math/sltp_manager.py` | `check_paper_trades()` |
| `src/agents/math/position_manager.py` | `check_trailing_stop()` |
| `src/agents/math/execution_agent.py` | `check_pending_orders()`, `_count_open_positions()` |
| `src/telegram/bot.py` | `_get_trade_context()` |
| `src/main.py` | `_reconcile_positions()` |

**Fix:** Query helper methods, misal `get_open_trades(mode)`, `get_closed_trades(mode)`.
