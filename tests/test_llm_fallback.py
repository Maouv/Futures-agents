# tests/test_llm_fallback.py
from unittest.mock import MagicMock, patch

import pytest

from src.agents.llm.analyst_agent import AnalystDecision, run_analyst


@pytest.fixture
def inputs():
    trend = MagicMock()
    trend.bias_label = "Bullish"
    trend.confidence = 0.8

    reversal = MagicMock()
    reversal.signal = "LONG"
    reversal.confidence = 80

    confirmation = MagicMock()
    confirmation.confirmed = True
    confirmation.fvg_confluence = True
    confirmation.bos_alignment = True

    return trend, reversal, confirmation, 50000.0, "BTCUSDT"

@patch('src.agents.llm.analyst_agent._call_llm_provider')
@patch('src.agents.llm.analyst_agent.settings')
def test_primary_succeeds(mock_settings, mock_call, inputs):
    mock_settings.CEREBRAS_API_KEY = "fake_key"
    mock_settings.RISK_REWARD_RATIO = 1.0
    mock_call.return_value = AnalystDecision(action="LONG", confidence=90,
reasoning="test", source="llm")

    result = run_analyst(*inputs)
    assert result.source == "llm"
    assert result.action == "LONG"
    mock_call.assert_called_once_with("cerebras", pytest.approx("")) # arg 2 is prompt

@patch('src.agents.llm.analyst_agent._call_llm_provider')
@patch('src.agents.llm.analyst_agent.settings')
def test_fallback_used_when_primary_fails(mock_settings, mock_call, inputs):
    mock_settings.CEREBRAS_API_KEY = "fake_key"
    mock_settings.FALLBACK_API_KEY = "fake_key"  # <-- FIXED: was on same line
    mock_settings.RISK_REWARD_RATIO = 1.0

    # Primary gagal, Fallback sukses
    mock_call.side_effect = [
        Exception("Primary down"),
        AnalystDecision(action="SHORT", confidence=80, reasoning="fb ok", source="llm")
    ]

    result = run_analyst(*inputs)
    assert result.source == "llm"
    assert result.action == "SHORT"
    assert mock_call.call_count == 2

@patch('src.agents.llm.analyst_agent._call_llm_provider')
@patch('src.agents.llm.analyst_agent.settings')
def test_rule_based_when_all_fail(mock_settings, mock_call, inputs):
    mock_settings.CEREBRAS_API_KEY = "fake_key"
    mock_settings.FALLBACK_API_KEY = "fake_key"
    mock_settings.RISK_REWARD_RATIO = 1.0

    # Keduanya gagal
    mock_call.side_effect = Exception("All down")

    result = run_analyst(*inputs)
    assert result.source == "rule_based"
