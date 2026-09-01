"""Entry point: run the Wayfinder paper-trading bot.

Usage:
    python main.py
"""

from wayfinder.bot import run
from wayfinder.config import load_config

if __name__ == "__main__":
    run(load_config())
