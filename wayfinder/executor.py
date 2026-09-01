"""Order execution for Wayfinder, via Alpaca's paper trading API.

SAFETY: ``paper=True`` is hardcoded below and is not exposed through Config
or any environment variable. This is deliberate — Wayfinder is a learning
tool and must never be able to place a live order.
"""

from __future__ import annotations

import time
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.models import Order
from alpaca.trading.requests import MarketOrderRequest

from wayfinder.config import Config

_ORDER_POLL_INTERVAL_SECONDS = 1
_ORDER_FILL_TIMEOUT_SECONDS = 10


def build_trading_client(cfg: Config) -> TradingClient:
    """Create an Alpaca trading client, hardcoded to paper trading.

    ``paper`` is intentionally not a Config field: this line is the single
    place that decides paper-vs-live, and it always says paper.
    """
    return TradingClient(api_key=cfg.api_key, secret_key=cfg.secret_key, paper=True)


def is_market_open(client: TradingClient) -> bool:
    """Check whether the market is currently open for trading."""
    return bool(client.get_clock().is_open)


def _wait_for_fill(client: TradingClient, order_id: str) -> Order:
    """Poll an order until it fills or the timeout elapses.

    Args:
        client: Trading client the order was submitted through.
        order_id: ID of the order to poll.

    Returns:
        The latest Order snapshot (may still be unfilled if the timeout
        was reached — callers should check ``.filled_qty``).
    """
    deadline = time.monotonic() + _ORDER_FILL_TIMEOUT_SECONDS
    order = client.get_order_by_id(order_id)
    while order.filled_qty in (None, "0") and time.monotonic() < deadline:
        time.sleep(_ORDER_POLL_INTERVAL_SECONDS)
        order = client.get_order_by_id(order_id)
    return order


def submit_buy_order(client: TradingClient, symbol: str, budget: float) -> Optional[Order]:
    """Submit a market buy order sized in dollars (fractional shares OK).

    Args:
        client: Paper trading client.
        symbol: Ticker to buy.
        budget: Dollar amount to spend.

    Returns:
        The filled Order, or None if it didn't fill within the timeout
        (caller should log and retry next cycle rather than assume a fill).
    """
    request = MarketOrderRequest(
        symbol=symbol,
        notional=round(budget, 2),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(request)
    filled = _wait_for_fill(client, str(order.id))
    if not filled.filled_qty or float(filled.filled_qty) == 0:
        return None
    return filled


def submit_sell_order(client: TradingClient, symbol: str, qty: float) -> Optional[Order]:
    """Submit a market sell order for the full quantity held.

    Args:
        client: Paper trading client.
        symbol: Ticker to sell.
        qty: Number of shares to sell.

    Returns:
        The filled Order, or None if it didn't fill within the timeout.
    """
    request = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(request)
    filled = _wait_for_fill(client, str(order.id))
    if not filled.filled_qty or float(filled.filled_qty) == 0:
        return None
    return filled
