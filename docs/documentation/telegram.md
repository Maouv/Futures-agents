# Telegram Bot

Read this when: working in `src/telegram/` or `src/agents/llm/commander_agent.py` / `concierge_agent.py`.

## Architecture

```
bot.py → handle_message()
  ├── is_command? → run_commander(message) → _execute_command(result)
  └── else        → run_concierge(message, trade_context)
```

Bot only processes messages from `settings.TELEGRAM_CHAT_ID` — all others silently ignored.

## Command Detection

A message is treated as a command if:
- Starts with `/`
- Or contains any keyword: `status`, `trades`, `history`, `performance`, `kill`, `resume`, `mode`, `menu`, `stats`, `trade`

## CommanderAgent

- Model: Groq `llama-3.1-8b-instant`, temp 0.0, JSON mode
- Input: raw message string
- Output: `CommanderResult` with `function_name: str` + `params: dict`
- `_execute_command()` dispatches to the matching Python function in `bot.py`

Adding a new command:
1. Add handler function in `bot.py`
2. Add function name to commander system prompt
3. Add dispatch case in `_execute_command()`

## ConciergeAgent

- Model: Modal GLM-5 FP8, temp 0.7, max_tokens 5000, timeout 600s
- Chat mode only — no JSON parsing on response
- Concurrency locked: if already processing, rejects new request immediately
- Receives `trade_context` (open positions, recent trades) as part of prompt

## Security

Only `settings.TELEGRAM_CHAT_ID` is authorized — checked in `handle_message()` before any processing.
Never expose API keys or secrets in bot responses.

