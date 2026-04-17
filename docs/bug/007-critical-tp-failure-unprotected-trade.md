# Bug #007 — CRITICAL: TP Algo Order Gagal, Trade Tanpa Proteksi

**File**: `src/agents/math/execution_agent.py:651-666` (`_handle_fill`)
**Impact**: SL berhasil dipasang tapi TP gagal → trade terbuka tanpa TP selamanya. Tidak ada retry, trade bisa rugi kalau price reverse setelah profit.

**Repro**: Live mode, SL algo order sukses, TP algo order gagal (rate limit, network error, atau Binance error). Error di-log tapi tidak ada recovery.

**Fix approach**: Kalau TP gagal setelah SL berhasil, langsung market close posisi tersebut. Lebih aman rugi sedikit (spread) daripada posisi tanpa TP terbuka indefinitely. Alternatif: retry TP placement 1-2x sebelum fallback ke market close.
