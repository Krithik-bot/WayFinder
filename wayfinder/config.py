"""Configuration loading for Wayfinder.

All tunable parameters live here and are sourced from environment variables
(via a ``.env`` file), so nothing is hardcoded deep inside the strategy or
execution logic. See ``.env.example`` for the variables this module reads.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    """Immutable set of runtime settings for a Wayfinder run.

    Attributes:
        symbol: Stock ticker to trade, e.g. "AAPL".
        budget: Max dollars to spend opening a new position.
        short_window: Number of daily bars in the short-term SMA.
        long_window: Number of daily bars in the long-term SMA.
        stop_loss_pct: Fractional drop from buy price that triggers a hard stop-loss.
        take_profit_trigger_pct: Fractional gain from buy price that arms the trailing stop.
        trailing_stop_pct: Fractional drop from the highest price seen (after arming)
            that triggers a sell.
        check_interval_seconds: Seconds to sleep between strategy cycles.
        api_key: Alpaca paper-trading API key ID.
        secret_key: Alpaca paper-trading API secret key.
    """

    symbol: str
    budget: float
    short_window: int
    long_window: int
    stop_loss_pct: float
    take_profit_trigger_pct: float
    trailing_stop_pct: float
    check_interval_seconds: int
    api_key: str
    secret_key: str


def _env_float(name: str, default: float) -> float:
    """Read an environment variable as a float, falling back to ``default``."""
    return float(os.getenv(name, default))


def _env_int(name: str, default: int) -> int:
    """Read an environment variable as an int, falling back to ``default``."""
    return int(os.getenv(name, default))


def load_config() -> Config:
    """Build a Config from environment variables (and defaults).

    Raises:
        ValueError: If required API credentials are missing, or the moving
            average windows are not in a sane order (short < long).
    """
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret_key = os.getenv("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise ValueError(
            "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set (see .env.example). "
            "Get paper trading keys from https://app.alpaca.markets/paper/dashboard/overview"
        )

    cfg = Config(
        symbol=os.getenv("SYMBOL", "AAPL"),
        budget=_env_float("BUDGET", 500.0),
        short_window=_env_int("SHORT_WINDOW", 10),
        long_window=_env_int("LONG_WINDOW", 30),
        stop_loss_pct=_env_float("STOP_LOSS_PCT", 0.05),
        take_profit_trigger_pct=_env_float("TAKE_PROFIT_TRIGGER_PCT", 0.05),
        trailing_stop_pct=_env_float("TRAILING_STOP_PCT", 0.03),
        check_interval_seconds=_env_int("CHECK_INTERVAL_SECONDS", 86400),
        api_key=api_key,
        secret_key=secret_key,
    )

    if cfg.short_window >= cfg.long_window:
        raise ValueError(
            f"SHORT_WINDOW ({cfg.short_window}) must be less than LONG_WINDOW ({cfg.long_window})"
        )

    return cfg
