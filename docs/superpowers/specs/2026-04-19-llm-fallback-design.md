# LLM Provider Chain — Design Spec

**Date:** 2026-04-19
**Status:** Implemented
**Goal:** Config-driven provider chain for analyst_agent. Iterates `llm.analyst_providers` list → rule-based fallback.

---

## Architecture

Instead of hardcoded "primary → fallback", providers are defined as an ordered list in `config.json`:

```
analyst_providers: [cerebras, fallback_openai, ...]
                         ↓           ↓
                   provider 1    provider 2  → ... → rule_based
```

Each provider is tried in order. If one fails (429, timeout, parse error, no API key), the next is tried.

---

## Config

```json
"llm": {
  "analyst_providers": [
    {
      "name": "cerebras",
      "api_key_env": "cerebras_api_key",
      "base_url": "https://api.cerebras.ai/v1",
      "model": "qwen-3-235b-a22b-instruct-2507",
      "rpm": 30, "min_interval": 3.0, "max_concurrent": 1,
      "retry_on_429": 3, "timeout_sec": 30, "max_tokens": 200
    },
    {
      "name": "fallback_openai",
      "api_key_env": "fallback_api_key",
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-4o-mini",
      "rpm": 60, "min_interval": 0.5, "max_concurrent": 1,
      "retry_on_429": 3, "timeout_sec": 45, "max_tokens": 200
    }
  ]
}
```

---

## Files Changed

| File | Change |
|------|--------|
| `config.json` | Add `llm.analyst_providers` list + `secrets.fallback_api_key` |
| `src/config/settings.py` | Add `FALLBACK_API_KEY` + `ANALYST_PROVIDERS` property + `get_secret_by_key()` |
| `src/agents/llm/analyst_agent.py` | Full rewrite: provider chain with cached clients, dynamic rate limiters |
| `src/utils/llm_rate_limiter.py` | Add `get_provider_limiter()` dynamic registry |
| `CLAUDE.md` | Updated architecture, conventions, gotchas |

---

## Key Design Decisions

1. **Config-driven chain**: Add/remove providers by editing `config.json` — no code change needed
2. **Dynamic rate limiters**: Each provider gets its own `LLMRateLimiter` from its config values
3. **Client caching**: OpenAI clients cached per provider name (thread-safe) — avoids re-creating per call
4. **Runtime validation**: Missing API key → provider skipped with warning, no crash
5. **Source tracing**: `AnalystDecision.source` = `llm:<provider_name>` or `rule_based`
6. **Retryable errors**: 429, 500, 502, 503, 529, timeout, connection error → retry within provider
7. **Non-retryable**: Parse failure → skip to next provider immediately

---

## Timeout Budget

```
Provider 1 (cerebras): 3 × 30s = 90s
Provider 2 (fallback): 3 × 45s = 135s
Total worst case: 225s (3.75 min) < 15 min cycle ✅
```
