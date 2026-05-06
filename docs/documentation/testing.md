# Testing & Linting

Read this when: writing tests, running CI checks, or verifying a fix.

## Commands

Before committing:
```bash
ruff check --fix src/
ruff format src/
```

After implementing a feature or fixing a bug:
```bash
pytest tests/test_<module>.py -s
```

Full verification before pushing:
```bash
ruff check src/ && pytest
```

Type check (optional, relaxed config):
```bash
mypy src/
```

## Test Naming

```
File:   tests/test_<module_name>.py
Class:  Test<Subject>
Method: test_<what_it_verifies>
```

```python
# Example
class TestRiskAgentPositionSize:
    def test_position_size_formula_correct(self):
        ...

    def test_raises_value_error_when_risk_distance_too_small(self):
        ...
```

## Test Structure

Use `setup_method` to reset DB state before each test:
```python
def setup_method(self):
    init_db()
    with get_session() as db:
        db.query(PaperTrade).delete()
        db.commit()
```

## Ruff Rules Active

`E, F, W` — pycodestyle + pyflakes
`I` — isort (import order)
`N` — pep8-naming
`UP` — pyupgrade (Python 3.12 syntax)

Auto-fixable via `ruff check --fix`: F401 (unused imports), I (isort), UP (pyupgrade).

Intentional ignores per file:
- `tests/*` → F401, F811, F841 ignored (fixtures and mocks)
- `scripts/test_*.py` → F401, F841 ignored
- `src/indicators/_smc_core.py` → N801, N802, UP030, UP032 ignored (upstream port)
- `src/config/settings.py` → N802 ignored (SCREAMING_CASE on @property)

## Scripts vs Tests

Files in `scripts/` are manual utilities — not part of CI, do not need to pass pytest.
Only files in `tests/` are run by `pytest`.

