"""Self-check for wayfinder/strategy.py — the core decision logic.

Plain assert-based tests, runnable directly (`python test_strategy.py`) or
via pytest if you have it installed. No fixtures, no framework required.
"""

from __future__ import annotations

import pandas as pd

from wayfinder.config import Config
from wayfinder.strategy import (
    PositionState,
    SmaSnapshot,
    compute_smas,
    evaluate_entry,
    evaluate_exit,
    sma_crossed_above,
    sma_crossed_below,
)

CFG = Config(
    symbol="TEST",
    budget=1000.0,
    short_window=3,
    long_window=5,
    stop_loss_pct=0.05,
    take_profit_trigger_pct=0.05,
    trailing_stop_pct=0.03,
    check_interval_seconds=86400,
    api_key="test",
    secret_key="test",
)


def test_crossover_detection() -> None:
    golden = SmaSnapshot(short_prev=9, short_curr=11, long_prev=10, long_curr=10)
    assert sma_crossed_above(golden)
    assert not sma_crossed_below(golden)

    death = SmaSnapshot(short_prev=11, short_curr=9, long_prev=10, long_curr=10)
    assert sma_crossed_below(death)
    assert not sma_crossed_above(death)

    no_cross = SmaSnapshot(short_prev=12, short_curr=13, long_prev=10, long_curr=10)
    assert not sma_crossed_above(no_cross)
    assert not sma_crossed_below(no_cross)


def test_evaluate_entry() -> None:
    golden = SmaSnapshot(short_prev=9, short_curr=11, long_prev=10, long_curr=10)
    assert evaluate_entry(golden) is True

    flat = SmaSnapshot(short_prev=11, short_curr=11, long_prev=10, long_curr=10)
    assert evaluate_entry(flat) is False


def test_stop_loss() -> None:
    state = PositionState()
    state.open(qty=10, buy_price=100.0)
    flat_sma = SmaSnapshot(short_prev=1, short_curr=1, long_prev=1, long_curr=1)
    # 5% below buy price should trigger the fixed stop-loss.
    reason = evaluate_exit(state, current_price=94.0, sma=flat_sma, cfg=CFG)
    assert reason == "stop_loss", reason
    assert not state.trailing_armed


def test_take_profit_arms_then_trailing_stop_fires() -> None:
    state = PositionState()
    state.open(qty=10, buy_price=100.0)
    flat_sma = SmaSnapshot(short_prev=1, short_curr=1, long_prev=1, long_curr=1)

    # Price rises 6% -> arms the trailing stop, does not sell.
    reason = evaluate_exit(state, current_price=106.0, sma=flat_sma, cfg=CFG)
    assert reason is None
    assert state.trailing_armed
    assert state.highest_price == 106.0

    # Price rises further -> highest_price tracks it, still no sell.
    reason = evaluate_exit(state, current_price=110.0, sma=flat_sma, cfg=CFG)
    assert reason is None
    assert state.highest_price == 110.0

    # Price drops >3% from the 110 high -> trailing stop fires.
    reason = evaluate_exit(state, current_price=106.0, sma=flat_sma, cfg=CFG)
    assert reason == "trailing_stop", reason


def test_trend_reversal_overrides_profit_state() -> None:
    state = PositionState()
    state.open(qty=10, buy_price=100.0)
    death_cross = SmaSnapshot(short_prev=11, short_curr=9, long_prev=10, long_curr=10)
    # Price is fine (no stop-loss/trailing trigger) but trend reversed.
    reason = evaluate_exit(state, current_price=101.0, sma=death_cross, cfg=CFG)
    assert reason == "trend_reversal", reason


def test_compute_smas() -> None:
    # 6 closes, long_window=5 -> exactly enough for one prev/curr pair.
    closes = pd.Series([10, 11, 12, 13, 14, 15], index=pd.date_range("2024-01-01", periods=6))
    sma = compute_smas(closes, CFG)
    assert sma is not None
    assert round(sma.long_curr, 2) == round((11 + 12 + 13 + 14 + 15) / 5, 2)

    # Too few closes -> None, not a crash.
    assert compute_smas(closes.iloc[:4], CFG) is None


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} tests passed.")
