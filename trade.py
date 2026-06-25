"""Executes a single order. Run as a subprocess by bot.py (and later cycle.py).

Uses IBKR_EXEC_CLIENT_ID so its connection never collides with the
orchestrator's connection.
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.ibkr_client import IBKRClient

load_dotenv()

TRADES_CSV = Path("trades.csv")
HEADER = ["timestamp_iso", "symbol", "side", "size", "fill_price", "order_id", "status"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", required=True)
    parser.add_argument("--size", type=int, required=True)
    args = parser.parse_args()

    host = os.environ["IBKR_HOST"]
    port = int(os.environ["IBKR_PORT"])
    exec_client_id = int(os.environ["IBKR_EXEC_CLIENT_ID"])

    ibkr = IBKRClient(host, port, exec_client_id)
    try:
        trade = ibkr.place_order(args.symbol, args.side, args.size)
        status = trade.orderStatus.status

        if status in ("Cancelled", "ApiCancelled", "Inactive"):
            print(f"ORDER REJECTED: {args.symbol} status={status}")
            for entry in trade.log:
                print("  ", entry.status, entry.message)
            sys.exit(1)

        fill_price = trade.orderStatus.avgFillPrice or 0
        order_id = trade.order.orderId

        if not TRADES_CSV.exists():
            with TRADES_CSV.open("w", newline="") as f:
                csv.writer(f).writerow(HEADER)

        row = [
            datetime.now(timezone.utc).isoformat(),
            args.symbol,
            args.side,
            args.size,
            fill_price,
            order_id,
            status,
        ]
        with TRADES_CSV.open("a", newline="") as f:
            csv.writer(f).writerow(row)

        print(f"FILLED: {args.side} {args.size} {args.symbol} @ {fill_price} status={status}")
    finally:
        ibkr.disconnect()


if __name__ == "__main__":
    main()