# Wayfinder

A trend-following trading bot built on [alpaca-py](https://github.com/alpacahq/alpaca-py),
for **learning purposes only**. Wayfinder trades exclusively on Alpaca's
**paper trading** API — `paper=True` is hardcoded in
[wayfinder/executor.py](wayfinder/executor.py) and is not a configurable
option anywhere in this project. There is no live-trading code path.

## Strategy

- **Entry:** buy when the short-term SMA crosses above the long-term SMA
  (a "golden cross"), using daily closing prices.
- **Exit**, checked in this order every cycle while holding a position:
  1. **Stop-loss** — sell if price falls below `buy_price * (1 - STOP_LOSS_PCT)`,
     but only before the trailing stop has armed.
  2. **Take-profit trigger** — once price rises above
     `buy_price * (1 + TAKE_PROFIT_TRIGGER_PCT)`, arm the trailing stop
     (this doesn't sell by itself).
  3. **Trailing stop** — once armed, track the highest price seen since
     buying and sell if price drops below `highest_price * (1 - TRAILING_STOP_PCT)`.
  4. **Trend reversal** — sell if the short SMA crosses back below the long
     SMA, regardless of profit/loss.

## Project structure

```
wayfinder/
  config.py    - loads settings from .env / environment variables
  data_feed.py - fetches historical daily bars from Alpaca's data API
  strategy.py  - pure decision logic (SMA crossovers, entry/exit state machine)
  executor.py  - places orders via Alpaca's TradingClient (paper=True hardcoded)
  bot.py       - the main loop: ties the above together, logs, handles errors
main.py        - entry point (`python main.py`)
backtest.py    - runs the exact same strategy.py logic against historical data
test_strategy.py - self-check for the strategy state machine
```

`strategy.py` has no network calls and doesn't know about Alpaca at all —
it's just functions operating on prices and a small `PositionState` object.
`backtest.py` and `bot.py` both call the *same* `evaluate_entry` /
`evaluate_exit` functions, so a backtest result reflects the logic the live
bot will actually run.

## Setup

### 1. Get Alpaca paper trading API keys

1. Sign up at [alpaca.markets](https://alpaca.markets/) (free).
2. Go to your [paper trading dashboard](https://app.alpaca.markets/paper/dashboard/overview).
3. Generate an API key ID and secret key. These are your **paper** keys —
   distinct from any live-trading keys, and safe to use here.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` and fill in `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. All
strategy parameters (symbol, budget, SMA windows, stop-loss/take-profit/
trailing percentages, check interval) have sane defaults but can be
overridden in `.env` too — see the comments in `.env.example`.

### 4. Run the bot

```bash
python main.py
```

Wayfinder logs each cycle (timestamp, price, both SMAs, position status,
any order placed) with a `[Wayfinder]` prefix, then sleeps for
`CHECK_INTERVAL_SECONDS` (default: once daily, matching the daily bars the
strategy trades on). Leave it running in a terminal, tmux session, etc.
Stop it any time with Ctrl+C — it holds no persistent state on disk, so on
restart it re-syncs from a flat (no position) state rather than remembering
an in-progress trailing stop from before the restart.

API errors, a closed market, or not-yet-enough price history are logged
and skipped, not fatal — the loop keeps running.

## Backtesting

Before ever pointing the live bot at a symbol, test the strategy against a
past date range:

```bash
python backtest.py --start 2023-01-01 --end 2023-12-31
python backtest.py --symbol TSLA --start 2022-01-01 --end 2022-12-31
python backtest.py --start 2021-01-01 --end 2021-06-30 --no-plot
```

It fetches historical daily bars for the given range from Alpaca, runs the
same entry/exit logic bar-by-bar, and prints: number of trades, win/loss
count, total return %, and a trade-by-trade log — then opens a matplotlib
window with the equity curve (skip with `--no-plot`). Try it against a
rising, a falling, and a flat/choppy period for the same symbol to get a
feel for how the strategy behaves in each regime.

## Running the self-check

```bash
python test_strategy.py
```

Asserts the crossover detection and the full exit priority order (stop-loss
→ take-profit-arms-trailing → trailing-stop → trend-reversal) behave as
specified.

## Known limitations (by design, for a learning tool)

- **In-memory state only.** `PositionState` (buy price, highest price,
  whether the trailing stop is armed) lives in the running process, not on
  disk. Restarting the bot while holding a position loses that state.
- **Daily-resolution price checks.** All exit thresholds are checked
  against the latest daily close, not live intraday quotes — matching the
  default once-a-day `CHECK_INTERVAL_SECONDS`. If you lower the interval,
  the "current price" still only updates once a new daily bar exists.
- **Single symbol, single position.** No portfolio management, no
  position sizing beyond spending up to `BUDGET` per entry.

None of this matters for its purpose — validating strategy logic against
Alpaca's paper API — but don't mistake it for production trading
infrastructure.
