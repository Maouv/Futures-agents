"""
concierge_agent.py — Interface ngobrol.
ATURAN KHUSUS Concierge (WAJIB DIPATUHI):
- DILARANG json.loads() atau response_format JSON
- Timeout sesuai settings.CONCIERGE_TIMEOUT_SEC
- Model, API key, dan base URL dikonfigurasi via .env
"""
import openai
from src.config.settings import settings
from src.utils.logger import logger

FREYANA_SYSTEM_PROMPT = """Kamu adalah Freyana, asisten trading bot yang blunt, sarcastic, dan casual.
Gunakan bahasa Indonesia dengan gw/lu pronouns.
Kamu bisa membaca data paper trades untuk menjawab pertanyaan performa.
DILARANG mengakses API keys atau mengeksekusi perintah sistem.
Jawab singkat dan langsung ke poin."""


def run_concierge(
    user_message: str,
    trade_context: str = "",
) -> str:
    """
    Jalankan Concierge Agent. Return raw text langsung.
    """
    try:
        client = openai.OpenAI(
            api_key=settings.CONCIERGE_API_KEY.get_secret_value(),
            base_url=str(settings.CONCIERGE_BASE_URL).rstrip('/chat/completions'),
            timeout=settings.CONCIERGE_TIMEOUT_SEC,
        )

        messages = [{"role": "system", "content": FREYANA_SYSTEM_PROMPT}]

        if trade_context:
            messages.append({
                "role": "system",
                "content": f"DATA TRADING TERKINI:\n{trade_context}"
            })

        messages.append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model=settings.CONCIERGE_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=settings.CONCIERGE_MAX_TOKENS,
            # DILARANG: response_format={"type": "json_object"}
        )

        # Ambil raw text — JANGAN json.loads()
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"[ConciergeAgent] Error: {e}")
        return f"⚠️ Error: {str(e)[:100]}"
