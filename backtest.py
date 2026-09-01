"""Backtest the Wayfinder strategy against historical daily bars.

Runs the *exact same* entry/exit functions as the live bot (wayfinder.strategy)
against a historical price series fetched from Alpaca, so results reflect
the real strategy logic rather than a reimplementation of it.

Usage:
    python backtest.py --start 2023-01-01 --end 2023-12-31
    python backtest.py --symbol TSLA --start 2022-01-01 --end 2022-12-31 --no-plot
"""

from __future__ import annotations

import argparse
import dataclasses
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import pandas as pd

from wayfinder.config import Config, load_config
from wayfinder.data_feed import build_data_client, get_daily_closes_for_range
from wayfinder.strategy import PositionState, compute_smas, evaluate_entry, evaluate_exit


@dataclass
class Trade:
    """One completed round-trip (buy then sell) during a backtest."""

    buy_date: pd.Timestamp
    buy_price: float
    sell_date: pd.Timestamp
    sell_price: float
    reason: str

    @property
    def return_pct(self) -> float:
        """Percent gain/loss of this trade."""
        return (self.sell_price / self.buy_price - 1) * 100


@dataclass
class BacktestResult:
    """Summary output of a backtest run."""

    trades: List[Trade]
    equity_curve: List[tuple]  # (date, equity) pairs
    initial_budget: float
    final_equity: float

    @property
    def total_return_pct(self) -> float:
        return (self.final_equity / self.initial_budget - 1) * 100

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.return_pct > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.return_pct <= 0)


def run_backtest(closes: pd.Series, cfg: Config) -> Optional[BacktestResult]:
    """Simulate the strategy bar-by-bar over historical closes.

    Args:
        closes: Daily closing prices, oldest first, indexed by date.
        cfg: Strategy configuration (windows, thresholds, starting budget).

    Returns:
        A BacktestResult, or None if there isn't enough data to evaluate
        even one SMA crossover.
    """
    if len(closes) < cfg.long_window + 1:
        return None

    state = PositionState()
    cash = cfg.budget
    trades: List[Trade] = []
    equity_curve: List[tuple] = []
    open_buy_date = None

    # ponytail: recomputes the rolling SMA on a growing slice each day (O(n^2))
    # rather than precomputing once, so this calls the exact same
    # wayfinder.strategy.compute_smas used by the live bot. Fine for a
    # few thousand daily bars; switch to precomputed rolling arrays if you
    # ever backtest tick/minute data.
    for i in range(cfg.long_window, len(closes)):
        window = closes.iloc[: i + 1]
        sma = compute_smas(window, cfg)
        if sma is None:
            continue
        price = float(window.iloc[-1])
        dt = window.index[-1]

        if not state.is_open:
            if evaluate_entry(sma):
                qty = cash / price
                state.open(qty=qty, buy_price=price)
                cash = 0.0
                open_buy_date = dt
        else:
            reason = evaluate_exit(state, price, sma, cfg)
            if reason is not None:
                cash = state.qty * price
                trades.append(Trade(open_buy_date, state.buy_price, dt, price, reason))
                state.close()

        equity = cash if not state.is_open else state.qty * price
        equity_curve.append((dt, equity))

    # Close out any position still open at the end of the period so the
    # reported stats reflect its (unrealized) result too.
    if state.is_open and equity_curve:
        last_date, last_equity = equity_curve[-1]
        last_price = last_equity / state.qty
        trades.append(Trade(open_buy_date, state.buy_price, last_date, last_price, "end_of_period"))
        cash = last_equity
        state.close()

    final_equity = equity_curve[-1][1] if equity_curve else cash
    return BacktestResult(trades=trades, equity_curve=equity_curve, initial_budget=cfg.budget, final_equity=final_equity)


def print_report(result: BacktestResult, symbol: str) -> None:
    """Print a plain-text summary of a backtest result."""
    print(f"[Wayfinder] Backtest report for {symbol}")
    print(f"[Wayfinder] Trades: {len(result.trades)}  Wins: {result.wins}  Losses: {result.losses}")
    print(f"[Wayfinder] Starting budget: ${result.initial_budget:.2f}")
    print(f"[Wayfinder] Final equity:    ${result.final_equity:.2f}")
    print(f"[Wayfinder] Total return:    {result.total_return_pct:+.2f}%")
    print("[Wayfinder] Trade log:")
    for t in result.trades:
        print(
            f"  {t.buy_date.date()} BUY ${t.buy_price:.2f} -> "
            f"{t.sell_date.date()} SELL ${t.sell_price:.2f} "
            f"({t.reason}, {t.return_pct:+.2f}%)"
        )


def plot_equity_curve(result: BacktestResult, symbol: str) -> None:
    """Plot the equity curve with matplotlib (blocks until the window is closed)."""
    import matplotlib.pyplot as plt

    dates = [d for d, _ in result.equity_curve]
    values = [v for _, v in result.equity_curve]
    plt.plot(dates, values)
    plt.title(f"Wayfinder Backtest Equity Curve — {symbol}")
    plt.xlabel("Date")
    plt.ylabel("Equity ($)")
    plt.grid(True)
    plt.tight_layout()
    plt.show()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest the Wayfinder strategy.")
    parser.add_argument("--symbol", default=None, help="Ticker to backtest (default: config SYMBOL)")
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=date.fromisoformat, help="End date, YYYY-MM-DD")
    parser.add_argument("--budget", type=float, default=None, help="Starting budget (default: config BUDGET)")
    parser.add_argument("--no-plot", action="store_true", help="Skip the matplotlib equity curve window")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    base_cfg = load_config()
    cfg = dataclasses.replace(
        base_cfg,
        symbol=args.symbol or base_cfg.symbol,
        budget=args.budget if args.budget is not None else base_cfg.budget,
    )

    data_client = build_data_client(cfg)
    closes = get_daily_closes_for_range(data_client, cfg.symbol, args.start, args.end)

    result = run_backtest(closes, cfg)
    if result is None:
        print(
            f"[Wayfinder] Not enough data for {cfg.symbol} between {args.start} and {args.end} "
            f"(need at least {cfg.long_window + 1} daily bars, got {len(closes)})."
        )
    else:
        print_report(result, cfg.symbol)
        if not args.no_plot and result.equity_curve:
            plot_equity_curve(result, cfg.symbol)
