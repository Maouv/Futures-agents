"""
commander_agent.py — Menerjemahkan perintah Telegram user ke fungsi Python.
Input: string pesan user
Output: CommanderResult dengan function_name yang bisa dieksekusi
"""
import json

import openai
from pydantic import BaseModel

from src.config.settings import settings
from src.utils.logger import logger


class CommanderResult(BaseModel):
    function_name: str      # Nama fungsi yang harus dieksekusi
    params: dict            # Parameter fungsi
    confidence: int         # 0-100
    original_message: str   # Pesan asli dari user


# Daftar fungsi yang diizinkan — JANGAN tambah tanpa review
# HARUS sync dengan COMMAND_HANDLERS di src/telegram/commands.py
ALLOWED_FUNCTIONS = [
    'get_status',               # Lihat status bot
    'get_open_trades',          # Lihat trades yang open
    'get_trade_history',        # Lihat history trades
    'get_performance',          # Lihat performa (win rate, PnL)
    'activate_kill_switch',     # Kill switch ON
    'deactivate_kill_switch',   # Kill switch OFF (resume)
    'show_menu',                # Tampilkan menu
    'switch_mode',              # Switch paper/testnet/mainnet
    'unknown',                  # Perintah tidak dikenali
]


def run_commander(user_message: str) -> CommanderResult:
    client = openai.OpenAI(
        api_key=settings.GROQ_API_KEY.get_secret_value(),
        base_url=str(settings.GROQ_BASE_URL).replace('/chat/completions', ''),
        timeout=settings.LLM_FAST_TIMEOUT_SEC,
    )

    prompt = f"""You are a trading bot command interpreter.
Map user messages to function names from this list ONLY:
{json.dumps(ALLOWED_FUNCTIONS)}

User message: "{user_message}"

Respond in JSON only:
{{"function_name": "function_from_list", "params": {{}}, "confidence": 0-100}}"""

    try:
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=100,
        )
        raw = response.choices[0].message.content
        data = json.loads(raw)
        fn = data.get('function_name', 'unknown')
        if fn not in ALLOWED_FUNCTIONS:
            fn = 'unknown'
        return CommanderResult(
            function_name=fn,
            params=data.get('params', {}),
            confidence=int(data.get('confidence', 50)),
            original_message=user_message,
        )
    except Exception as e:
        logger.error(f"[CommanderAgent] Error: {e}")
        return CommanderResult(
            function_name='unknown',
            params={},
            confidence=0,
            original_message=user_message,
        )
