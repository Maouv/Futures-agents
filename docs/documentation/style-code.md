# Style & Code Conventions

Read this when: writing new code, reviewing code, or unsure about conventions.

## Agent Pattern

Every math agent must:
- Live in `src/agents/math/`
- Extend `BaseAgent` from `src/agents/math/base_agent.py`
- Implement `run() → XxxResult` where `XxxResult` is a Pydantic `BaseModel`
- Never return a raw `dict`
- Never make LLM calls

```python
# Correct pattern
class RiskAgent(BaseAgent):
    def run(self, ...) -> RiskResult:
        ...
        return RiskResult(entry_price=..., sl_price=..., ...)

# Wrong
class RiskAgent(BaseAgent):
    def run(self, ...) -> dict:
        return {"entry_price": ..., "sl_price": ...}
```

## Result Models

```
TrendResult:        bias: int (-1/0/1), bias_label: str, confidence: float, reason: str
ReversalResult:     signal: str (LONG/SHORT/NONE), confidence: int, entry_price: float, reason: str
ConfirmationResult: confirmed: bool, reason: str, fvg_confluence: bool, bos_alignment: bool
RiskResult:         entry_price, sl_price, tp_price, position_size, rr_ratio, leverage, margin_required
ExecutionResult:    action: str (OPEN/SKIP/PENDING), reason: str, trade_id: int | None
AnalystDecision:    action: str (LONG/SHORT/SKIP), confidence: int, reasoning: str, source: str
```

## Intentional Exceptions

`src/indicators/_smc_core.py` — upstream port of LuxAlgo. Do not touch naming or style.
`src/config/settings.py` — SCREAMING_CASE on `@property` is intentional (N802 ignored).

## SQLAlchemy

```python
# Correct — SQLAlchemy 2.0 style
class PaperTrade(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pair: Mapped[str] = mapped_column(String(20), nullable=False)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)

# Wrong — legacy 1.x style
class PaperTrade(Base):
    id = Column(Integer, primary_key=True)
    pair = Column(String(20), nullable=False)
```

## How to Add Things

| Task | Action |
|---|---|
| New math agent | `src/agents/math/`, extend `BaseAgent`, return Pydantic model, register in `main.py` |
| New indicator | `src/indicators/`, call from math agent only — never from LLM layer |
| New test | `tests/test_<module>.py`, class `Test<Subject>`, method `test_<behavior>` |

