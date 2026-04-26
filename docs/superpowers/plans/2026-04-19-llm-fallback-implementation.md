# LLM Provider Chain — Implementation Plan

**Goal:** Config-driven provider chain for analyst_agent. `llm.analyst_providers` list → rule-based fallback.

**Status:** ✅ Implemented

---

### Task 1: Config (`config.json`)

- [x] Add `llm.analyst_providers` ordered list with per-provider config
- [x] Add `"fallback_api_key": "${FALLBACK_API_KEY}"` to `secrets`

### Task 2: Settings (`settings.py`)

- [x] Add `FALLBACK_API_KEY` field + `model_post_init` resolution
- [x] Add `ANALYST_PROVIDERS` property (reads from config)
- [x] Add `get_secret_by_key()` helper for dynamic API key resolution

### Task 3: Rate Limiter (`llm_rate_limiter.py`)

- [x] Add `get_provider_limiter(name)` dynamic registry
- [x] Reads RPM/min_interval/max_concurrent from provider config

### Task 4: Analyst Agent (`analyst_agent.py`) — core rewrite

- [x] Provider chain iteration: tries each provider in order
- [x] Cached OpenAI clients per provider (thread-safe)
- [x] `_parse_llm_response()` — never raises, returns None on parse failure
- [x] `_call_provider()` — retry with exponential backoff, rate limiter per provider
- [x] `_is_retryable()` — handles 429, 5xx, timeout, connection errors
- [x] Source tracing: `llm:<provider_name>` in AnalystDecision

### Task 5: Docs & CLAUDE.md

- [x] Updated spec doc
- [x] Updated implementation plan
- [x] Updated CLAUDE.md (architecture, conventions, gotchas)
