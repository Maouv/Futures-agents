# LLM Fallback — Implementation Plan

**Goal:** Primary (Cerebras) → Fallback → Rule-based for analyst_agent only.

**Files:** `config.json`, `.env.example`, `settings.py`, `llm_rate_limiter.py`, `analyst_agent.py`, `tests/test_llm_fallback.py`

---

### Task 1: Config (`config.json`, `.env.example`)

- [ ] Add `llm.fallback` to config.json: `base_url`, `model`, `retry_on_429: 3`, `timeout_sec: 60`, `max_tokens: 2000`
- [ ] Add `"fallback_api_key": "${FALLBACK_API_KEY}"` to `secrets`
- [ ] Add `FALLBACK_API_KEY=` to `.env.example`
- [ ] Commit

### Task 2: Settings (`settings.py`)

- [ ] Add `FALLBACK_API_KEY` field + `model_post_init` block (same pattern as CEREBRAS_API_KEY)
- [ ] Add properties: `FALLBACK_BASE_URL`, `FALLBACK_MODEL`, `FALLBACK_RETRY_ON_429`, `FALLBACK_TIMEOUT_SEC`, `FALLBACK_MAX_TOKENS` (same pattern as cerebras properties)
- [ ] Commit

### Task 3: Rate Limiter (`llm_rate_limiter.py`)

- [ ] Add `_get_fallback_limiter()` → `LLMRateLimiter(max_concurrent=1, rpm=60, min_interval=0.5)`
- [ ] Add `fallback_limiter = _LazyLimiter(_get_fallback_limiter)` at module level
- [ ] Commit

### Task 4: Analyst Agent (`analyst_agent.py`) — core change

- [ ] Add `from src.utils.llm_rate_limiter import fallback_limiter`
- [ ] Add `_validate_fallback_config()` → returns bool, logs issues. Sets `FALLBACK_AVAILABLE` at module load.
- [ ] Add `_call_fallback_llm(prompt)` → uses fallback_limiter, reads retry/timeout from config, same pattern as `_call_llm` but with config-driven retry loop
- [ ] Replace `run_analyst` retry block: primary fails → check `FALLBACK_AVAILABLE` → `_call_fallback_llm()` → `_rule_based_fallback()`
- [ ] Commit

### Task 5: Tests (`tests/test_llm_fallback.py`)

- [ ] 3 tests: fallback used when primary fails, rule-based when no fallback config, rule-based when both fail
- [ ] Run: `pytest tests/test_llm_fallback.py -v`
- [ ] Commit
