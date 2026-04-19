# LLM Fallback System — Design Spec

**Date:** 2026-04-19
**Goal:** Single fallback LLM provider for analyst_agent. Primary (Cerebras) → Fallback → Rule-based.

---

## Config Changes

**config.json — add `llm.fallback`:**
```json
"llm": {
  "cerebras": { ... existing ... },
  "fallback": {
    "base_url": "https://api.openai.com/v1/chat/completions",
    "model": "gpt-4o",
    "retry_on_429": 3,
    "timeout_sec": 60,
    "max_tokens": 2000
  },
  "groq": { ... },
  "concierge": { ... }
}
```

**config.json — add to `secrets`:**
```json
"fallback_api_key": "${FALLBACK_API_KEY}"
```

**.env:**
```
FALLBACK_API_KEY=sk-xxx
```

---

## Files Changed

| File | Change |
|------|--------|
| `config.json` | Add `llm.fallback` + `secrets.fallback_api_key` |
| `.env.example` | Add `FALLBACK_API_KEY=` |
| `src/agents/llm/analyst_agent.py` | Add validation, fallback call, modified flow |
| `src/utils/llm_rate_limiter.py` | Add `fallback_limiter` |

---

## analyst_agent.py — Modified Flow

```python
def run_analyst():
    # Primary (Cerebras) — existing retry logic
    try:
        return call_primary_llm()
    except LLMError:
        logging.warning("[AnalystAgent] Primary LLM failed after all retries")

    # Skip fallback if not configured
    if not FALLBACK_AVAILABLE:
        return rule_based_decision()

    # Fallback
    try:
        result = call_fallback_llm()
        logging.info("[AnalystAgent] Fallback LLM succeeded")
        return result
    except LLMError:
        logging.warning("[AnalystAgent] Fallback also failed")

    # Last resort
    return rule_based_decision()
```

---

## analyst_agent.py — New Functions

```python
def validate_fallback_config():
    """Run at startup. Sets global FALLBACK_AVAILABLE flag."""
    fallback_cfg = settings.config.llm.get("fallback")
    if not fallback_cfg:
        return False, "llm.fallback section missing"
    if not settings.fallback_api_key:
        return False, "FALLBACK_API_KEY not set in .env"
    if not fallback_cfg.get("base_url") or not fallback_cfg.get("model"):
        return False, "fallback base_url or model missing"
    return True, "OK"


def call_fallback_llm():
    """Retry logic mirrors primary — no hardcoded values, reads from config."""
    cfg = settings.config.llm["fallback"]
    retry_count = cfg.get("retry_on_429", 3)
    timeout = cfg.get("timeout_sec", 60)

    for attempt in range(retry_count):
        try:
            client = openai.OpenAI(
                api_key=settings.fallback_api_key,
                base_url=cfg["base_url"].rstrip("/chat/completions")
            )
            response = client.chat.completions.create(
                model=cfg["model"],
                messages=[...],
                timeout=timeout,
                max_tokens=cfg.get("max_tokens", 2000)
            )
            return parse_llm_response(response)  # standardized parser, try-except wrapped

        except openai.RateLimitError:
            wait = 2 ** attempt
            logging.warning(f"[FallbackLLM] 429. Retry {attempt+1}/{retry_count} after {wait}s")
            time.sleep(wait)

        except (openai.APITimeoutError, requests.Timeout):
            logging.warning(f"[FallbackLLM] Timeout attempt {attempt+1}/{retry_count}")

        except Exception as e:
            logging.error(f"[FallbackLLM] API error: {e}")
            break

    raise LLMError("Fallback LLM failed after all retries")
```

---

## llm_rate_limiter.py — New Limiter

```python
fallback_limiter = LLMSemaphoreLimiter(
    name="fallback",
    max_concurrent=1,
    rpm=60,
    min_interval=0.5
)
```

---

## Timeout Budget

```
Primary: 3 × 45s = 135s (2.25 min)
Fallback: 3 × 60s = 180s (3 min)
Total worst case: 5.25 min < 15 min cycle ✅
```

---

## Premortem Mitigations

| Risk | Mitigation |
|------|-----------|
| Fallback also rate-limited (likely) | Exponential backoff + monitoring logs |
| Config incomplete | Startup validation → skip gracefully, no crash |
| Response format mismatch | `parse_llm_response()` wrapped in try-except |
| Timeout hang | Enforced `timeout_sec` from config, total < cycle time |
| Stale config | Documented: "config change → restart required" |

---

## Requirements

- Fallback endpoint MUST be **OpenAI-compatible** (chat completions format)
- Config changes require **bot restart** (same as mode switch pattern)
- Missing/incomplete fallback → skip to rule-based, **no crash**

---

## What Does NOT Change

- commander_agent, concierge_agent (unchanged)
- config_loader (auto-handles new section)
- Other agents, other files (untouched)
