Guide to test, Lint check, format, and type check.

# Activate venv first — always
source venv/bin/activate

# Run all tests
pytest

# Run a specific module
pytest tests/test_risk_agent.py
pytest tests/test_sltp_manager.py
pytest tests/test_llm_fallback.py

# Run with output (useful for debugging)
pytest tests/test_risk_agent.py -s

# Lint check
ruff check src/

# Auto-fix safe issues (unused imports, isort, pyupgrade)
ruff check --fix src/

# Format
ruff format src/

# Type check
mypy src/

Test file naming — tests/test_<module_name>.py. Test classes use Test<Subject>, methods use test_<what_it_tests>.
Scripts in scripts/ are manual utilities — they are not part of CI and do not need to pass pytest.
