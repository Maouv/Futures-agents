"""
concierge_agent.py — Interface ngobrol.
ATURAN KHUSUS GLM-5 (WAJIB DIPATUHI):
- DILARANG json.loads() atau response_format JSON
- DILARANG queue atau parallel request
- Timeout 600 detik (GLM-5 sangat lambat)
- Concurrency lock: tolak pesan baru jika sedang proses
"""
import threading
import openai
from src.config.settings import settings
from src.utils.logger import logger


# Concurrency lock — hanya 1 request ke GLM-5 dalam satu waktu
_glm5_lock = threading.Lock()
_glm5_busy = False

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
    Jalankan GLM-5 Concierge. Return raw text langsung.
    Jika sedang busy, return pesan tunggu.
    """
    global _glm5_busy

    # Cek apakah sedang proses request lain
    if _glm5_busy:
        return "⏳ Sabar, masih mikir... coba lagi sebentar."

    if not _glm5_lock.acquire(blocking=False):
        return "⏳ Sabar, masih mikir... coba lagi sebentar."

    _glm5_busy = True
    try:
        client = openai.OpenAI(
            api_key=settings.MODAL_TOKEN.get_secret_value(),
            base_url=str(settings.MODAL_BASE_URL).rstrip('/chat/completions'),
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
            model=settings.MODAL_MODEL,
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
    finally:
        _glm5_busy = False
        _glm5_lock.release()
