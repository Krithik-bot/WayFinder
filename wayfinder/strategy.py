"""Trend-following strategy logic for Wayfinder.

Pure functions and a small state container — no network calls here, so this
module is trivially unit-testable and is shared verbatim between the live
bot (bot.py) and the backtester (backtest.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from wayfinder.config import Config


@dataclass
class PositionState:
    """Tracks everything the exit logic needs to know about an open position.

    Attributes:
        is_open: Whether we currently hold shares.
        qty: Number of shares held.
        buy_price: Fill price of the entry order.
        highest_price: Highest price observed since buying (only meaningful
            once the trailing stop is armed).
        trailing_armed: Whether the take-profit trigger has fired, switching
            exit logic from "fixed stop-loss" to "trailing stop".
    """

    is_open: bool = False
    qty: float = 0.0
    buy_price: float = 0.0
    highest_price: float = 0.0
    trailing_armed: bool = False

    def open(self, qty: float, buy_price: float) -> None:
        """Record a new position after a buy fill."""
        self.is_open = True
        self.qty = qty
        self.buy_price = buy_price
        self.highest_price = buy_price
        self.trailing_armed = False

    def close(self) -> None:
        """Reset state after a sell fill."""
        self.is_open = False
        self.qty = 0.0
        self.buy_price = 0.0
        self.highest_price = 0.0
        self.trailing_armed = False


@dataclass
class SmaSnapshot:
    """The two most recent short/long SMA values, used for crossover detection."""

    short_prev: float
    short_curr: float
    long_prev: float
    long_curr: float


def compute_smas(closes: pd.Series, cfg: Config) -> Optional[SmaSnapshot]:
    """Compute the current and previous short/long SMA values.

    Args:
        closes: Daily closing prices, oldest first, at least
            ``cfg.long_window + 1`` values long.
        cfg: Strategy configuration (provides the SMA windows).

    Returns:
        An SmaSnapshot, or None if there isn't enough data yet to compute
        both SMAs plus one prior value (needed to detect a crossover).
    """
    if len(closes) < cfg.long_window + 1:
        return None

    short_sma = closes.rolling(cfg.short_window).mean()
    long_sma = closes.rolling(cfg.long_window).mean()

    return SmaSnapshot(
        short_prev=float(short_sma.iloc[-2]),
        short_curr=float(short_sma.iloc[-1]),
        long_prev=float(long_sma.iloc[-2]),
        long_curr=float(long_sma.iloc[-1]),
    )


def sma_crossed_above(sma: SmaSnapshot) -> bool:
    """True if the short SMA just crossed from at/below to above the long SMA."""
    return sma.short_prev <= sma.long_prev and sma.short_curr > sma.long_curr


def sma_crossed_below(sma: SmaSnapshot) -> bool:
    """True if the short SMA just crossed from at/above to below the long SMA."""
    return sma.short_prev >= sma.long_prev and sma.short_curr < sma.long_curr


def evaluate_entry(sma: SmaSnapshot) -> bool:
    """Return True if the entry signal (golden cross) fired this cycle."""
    return sma_crossed_above(sma)


def evaluate_exit(
    state: PositionState, current_price: float, sma: SmaSnapshot, cfg: Config
) -> Optional[str]:
    """Run the exit checks in priority order for a held position.

    Mutates ``state`` in place (arming the trailing stop, tracking the
    highest price) and returns a reason string if the position should be
    sold this cycle, else None. Priority order, matching the spec:

    1. Fixed stop-loss (only while trailing stop is not yet armed).
    2. Take-profit trigger arms the trailing stop (does not itself sell).
    3. Trailing stop (only once armed).
    4. Trend reversal (checked regardless of the above).

    Args:
        state: Mutable position state; updated with new highest_price /
            trailing_armed values.
        current_price: Latest price to evaluate against.
        sma: Current/previous SMA snapshot for trend-reversal detection.
        cfg: Strategy configuration (thresholds).

    Returns:
        "stop_loss", "trailing_stop", "trend_reversal", or None.
    """
    if not state.trailing_armed:
        if current_price < state.buy_price * (1 - cfg.stop_loss_pct):
            return "stop_loss"
        if current_price > state.buy_price * (1 + cfg.take_profit_trigger_pct):
            state.trailing_armed = True
            state.highest_price = current_price
    else:
        state.highest_price = max(state.highest_price, current_price)
        if current_price < state.highest_price * (1 - cfg.trailing_stop_pct):
            return "trailing_stop"

    if sma_crossed_below(sma):
        return "trend_reversal"

    return None
