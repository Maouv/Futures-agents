# Design: Split Order Blocks into Internal OB and Swing OB

**Date:** 2026-04-01
**Status:** Approved for Implementation
**Phase:** Phase 2 - Smart Money Concepts Indicators

---

## Problem Statement

Current `detect_order_blocks()` implementation uses hardcoded `swing_size=5` for all Order Blocks. TradingView LuxAlgo SMC indicator separates Order Blocks into two types:

- **Internal Order Blocks**: Uses `swing_size=5` (more sensitive, shorter-term)
- **Swing Order Blocks**: Uses `swing_size=50` (less sensitive, longer-term)

Need to update implementation to detect and return both types separately to match TradingView behavior.

---

## Design Overview

### Approach: Return Tuple of Two Lists

**Option A (SELECTED):**
```python
def detect_order_blocks(df: pd.DataFrame) -> tuple[list[OrderBlock], list[OrderBlock]]:
    """Returns: (internal_obs, swing_obs)"""
    internal_obs = _detect_obs_with_size(df, swing_size=5, ob_type='internal')
    swing_obs = _detect_obs_with_size(df, swing_size=50, ob_type='swing')
    return internal_obs, swing_obs
```

**Why this approach:**
- Simple and backward-compatible-ish (still returns lists)
- Easy to unpack: `internal_obs, swing_obs = detect_order_blocks(df)`
- Consistent with existing code style (other functions return lists directly)
- No additional Pydantic models needed

---

## Technical Implementation

### 1. Update OrderBlock Model

**File:** `src/indicators/luxalgo_smc.py`

**Change:**
```python
class OrderBlock(BaseModel):
    index: int
    high: float
    low: float
    bias: int               # 1=BULLISH, -1=BEARISH
    mitigated: bool = False
    ob_type: str            # 'internal' or 'swing'  <- NEW FIELD
```

**Why:** Distinguish between Internal and Swing OB types in data model.

---

### 2. Extract Detection Logic to Helper Function

**File:** `src/indicators/luxalgo_smc.py`

**New helper function:**
```python
def _detect_obs_with_size(
    df: pd.DataFrame,
    swing_size: int,
    ob_type: str
) -> list[OrderBlock]:
    """
    Internal helper to detect Order Blocks with specific swing size.

    Args:
        df: OHLCV DataFrame
        swing_size: Lookback period for swing detection
        ob_type: 'internal' or 'swing'

    Returns:
        List of OrderBlock objects with specified ob_type
    """
    size = _adaptive_swing_size(df, preferred=swing_size)

    if len(df) < size * 2 + 1:
        return []

    parsed_high, parsed_low = _parsed_highs_lows(df)

    sh_mask = find_swing_highs(df, size=size)
    sl_mask = find_swing_lows(df, size=size)

    swing_highs = [i for i in range(len(df)) if sh_mask.iloc[i]]
    swing_lows = [i for i in range(len(df)) if sl_mask.iloc[i]]

    order_blocks: list[OrderBlock] = []

    # Bearish OB (from swing highs pairs)
    for k in range(1, len(swing_highs)):
        prev_idx = swing_highs[k - 1]
        curr_idx = swing_highs[k]

        segment = parsed_high.iloc[prev_idx:curr_idx + 1]
        if segment.empty:
            continue

        ob_pos = int(segment.idxmax())
        ob_high = float(df['high'].iloc[ob_pos])
        ob_low = float(df['low'].iloc[ob_pos])

        mitigated = bool(
            (df['close'].iloc[ob_pos + 1:] > ob_high).any()
        )

        order_blocks.append(OrderBlock(
            index=ob_pos,
            high=ob_high,
            low=ob_low,
            bias=-1,
            mitigated=mitigated,
            ob_type=ob_type,  # Set the ob_type field
        ))

    # Bullish OB (from swing lows pairs)
    for k in range(1, len(swing_lows)):
        prev_idx = swing_lows[k - 1]
        curr_idx = swing_lows[k]

        segment = parsed_low.iloc[prev_idx:curr_idx + 1]
        if segment.empty:
            continue

        ob_pos = int(segment.idxmin())
        ob_high = float(df['high'].iloc[ob_pos])
        ob_low = float(df['low'].iloc[ob_pos])

        mitigated = bool(
            (df['close'].iloc[ob_pos + 1:] < ob_low).any()
        )

        order_blocks.append(OrderBlock(
            index=ob_pos,
            high=ob_high,
            low=ob_low,
            bias=1,
            mitigated=mitigated,
            ob_type=ob_type,  # Set the ob_type field
        ))

    order_blocks.sort(key=lambda ob: ob.index)
    return order_blocks
```

---

### 3. Refactor detect_order_blocks()

**File:** `src/indicators/luxalgo_smc.py`

**Updated signature and implementation:**
```python
def detect_order_blocks(
    df: pd.DataFrame,
) -> tuple[list[OrderBlock], list[OrderBlock]]:
    """
    Detect Internal and Swing Order Blocks.

    Internal OB uses swing_size=5 (more sensitive)
    Swing OB uses swing_size=50 (less sensitive)

    Returns:
        tuple: (internal_obs, swing_obs) - Two separate lists of OrderBlock objects

    Process:
    1. Detect Internal OBs with swing_size=5
    2. Detect Swing OBs with swing_size=50
    3. Return both lists separately
    """
    internal_obs = _detect_obs_with_size(df, swing_size=5, ob_type='internal')
    swing_obs = _detect_obs_with_size(df, swing_size=50, ob_type='swing')

    return internal_obs, swing_obs
```

---

### 4. Update Callers

**File:** `scripts/validate_indicators.py`

**Before:**
```python
obs = detect_order_blocks(df)
logger.info(f"Total Order Blocks detected: {len(obs)}")

if obs:
    logger.info("=== LAST 5 ORDER BLOCKS ===")
    for ob in obs[-5:]:
        # ... display logic
```

**After:**
```python
internal_obs, swing_obs = detect_order_blocks(df)

logger.info(f"Internal Order Blocks detected: {len(internal_obs)}")
logger.info(f"Swing Order Blocks detected: {len(swing_obs)}")
logger.info("")

# Display Internal OBs
if internal_obs:
    logger.info("=== LAST 5 INTERNAL ORDER BLOCKS ===")
    for ob in internal_obs[-5:]:
        bias_str = "BULLISH" if ob.bias == 1 else "BEARISH"
        mitigated_str = "MITIGATED" if ob.mitigated else "ACTIVE"
        timestamp = df['timestamp'].iloc[ob.index] if ob.index < len(df) else "N/A"

        logger.info(f"  {bias_str} Internal OB | Index: {ob.index} | Time: {timestamp}")
        logger.info(f"    High: {ob.high:.2f} | Low: {ob.low:.2f}")
        logger.info(f"    Status: {mitigated_str}")
        logger.info("")

# Display Swing OBs
if swing_obs:
    logger.info("=== LAST 5 SWING ORDER BLOCKS ===")
    for ob in swing_obs[-5:]:
        bias_str = "BULLISH" if ob.bias == 1 else "BEARISH"
        mitigated_str = "MITIGATED" if ob.mitigated else "ACTIVE"
        timestamp = df['timestamp'].iloc[ob.index] if ob.index < len(df) else "N/A"

        logger.info(f"  {bias_str} Swing OB | Index: {ob.index} | Time: {timestamp}")
        logger.info(f"    High: {ob.high:.2f} | Low: {ob.low:.2f}")
        logger.info(f"    Status: {mitigated_str}")
        logger.info("")
```

---

### 5. Update Tests

**File:** `tests/test_indicators.py`

**Changes needed:**
1. Update existing `test_detect_order_blocks_returns_list` to handle tuple return
2. Add new tests to verify Internal vs Swing OB separation

**Example test updates:**
```python
def test_detect_order_blocks_returns_list(self):
    df = self._make_df(200)
    internal_obs, swing_obs = detect_order_blocks(df)  # Unpack tuple

    assert isinstance(internal_obs, list)
    assert isinstance(swing_obs, list)

    if internal_obs:
        assert isinstance(internal_obs[0], OrderBlock)
    if swing_obs:
        assert isinstance(swing_obs[0], OrderBlock)

def test_internal_ob_has_correct_type(self):
    df = self._make_df(200)
    internal_obs, _ = detect_order_blocks(df)

    if internal_obs:
        for ob in internal_obs:
            assert ob.ob_type == 'internal'

def test_swing_ob_has_correct_type(self):
    df = self._make_df(200)
    _, swing_obs = detect_order_blocks(df)

    if swing_obs:
        for ob in swing_obs:
            assert ob.ob_type == 'swing'
```

---

## What Does NOT Change

### ✅ Keep Unchanged (per requirements):

1. **FVG Detection** - No changes to `detect_fvg()`
2. **BOS/CHOCH Detection** - No changes to `detect_bos_choch()`
3. **Helper Functions** - No changes to helpers (`find_swing_highs`, `find_swing_lows`, etc.)
4. **Core OB Logic** - Detection algorithm remains the same, only split into two passes with different swing_size

---

## Testing Strategy

### Unit Tests
1. Verify `OrderBlock.ob_type` field exists and accepts 'internal' or 'swing'
2. Verify `detect_order_blocks()` returns tuple of two lists
3. Verify Internal OBs have `ob_type='internal'`
4. Verify Swing OBs have `ob_type='swing'`
5. Verify both types use correct swing_size (5 vs 50)

### Validation Against TradingView
Run `scripts/validate_indicators.py` and compare:
- Internal OB count and positions should match TradingView Internal OB setting (size=5)
- Swing OB count and positions should match TradingView Swing OB setting (size=50)
- Both should show correct mitigation status

---

## Success Criteria

- [ ] `OrderBlock` model has `ob_type` field
- [ ] `detect_order_blocks()` returns tuple `(internal_obs, swing_obs)`
- [ ] Internal OB uses `swing_size=5`
- [ ] Swing OB uses `swing_size=50`
- [ ] All OrderBlock objects have correct `ob_type` value
- [ ] All existing tests pass after update
- [ ] New tests for Internal vs Swing OB pass
- [ ] Manual validation matches TradingView output
- [ ] FVG and BOS/CHOCH remain unchanged

---

## Implementation Steps

1. Update `OrderBlock` model in `src/indicators/luxalgo_smc.py`
2. Create `_detect_obs_with_size()` helper function
3. Refactor `detect_order_blocks()` to call helper twice and return tuple
4. Update `scripts/validate_indicators.py` to unpack and display both OB types
5. Update tests in `tests/test_indicators.py`
6. Run pytest to verify all tests pass
7. Run manual validation script to compare with TradingView

---

## Risks and Mitigations

**Risk:** Breaking change for existing callers of `detect_order_blocks()`
**Mitigation:** This is Phase 2 development, no production code depends on this yet. Update all callers in same commit.

**Risk:** Performance impact from running OB detection twice
**Mitigation:** Acceptable for now (Phase 2 priority is correctness). Can optimize later if needed with caching or parallel processing.

**Risk:** TradingView settings might have additional filters (OB Filter=ATR, Mitigation=High/Low)
**Mitigation:** Current implementation already includes ATR volatility filter (`_parsed_highs_lows`). Mitigation logic matches TradingView (close penetrates OB boundary). This design focuses on swing_size split only.
