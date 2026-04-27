"""
test_cerebras_concurrency.py — Test apakah Cerebras bisa handle concurrent requests.

Jalankan: source venv/bin/activate && python scripts/test_cerebras_concurrency.py

Test matrix:
1. Sequential 4 calls (baseline) — harusnya semua 200
2. Concurrent 2 calls — apakah bisa tanpa 429?
3. Concurrent 3 calls — test batas 3 req/sec
4. Concurrent 4 calls — kemungkinan besar kena 429
"""
import asyncio
import time
import json
from datetime import datetime

from src.config.settings import settings


# ── Helper ──────────────────────────────────────────────────────────────────

async def call_cerebras(pair: str, semaphore: asyncio.Semaphore | None = None) -> dict:
    """
    Kirim 1 request ke Cerebras. Return dict: pair, status, latency, error.
    """
    import openai

    client = openai.AsyncOpenAI(
        api_key=settings.CEREBRAS_API_KEY.get_secret_value(),
        base_url=str(settings.CEREBRAS_BASE_URL).replace('/chat/completions', ''),
        timeout=30,
    )

    prompt = f"""You are a crypto analyst. Analyze {pair} briefly.
Respond in JSON only: {{"action": "LONG|SHORT|SKIP", "confidence": 0-100, "reasoning": "brief"}}"""

    start = time.monotonic()
    result = {"pair": pair, "status": None, "latency_ms": None, "error": None}

    try:
        if semaphore:
            async with semaphore:
                response = await client.chat.completions.create(
                    model=settings.CEREBRAS_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                    max_tokens=100,
                )
        else:
            response = await client.chat.completions.create(
                model=settings.CEREBRAS_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=100,
            )

        elapsed = (time.monotonic() - start) * 1000
        raw = response.choices[0].message.content
        data = json.loads(raw)

        result["status"] = 200
        result["latency_ms"] = round(elapsed)
        result["action"] = data.get("action", "?")

    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        error_str = str(e)
        result["status"] = 429 if "429" in error_str or "too_many_requests" in error_str else "error"
        result["latency_ms"] = round(elapsed)
        result["error"] = error_str[:120]

    finally:
        await client.close()

    return result


def print_results(label: str, results: list[dict], total_sec: float):
    """Print hasil test dalam format tabel."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Total time: {total_sec:.2f}s")
    print(f"{'='*60}")
    print(f"  {'Pair':<12} {'Status':<8} {'Latency':>10} {'Action':<8} {'Error'}")
    print(f"  {'-'*12} {'-'*8} {'-'*10} {'-'*8} {'-'*30}")

    ok = 0
    rate_limited = 0
    for r in results:
        status_str = str(r["status"])
        latency = f"{r['latency_ms']:.0f}ms" if r["latency_ms"] else "-"
        action = r.get("action", "-")
        error = r.get("error", "")[:30] if r.get("error") else ""

        if r["status"] == 200:
            ok += 1
        elif r["status"] == 429:
            rate_limited += 1

        print(f"  {r['pair']:<12} {status_str:<8} {latency:>10} {action:<8} {error}")

    print(f"\n  Result: {ok} OK, {rate_limited} rate-limited, {len(results)-ok-rate_limited} other errors")
    verdict = "PASS" if rate_limited == 0 and ok == len(results) else "FAIL"
    print(f"  Verdict: {verdict}")


# ── Tests ───────────────────────────────────────────────────────────────────

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "SUIUSDT"]


async def test_sequential():
    """Test 1: Sequential 4 calls — baseline."""
    print("\n[TEST 1] Sequential 4 calls (baseline)")
    start = time.monotonic()
    results = []
    for pair in PAIRS:
        r = await call_cerebras(pair)
        results.append(r)
        print(f"  {pair} done ({r['latency_ms']:.0f}ms)")
    total = time.monotonic() - start
    print_results("Sequential 4 calls", results, total)
    return results


async def test_concurrent_2():
    """Test 2: Concurrent 2 calls — apakah Cerebras bisa handle 2 sekaligus?"""
    print("\n[TEST 2] Concurrent 2 calls (Semaphore=2)")
    sem = asyncio.Semaphore(2)
    start = time.monotonic()
    tasks = [call_cerebras(pair, sem) for pair in PAIRS]
    results = await asyncio.gather(*tasks)
    total = time.monotonic() - start
    print_results("Concurrent 2 (Semaphore=2)", list(results), total)
    return list(results)


async def test_concurrent_3():
    """Test 3: Concurrent 3 calls — test batas 3 req/sec."""
    print("\n[TEST 3] Concurrent 3 calls (Semaphore=3)")
    sem = asyncio.Semaphore(3)
    start = time.monotonic()
    tasks = [call_cerebras(pair, sem) for pair in PAIRS]
    results = await asyncio.gather(*tasks)
    total = time.monotonic() - start
    print_results("Concurrent 3 (Semaphore=3)", list(results), total)
    return list(results)


async def test_concurrent_4():
    """Test 4: Concurrent 4 calls — kemungkinan besar kena 429."""
    print("\n[TEST 4] Concurrent 4 calls (no semaphore)")
    start = time.monotonic()
    tasks = [call_cerebras(pair) for pair in PAIRS]
    results = await asyncio.gather(*tasks)
    total = time.monotonic() - start
    print_results("Concurrent 4 (no limit)", list(results), total)
    return list(results)


async def test_batched_with_delay():
    """Test 5: Batch 3 + delay + sisa. Kirim 3 bersamaan, tunggu selesai + 1s buffer, lalu kirim 1 lagi."""
    print("\n[TEST 5] Batched: 3 concurrent + 1s buffer + 1 more")
    start = time.monotonic()
    sem = asyncio.Semaphore(3)

    # Batch 1: 3 pairs concurrent
    batch1_tasks = [call_cerebras(p, sem) for p in PAIRS[:3]]
    batch1 = await asyncio.gather(*batch1_tasks)
    print(f"  Batch 1 done ({len(batch1)} calls)")

    # Buffer 1 detik supaya rate limit window reset
    await asyncio.sleep(1.0)

    # Batch 2: 1 pair
    batch2 = [await call_cerebras(PAIRS[3], sem)]
    print("  Batch 2 done (1 call)")

    total = time.monotonic() - start
    results = list(batch1) + batch2
    print_results("Batched 3+1 (1s buffer)", results, total)
    return results


async def test_sequential_delayed():
    """Test 6: Sequential dengan 1.5s delay antar call — simulasi rate limiter."""
    print("\n[TEST 6] Sequential + 1.5s delay between calls")
    start = time.monotonic()
    results = []
    for pair in PAIRS:
        r = await call_cerebras(pair)
        results.append(r)
        print(f"  {pair} done ({r['latency_ms']:.0f}ms) — sleeping 1.5s")
        await asyncio.sleep(1.5)
    total = time.monotonic() - start
    print_results("Sequential + 1.5s delay", results, total)
    return results


async def main():
    print("=" * 60)
    print("  Cerebras Concurrency Test v2")
    print(f"  Model: {settings.CEREBRAS_MODEL}")
    print(f"  Time: {datetime.now().isoformat()}")
    print(f"  Pairs: {', '.join(PAIRS)}")
    print("=" * 60)

    # Test 1: Sequential baseline
    r1 = await test_sequential()

    print("\nWaiting 15s before next test...")
    await asyncio.sleep(15)

    # Test 2: Concurrent 2
    r2 = await test_concurrent_2()

    print("\nWaiting 15s before next test...")
    await asyncio.sleep(15)

    # Test 3: Concurrent 3
    r3 = await test_concurrent_3()

    print("\nWaiting 15s before next test...")
    await asyncio.sleep(15)

    # Test 4: Concurrent 4
    r4 = await test_concurrent_4()

    print("\nWaiting 15s before next test...")
    await asyncio.sleep(15)

    # Test 5: Batched with delay
    r5 = await test_batched_with_delay()

    print("\nWaiting 15s before next test...")
    await asyncio.sleep(15)

    # Test 6: Sequential with delay
    r6 = await test_sequential_delayed()

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)

    tests = [
        ("Sequential 4", r1),
        ("Concurrent 2", r2),
        ("Concurrent 3", r3),
        ("Concurrent 4", r4),
        ("Batched 3+1", r5),
        ("Seq + 1.5s delay", r6),
    ]

    for name, results in tests:
        ok = sum(1 for r in results if r["status"] == 200)
        rl = sum(1 for r in results if r["status"] == 429)
        avg_lat = sum(r["latency_ms"] for r in results if r["latency_ms"]) / max(len(results), 1)
        print(f"  {name:<18} → {ok} OK, {rl} rate-limited | avg {avg_lat:.0f}ms")

    print("\n  Rekomendasi:")
    best = "Sequential"
    for name, results in tests:
        if sum(1 for r in results if r["status"] == 429) == 0:
            best = name
    print(f"  → {best}")


if __name__ == "__main__":
    asyncio.run(main())
