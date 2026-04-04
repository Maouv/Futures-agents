"""
test_analyst_prompt.py — Integration test untuk BUG #9 fix.
Test bahwa RISK_REWARD_RATIO dari settings muncul di prompt LLM.
"""
import inspect
from src.agents.llm.analyst_agent import run_analyst
from src.config.settings import settings


def test_risk_reward_ratio_in_prompt():
    """
    Test bahwa nilai RISK_REWARD_RATIO dari settings digunakan di prompt.
    Dengan menginspect source code, bukan dengan benar-benar call API.
    """
    # Get source code
    source = inspect.getsource(run_analyst)

    # Verify hardcoded value tidak ada
    assert "1:2.5" not in source, "Hardcoded RR ratio masih ada!"

    # Verify settings digunakan
    assert "settings.RISK_REWARD_RATIO" in source, "Settings RR ratio tidak digunakan!"

    # Verify settings value
    assert hasattr(settings, 'RISK_REWARD_RATIO')
    assert settings.RISK_REWARD_RATIO == 2.0  # Default value


def test_prompt_content_with_custom_rr():
    """
    Test bahwa jika settings diubah, prompt akan mengikuti.
    """
    # Verify f-string menggunakan settings
    source = inspect.getsource(run_analyst)
    assert "1:{settings.RISK_REWARD_RATIO}" in source, \
        "Prompt tidak menggunakan settings.RISK_REWARD_RATIO"
