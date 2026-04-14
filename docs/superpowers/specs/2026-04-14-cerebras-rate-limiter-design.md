# Cerebras LLM Rate Limiter Design

**Date**: 2026-04-14
**Status**: Draft

## Problem

AnalystAgent kena 429 dari Cerebras API saat memproses multiple pairs dalam 1 cycle.
Cerebras limit: 3 req/sec, 30 req/min. Bot memproses 4 pairs sequential tanpa rate limiting —
request ke-3/ke-4 kena queue_exceeded karena in-flight requests belum selesai diproses server.

## Test Results

4 pairs (BTCUSDT, ETHUSDT, SOLUSDT, SUIUSDT) dengan model qwen-3-235b:

| Skenario                | OK  | 429 | Total  |
|-------------------------|-----|-----|--------|
| Concurrent 2 (Sem=2)    | 4/4 | 0   | 0.99s  |
| Concurrent 3 (Sem=3)    | 4/4 | 0   | 1.01s  |
| Batched 3+1 + 1s buffer | 4/4 | 0   | 2.35s  |
| Concurrent 4 (no limit) | 3/4 | 1   | 0.70s  |
| Sequential 4            | 3/4 | 1   | 2.84s  |
| Seq + 1.5s delay        | 2/4 | 2   | 9.26s  |

**Kesimpulan**: Cerebras bisa handle 2-3 concurrent requests. Lebih dari itu → 429.
Sequential + delay justru lebih buruk karena residual quota belum reset.

## Design

### 1. LLMRateLimiter (`src/utils/llm_rate_limiter.py`) — BARU

Provider-agnostic rate limiter. Menggunakan threading.Semaphore untuk mengontrol
max concurrent in-flight requests + sliding window untuk RPM limit.

```python
class LLMRateLimiter:
    """
    Rate limiter untuk LLM API calls.
    - Semaphore: mengontrol max concurrent in-flight requests
    - Sliding window: mengontrol requests per minute (RPM)
    - Thread-safe untuk digunakan dari APScheduler background thread
    """
    def __init__(self, max_concurrent: int, rpm: int):
        ...

    def acquire(self) -> None:
        """Block sampai slot tersedia (semaphore + RPM check)."""

    def release(self) -> None:
        """Release slot setelah response diterima."""

    def __enter__(self) -> None: ...   # Context manager support
    def __exit__(self) -> None: ...
```

Singleton per provider:
```python
cerebras_limiter = LLMRateLimiter(
    max_concurrent=settings.LLM_CEREBRAS_MAX_CONCURRENT,
    rpm=settings.LLM_CEREBRAS_RPM,
)
groq_limiter = LLMRateLimiter(
    max_concurrent=settings.LLM_GROQ_MAX_CONCURRENT,
    rpm=settings.LLM_GROQ_RPM,
)
```

### 2. AnalystAgent (`src/agents/llm/analyst_agent.py`) — DIUBAH

Perubahan minimal — signature `run_analyst()` TIDAK berubah:

```python
def run_analyst(trend, reversal, confirmation, current_price, symbol="BTCUSDT"):
    # ... setup client sama seperti sebelumnya ...

    try:
        cerebras_limiter.acquire()
        response = client.chat.completions.create(...)
        cerebras_limiter.release()
        # ... parse response ...
        return AnalystDecision(action=..., source='llm')

    except Exception as e:
        cerebras_limiter.release()  # Pastikan release kalau error
        if _is_429(e) and retry_count < LLM_RETRY_ON_429:
            # Exponential backoff: 1s, 2s
            time.sleep(2 ** retry_count)
            return _retry(...)  # Recursive retry, max 2x
        # Fallback rule-based
        return _rule_based_fallback(trend, reversal, confirmation)
```

Retry strategy:
```
Call Cerebras
  ├─ 200 → return result (source='llm')
  ├─ 429 → wait 1s → retry
  │   ├─ 200 → return result (source='llm')
  │   └─ 429 → wait 2s → retry
  │       ├─ 200 → return result (source='llm')
  │       └─ 429 → fallback rule-based (source='rule_based')
  └─ Other error → fallback rule-based (source='rule_based')
```

### 3. Settings (`src/config/settings.py`) — DIUBAH

3 field baru:

| Key | Type | Default | Keterangan |
|-----|------|---------|------------|
| `LLM_CEREBRAS_MAX_CONCURRENT` | int | 2 | Max in-flight requests ke Cerebras |
| `LLM_CEREBRAS_RPM` | int | 30 | Max requests per minute ke Cerebras |
| `LLM_RETRY_ON_429` | int | 2 | Max retry saat kena 429 |

Ganti provider? Tambah config `LLM_<PROVIDER>_MAX_CONCURRENT` dan `LLM_<PROVIDER>_RPM`,
buat limiter singleton baru.

### 4. main.py — DIUBAH (minimal)

Hapus throttle hack di line 127-128:
```python
# HAPUS ini:
if len(self.pairs) > 5:
    time.sleep(1.0)
```

Rate limiting sudah ditangani oleh `cerebras_limiter.acquire()` di dalam `run_analyst()`.

## File Changes Summary

| File | Action | Perubahan |
|------|--------|-----------|
| `src/utils/llm_rate_limiter.py` | BARU | LLMRateLimiter class + singleton instances |
| `src/agents/llm/analyst_agent.py` | DIUBAH | Tambah acquire/release + retry logic |
| `src/config/settings.py` | DIUBAH | 3 field baru |
| `src/main.py` | DIUBAH | Hapus throttle hack |

## Files to Read Before Implementation

Sebelum implement, baca file-file berikut untuk memahami konteks:

1. `src/agents/llm/analyst_agent.py` — kode yang akan diubah, pahami flow saat ini
2. `src/utils/rate_limiter.py` — referensi pattern rate limiter yang sudah ada (untuk Binance)
3. `src/main.py` — pahami run_trading_cycle() dan throttle hack yang akan dihapus
4. `src/config/settings.py` — tempat tambah config baru
5. `src/agents/llm/commander_agent.py` — Groq consumer, calon user groq_limiter
6. `src/agents/llm/concierge_agent.py` — Groq consumer lain, calon user groq_limiter

## Regression Checklist

Setelah implement, verify bahwa fitur baru TIDAK menyebabkan bug:

- [ ] `run_analyst()` tetap return `AnalystDecision` dengan field yang sama
- [ ] `run_analyst()` signature tidak berubah — caller di `main.py` tidak perlu diubah
- [ ] Rule-based fallback masih jalan kalau API error (bukan hanya 429)
- [ ] Bot tidak crash kalau Cerebras down total — fallback rule-based tetap bekerja
- [ ] `source` field di `AnalystDecision` benar: `'llm'` kalau berhasil, `'rule_based'` kalau fallback
- [ ] Semaphore tidak deadlock — `release()` selalu dipanggil di semua path (success, error, retry exhausted)
- [ ] Threading aman — APScheduler menjalankan `run_trading_cycle()` di background thread, semaphore harus thread-safe
- [ ] Cycle time tidak membesar drastis — limiter harus improve, bukan memperlambat
- [ ] Existing tests masih pass — jalankan `pytest tests/ -x` setelah implement
- [ ] Groq consumers (commander, concierge) tidak terpengaruh — mereka belum pakai `groq_limiter` saat ini
- [ ] Live mode masih jalan — execution agent, SL/TP, WS stream tidak terpengaruh
- [ ] Config default backwards-compatible — tanpa `.env` update, bot jalan dengan default values

## Tidak Berubah

- `run_analyst()` signature dan return type (AnalystDecision)
- Rule-based fallback logic
- Math agents pipeline
- SLTP manager
- Telegram bot
- Exchange / Binance rate limiter
- Execution agent
