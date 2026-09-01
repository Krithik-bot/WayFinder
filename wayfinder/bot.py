"""Main trading loop for Wayfinder.

Wires together config, data fetching, strategy logic, and order execution.
Runs forever, sleeping ``CHECK_INTERVAL_SECONDS`` between cycles, and never
lets a single cycle's error take the process down.
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.client import TradingClient

from wayfinder.config import Config
from wayfinder.data_feed import build_data_client, get_recent_daily_closes
from wayfinder.executor import (
    build_trading_client,
    is_market_open,
    submit_buy_order,
    submit_sell_order,
)
from wayfinder.strategy import PositionState, compute_smas, evaluate_entry, evaluate_exit

LOG_PREFIX = "[Wayfinder]"


def _log(message: str) -> None:
    """Print a timestamped, Wayfinder-prefixed log line."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{LOG_PREFIX} {timestamp} {message}")


def run_cycle(
    cfg: Config,
    trading_client: TradingClient,
    data_client: StockHistoricalDataClient,
    state: PositionState,
) -> None:
    """Run one strategy cycle: fetch data, log status, act on signals.

    Raises whatever the underlying API calls raise; the caller (`run`) is
    responsible for catching and logging so one bad cycle doesn't kill the
    process.
    """
    closes = get_recent_daily_closes(data_client, cfg.symbol, cfg.long_window)
    sma = compute_smas(closes, cfg)
    if sma is None:
        _log(
            f"Insufficient data for {cfg.symbol}: have {len(closes)} daily bars, "
            f"need at least {cfg.long_window + 1}. Skipping this cycle."
        )
        return

    current_price = float(closes.iloc[-1])
    position_desc = (
        f"holding {state.qty:.4f} @ ${state.buy_price:.2f} "
        f"(armed={state.trailing_armed}, high=${state.highest_price:.2f})"
        if state.is_open
        else "flat"
    )
    _log(
        f"{cfg.symbol} price=${current_price:.2f} "
        f"SMA{cfg.short_window}=${sma.short_curr:.2f} SMA{cfg.long_window}=${sma.long_curr:.2f} "
        f"position={position_desc}"
    )

    if not state.is_open:
        if evaluate_entry(sma):
            _log(f"Buy signal triggered: SMA{cfg.short_window} crossed above SMA{cfg.long_window}.")
            _place_buy(cfg, trading_client, state, current_price)
        return

    reason = evaluate_exit(state, current_price, sma, cfg)
    if reason is not None:
        _log(f"Sell signal triggered ({reason}) at ${current_price:.2f}.")
        _place_sell(cfg, trading_client, state)


def _place_buy(cfg: Config, trading_client: TradingClient, state: PositionState, price: float) -> None:
    """Check market hours, submit a buy order, and update state on fill."""
    if not is_market_open(trading_client):
        _log("Market is closed — skipping buy this cycle, will retry next cycle.")
        return

    order = submit_buy_order(trading_client, cfg.symbol, cfg.budget)
    if order is None:
        _log("Buy order did not fill in time — will re-evaluate next cycle.")
        return

    fill_price = float(order.filled_avg_price or price)
    fill_qty = float(order.filled_qty)
    state.open(qty=fill_qty, buy_price=fill_price)
    _log(f"BUY {fill_qty:.4f} {cfg.symbol} @ ${fill_price:.2f} (~${fill_qty * fill_price:.2f})")


def _place_sell(cfg: Config, trading_client: TradingClient, state: PositionState) -> None:
    """Check market hours, submit a sell order, and reset state on fill."""
    if not is_market_open(trading_client):
        _log("Market is closed — skipping sell this cycle, will retry next cycle.")
        return

    order = submit_sell_order(trading_client, cfg.symbol, state.qty)
    if order is None:
        _log("Sell order did not fill in time — will retry next cycle.")
        return

    fill_price = float(order.filled_avg_price or 0.0)
    pnl_pct = (fill_price / state.buy_price - 1) * 100 if state.buy_price else 0.0
    _log(f"SELL {state.qty:.4f} {cfg.symbol} @ ${fill_price:.2f} (P/L {pnl_pct:+.2f}%)")
    state.close()


def run(cfg: Config) -> None:
    """Run the Wayfinder bot forever, one strategy cycle per CHECK_INTERVAL_SECONDS.

    Any exception raised during a cycle is logged and swallowed so the bot
    keeps running through transient API errors, market-closed periods, etc.
    """
    _log(f"Starting on {cfg.symbol} (paper trading only). Budget=${cfg.budget:.2f}")
    trading_client = build_trading_client(cfg)
    data_client = build_data_client(cfg)
    state = PositionState()

    while True:
        try:
            run_cycle(cfg, trading_client, data_client, state)
        except Exception:
            _log("Error during strategy cycle:")
            traceback.print_exc()
        time.sleep(cfg.check_interval_seconds)
