"""Single-symbol dev tool: evaluate one ticker and optionally paper-buy it.

This is the manual tester you run by hand. The autonomous loop is cycle.py,
which we build in a later step.
"""

import argparse
import csv
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

import strategy
from src.ibkr_client import IBKRClient

load_dotenv()

ET = ZoneInfo("America/New_York")
TRADES_CSV = Path("trades.csv")
HEADER = ["timestamp_iso", "symbol", "side", "size", "fill_price", "order_id", "status"]


def stamp(msg):
    print(f"[{datetime.now(ET):%H:%M:%S} ET] {msg}")


def todays_buy_count():
    if not TRADES_CSV.exists():
        with TRADES_CSV.open("w", newline="") as f:
            csv.writer(f).writerow(HEADER)
        return 0
    today = datetime.now(ET).strftime("%Y-%m-%d")
    count = 0
    with TRADES_CSV.open() as f:
        for r in csv.DictReader(f):
            if r["side"] == "BUY" and r["timestamp_iso"].startswith(today):
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol.upper()

    paper = os.environ.get("PAPER_TRADING", "true").lower() == "true"
    host = os.environ["IBKR_HOST"]
    port = int(os.environ["IBKR_PORT"])
    client_id = int(os.environ["IBKR_CLIENT_ID"])
    max_trades = int(os.environ["MAX_TRADES_PER_DAY"])
    portfolio = float(os.environ["PORTFOLIO_VALUE_USD"])
    max_trade_usd = float(os.environ["MAX_TRADE_SIZE_USD"])

    # Hard paper/live interlock: refuse to run if the flag and port disagree.
    if paper and port in (7496, 4001):
        sys.exit("ABORT: PAPER_TRADING=true but IBKR_PORT is a LIVE port.")
    if not paper and port in (7497, 4002):
        sys.exit("ABORT: PAPER_TRADING=false but IBKR_PORT is a PAPER port.")

    # Daily trade cap.
    if todays_buy_count() >= max_trades:
        stamp(f"Daily trade cap reached ({max_trades}). No more entries today.")
        sys.exit(0)

    ibkr = IBKRClient(host, port, client_id)
    quantity = 0
    price = 0.0
    try:
        result = strategy.evaluate(symbol, ibkr.ib)
        stamp(f"Evaluation: {result}")

        if args.check_only:
            stamp("Check-only mode: no trade placed.")
            return

        if not result["pass"]:
            stamp(f"Skip {symbol}: {', '.join(result['reasons'])}")
            return

        price = result["price"]
        if price <= 0:
            stamp("No valid price available, skipping.")
            return

        budget = min(max_trade_usd, portfolio * 0.10)
        quantity = int(budget / price)
        if quantity < 1:
            stamp("Position too small for budget, skipping.")
            return

        stamp(f"Placing paper BUY: {quantity} {symbol} @ ~${price:.2f}")
    finally:
        ibkr.disconnect()

    if quantity < 1:
        return

    # Hand execution to trade.py as a separate process (separate client id).
    proc = subprocess.run(
        [sys.executable, "trade.py", "--symbol", symbol, "--side", "BUY", "--size", str(quantity)],
        capture_output=True, text=True, timeout=30,
    )
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.stderr.strip():
        print(proc.stderr.strip())

    # Read back the last recorded row as confirmation.
    if TRADES_CSV.exists():
        with TRADES_CSV.open() as f:
            rows = list(csv.DictReader(f))
        if rows:
            last = rows[-1]
            stamp(f"Recorded: {last['side']} {last['size']} {last['symbol']} status={last['status']}")


if __name__ == "__main__":
    main()