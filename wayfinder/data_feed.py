"""Historical price data fetching for Wayfinder, via Alpaca's market data API."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from wayfinder.config import Config


def build_data_client(cfg: Config) -> StockHistoricalDataClient:
    """Create an Alpaca historical data client from the loaded config.

    The market data API is not a trading endpoint, so there is no
    paper/live distinction to enforce here.
    """
    return StockHistoricalDataClient(api_key=cfg.api_key, secret_key=cfg.secret_key)


def get_recent_daily_closes(
    client: StockHistoricalDataClient, symbol: str, long_window: int
) -> pd.Series:
    """Fetch recent daily closing prices, enough to compute both SMAs twice over.

    Args:
        client: An Alpaca historical data client.
        symbol: Ticker to fetch.
        long_window: The long SMA window; determines how far back to look.

    Returns:
        A pandas Series of closing prices indexed by date, oldest first.
        May contain fewer rows than requested near market holidays/weekends
        or if the symbol has a short trading history.
    """
    # Fetch a generous buffer beyond the long window: enough calendar days to
    # cover weekends/holidays, plus one extra bar so the *previous* SMA value
    # (needed to detect a crossover) is also computable.
    lookback_days = int((long_window + 5) * 1.6) + 5
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=datetime.utcnow() - timedelta(days=lookback_days),
    )
    bar_set = client.get_stock_bars(request)
    df = bar_set.df
    if df.empty:
        return pd.Series(dtype=float)

    # alpaca-py returns a MultiIndex (symbol, timestamp) frame when queried
    # with a symbol list; drop the symbol level to get a simple date-indexed series.
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    return df["close"]


def get_daily_closes_for_range(
    client: StockHistoricalDataClient, symbol: str, start: date, end: date
) -> pd.Series:
    """Fetch daily closing prices for an explicit date range (used by the backtester).

    Args:
        client: An Alpaca historical data client.
        symbol: Ticker to fetch.
        start: First date to include.
        end: Last date to include.

    Returns:
        A pandas Series of closing prices indexed by date, oldest first.
    """
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=datetime.combine(start, datetime.min.time()),
        end=datetime.combine(end, datetime.min.time()),
    )
    bar_set = client.get_stock_bars(request)
    df = bar_set.df
    if df.empty:
        return pd.Series(dtype=float)

    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    return df["close"]
