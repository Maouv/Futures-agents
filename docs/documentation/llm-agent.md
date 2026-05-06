# LLM Agents

Read this when: working in `src/agents/llm/` or `src/utils/llm_rate_limiter.py`.

## Three Agents

```
analyst_agent.py    → Cerebras (Qwen-3-235B), temp 0.0, JSON mode
                      Provider chain → rule-based fallback → AnalystDecision
commander_agent.py  → Groq (Llama-3.1-8b-instant), temp 0.0, JSON mode
                      Parses Telegram commands → Python function name
concierge_agent.py  → Modal (GLM-5 FP8), temp 0.7, chat mode (NO JSON parsing)
                      Concurrency locked — rejects new requests while processing
```

## Provider Chain

Analyst iterates `config.json → llm.analyst_providers[]` in order.
If all providers fail → rule-based fallback. Bot must never crash when LLM is down.

```python
# source field format
"llm:cerebras"     # provider responded
"rule_based"       # all providers failed, fallback used
```

To add a new provider: append to `llm.analyst_providers[]` in `config.json`, add API key to `.env`, restart.

## Rate Limiter

All LLM calls must go through `get_provider_limiter(name)` from `llm_rate_limiter.py`.
Each provider has its own semaphore + RPM sliding window + min_interval — configured per-provider in `config.json`.

```python
from src.utils.llm_rate_limiter import get_provider_limiter

limiter = get_provider_limiter("cerebras")
async with limiter:
    response = await client.chat.completions.create(...)
```

Never call LLM APIs directly without going through the limiter.

## OpenAI SDK for All Providers

All three agents use the `openai` SDK with `base_url` override — not provider-specific SDKs:
```python
client = OpenAI(
    api_key=settings.CEREBRAS_API_KEY.get_secret_value(),
    base_url="https://api.cerebras.ai/v1",
)
```

## Concierge Rules

- Temperature 0.7, max_tokens 5000, timeout 600s
- Chat mode only — never attempt JSON parsing on response
- Concurrency lock: if already processing, reject new request immediately
- Connect via `openai` SDK + `base_url=settings.MODAL_BASE_URL` — not Modal SDK

