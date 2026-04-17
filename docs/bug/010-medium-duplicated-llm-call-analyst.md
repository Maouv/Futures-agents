# Bug #010 — MEDIUM: Duplicated LLM Call Code di Analyst Agent

**File**: `src/agents/llm/analyst_agent.py:111-165`
**Impact**: Block `client.chat.completions.create(...)` + JSON parse + `AnalystDecision(...)` diduplikasi verbatim antara initial try (lines 113-120) dan retry loop (lines 138-146). Kalau satu diupdate tapi satunya tidak → diverge behavior.

**Fix approach**: Extract ke helper function:
```python
def _call_llm(client, model, messages, temperature) -> AnalystDecision:
    resp = client.chat.completions.create(...)
    data = json.loads(resp.choices[0].message.content)
    return AnalystDecision(...)
```
Lalu panggil `_call_llm()` di initial try dan di retry loop. DRY, single point of change.
