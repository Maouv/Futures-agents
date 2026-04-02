"""
analyst_agent.py — LLM Analyst menggunakan Cerebras Qwen-3-235B.
Menerima output Math Agents, mengambil keputusan final LONG/SHORT/SKIP.
WAJIB ada fallback ke rule-based jika API down.
"""
from pydantic import BaseModel
from typing import Optional
import json
import openai
from src.config.settings import settings
from src.agents.math.trend_agent import TrendResult
from src.agents.math.reversal_agent import ReversalResult
from src.agents.math.confirmation_agent import ConfirmationResult
from src.utils.logger import logger


class AnalystDecision(BaseModel):
    action: str             # 'LONG', 'SHORT', 'SKIP'
    confidence: int         # 0-100
    reasoning: str          # Penjelasan keputusan
    source: str             # 'llm' atau 'rule_based' (fallback)


def _rule_based_fallback(
    trend: TrendResult,
    reversal: ReversalResult,
    confirmation: ConfirmationResult,
) -> AnalystDecision:
    """
    Fallback logic jika Cerebras API down.
    Logika sederhana berdasarkan confluence Math Agents.
    """
    # LONG jika semua aligned bullish
    if (trend.bias == 1
            and reversal.signal == 'LONG'
            and confirmation.confirmed):
        return AnalystDecision(
            action='LONG',
            confidence=70,
            reasoning='Rule-based: H4 bullish + H1 LONG signal + 15m confirmed',
            source='rule_based',
        )
    # SHORT jika semua aligned bearish
    if (trend.bias == -1
            and reversal.signal == 'SHORT'
            and confirmation.confirmed):
        return AnalystDecision(
            action='SHORT',
            confidence=70,
            reasoning='Rule-based: H4 bearish + H1 SHORT signal + 15m confirmed',
            source='rule_based',
        )
    return AnalystDecision(
        action='SKIP',
        confidence=80,
        reasoning='Rule-based: No clear confluence',
        source='rule_based',
    )


def run_analyst(
    trend: TrendResult,
    reversal: ReversalResult,
    confirmation: ConfirmationResult,
    current_price: float,
) -> AnalystDecision:
    """
    Jalankan LLM Analyst. Fallback ke rule-based jika API down.
    """
    client = openai.OpenAI(
        api_key=settings.CEREBRAS_API_KEY.get_secret_value(),
        base_url=str(settings.CEREBRAS_BASE_URL).rstrip('/chat/completions'),
        timeout=settings.LLM_FAST_TIMEOUT_SEC,
    )

    prompt = f"""You are a professional crypto futures trader analyzing BTC/USDT.

MARKET DATA:
- Current Price: ${current_price:,.2f}
- H4 Trend: {trend.bias_label} (confidence: {trend.confidence:.0%})
- H1 Signal: {reversal.signal} (confidence: {reversal.confidence}/100)
- 15m Confirmation: {'CONFIRMED' if confirmation.confirmed else 'NOT CONFIRMED'}
- FVG Confluence: {'YES' if confirmation.fvg_confluence else 'NO'}
- BOS Alignment: {'YES' if confirmation.bos_alignment else 'NO'}

STRATEGY RULES:
- Only trade when H4 trend aligns with H1 signal
- Entry at 50% of Order Block (midpoint)
- Risk/Reward: 1:2.5

Respond in JSON only:
{{"action": "LONG|SHORT|SKIP", "confidence": 0-100, "reasoning": "brief explanation"}}"""

    try:
        response = client.chat.completions.create(
            model=settings.CEREBRAS_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=200,
        )
        raw = response.choices[0].message.content
        data = json.loads(raw)
        return AnalystDecision(
            action=data.get('action', 'SKIP'),
            confidence=int(data.get('confidence', 50)),
            reasoning=data.get('reasoning', ''),
            source='llm',
        )
    except Exception as e:
        logger.warning(f"[AnalystAgent] API error: {e}. Falling back to rule-based.")
        return _rule_based_fallback(trend, reversal, confirmation)
