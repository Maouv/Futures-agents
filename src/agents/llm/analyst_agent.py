"""
analyst_agent.py — LLM Analyst dengan provider chain.
Providers diiterate: primary → fallback → ... → rule-based.
Config driven dari config.json llm.analyst_providers list.
"""
from pydantic import BaseModel
from typing import Optional
import json
import time
import threading
import openai
from src.config.settings import settings
from src.agents.math.trend_agent import TrendResult
from src.agents.math.reversal_agent import ReversalResult
from src.agents.math.confirmation_agent import ConfirmationResult
from src.utils.logger import logger
from src.utils.llm_rate_limiter import get_provider_limiter


class AnalystDecision(BaseModel):
    action: str             # 'LONG', 'SHORT', 'SKIP'
    confidence: int         # 0-100
    reasoning: str          # Penjelasan keputusan
    source: str             # 'llm', 'llm:<provider_name>', atau 'rule_based'


# ── Client cache (thread-safe, per provider name) ──────────────────────────

_client_cache: dict[str, openai.OpenAI] = {}
_client_lock = threading.Lock()


def _get_client(provider: dict) -> Optional[openai.OpenAI]:
    """Get or create cached OpenAI client for a provider. Returns None if misconfigured."""
    name = provider['name']
    api_key = settings.get_secret_by_key(provider.get('api_key_env', ''))
    if not api_key:
        logger.warning(f"[AnalystAgent] Provider '{name}': no API key for '{provider.get('api_key_env')}'")
        return None

    base_url = provider.get('base_url', '').rstrip('/')
    timeout = provider.get('timeout_sec', 30)

    if name not in _client_cache:
        with _client_lock:
            if name not in _client_cache:
                _client_cache[name] = openai.OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=timeout,
                )
                logger.debug(f"[AnalystAgent] Cached client for provider '{name}'")
    return _client_cache[name]


# ── Response parser ────────────────────────────────────────────────────────

def _parse_llm_response(raw: str, provider_name: str) -> AnalystDecision:
    """Parse LLM JSON response into AnalystDecision. Never raises."""
    try:
        data = json.loads(raw)
        action = data.get('action', 'SKIP').upper()
        if action not in ('LONG', 'SHORT', 'SKIP'):
            action = 'SKIP'
        confidence = int(data.get('confidence', 50))
        confidence = max(0, min(100, confidence))
        return AnalystDecision(
            action=action,
            confidence=confidence,
            reasoning=data.get('reasoning', '')[:500],
            source=f'llm:{provider_name}',
        )
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"[AnalystAgent] Failed to parse LLM response from '{provider_name}': {e}")
        return None


# ── Per-provider LLM call with retry ───────────────────────────────────────

def _is_retryable(exc: Exception) -> bool:
    """Check if error is worth retrying (429, timeout, server error)."""
    exc_str = str(exc).lower()
    if '429' in exc_str or 'rate_limit' in exc_str or 'rate limit' in exc_str:
        return True
    if hasattr(exc, 'status_code'):
        if exc.status_code in (429, 500, 502, 503, 529):
            return True
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return True
    return False


def _call_provider(provider: dict, prompt: str) -> Optional[AnalystDecision]:
    """
    Call a single provider with retry + rate limiting.
    Returns AnalystDecision on success, None on failure (so chain can continue).
    """
    name = provider['name']
    client = _get_client(provider)
    if client is None:
        return None

    limiter = get_provider_limiter(name)
    retries = provider.get('retry_on_429', 3)
    model = provider.get('model', '')
    max_tokens = provider.get('max_tokens', 200)

    for attempt in range(retries):
        limiter.acquire()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
            )
            raw = response.choices[0].message.content
            result = _parse_llm_response(raw, name)
            if result is not None:
                logger.info(f"[AnalystAgent] Provider '{name}' succeeded (action={result.action})")
                return result
            # Parse failed — not retryable, move to next provider
            logger.warning(f"[AnalystAgent] Provider '{name}' returned unparseable response")
            return None
        except Exception as e:
            retryable = _is_retryable(e)
            if retryable and attempt < retries - 1:
                backoff = 2 ** attempt
                logger.warning(
                    f"[AnalystAgent] Provider '{name}' error: {e}. "
                    f"Retry {attempt + 1}/{retries} after {backoff}s"
                )
                time.sleep(backoff)
                continue
            logger.warning(f"[AnalystAgent] Provider '{name}' failed: {e}")
            return None
        finally:
            limiter.release()

    return None


# ── Rule-based fallback (last resort) ─────────────────────────────────────

def _rule_based_fallback(
    trend: TrendResult,
    reversal: ReversalResult,
    confirmation: ConfirmationResult,
) -> AnalystDecision:
    """Deterministic fallback — no LLM needed."""
    if (trend.bias == 1
            and reversal.signal == 'LONG'
            and confirmation.confirmed):
        return AnalystDecision(
            action='LONG', confidence=70,
            reasoning='Rule-based: H4 bullish + H1 LONG signal + 15m confirmed',
            source='rule_based',
        )
    if (trend.bias == -1
            and reversal.signal == 'SHORT'
            and confirmation.confirmed):
        return AnalystDecision(
            action='SHORT', confidence=70,
            reasoning='Rule-based: H4 bearish + H1 SHORT signal + 15m confirmed',
            source='rule_based',
        )
    return AnalystDecision(
        action='SKIP', confidence=80,
        reasoning='Rule-based: No clear confluence',
        source='rule_based',
    )


# ── Main entry point ──────────────────────────────────────────────────────

def run_analyst(
    trend: TrendResult,
    reversal: ReversalResult,
    confirmation: ConfirmationResult,
    current_price: float,
    symbol: str = "BTCUSDT",
) -> AnalystDecision:
    """
    Run LLM Analyst with provider chain.
    Iterates analyst_providers in order → rule-based if all fail.
    """
    # Format pair untuk display (BTCUSDT -> BTC/USDT)
    display_pair = f"{symbol[:-4]}/{symbol[-4:]}" if symbol.endswith("USDT") else symbol

    prompt = f"""You are a professional crypto futures trader analyzing {display_pair}.

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
- Risk/Reward: 1:{settings.RISK_REWARD_RATIO}

Respond in JSON only:
{{"action": "LONG|SHORT|SKIP", "confidence": 0-100, "reasoning": "brief explanation"}}"""

    # Iterate provider chain
    providers = settings.ANALYST_PROVIDERS
    for provider in providers:
        result = _call_provider(provider, prompt)
        if result is not None:
            return result

    # All providers failed — rule-based last resort
    logger.warning("[AnalystAgent] All LLM providers failed. Using rule-based fallback.")
    return _rule_based_fallback(trend, reversal, confirmation)
