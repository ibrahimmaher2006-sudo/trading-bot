"""Single-symbol gate check used by bot.py (the manual dev tool).

Only checks two things:
  a) do we already hold this symbol?
  b) are we inside the entry window?
The full D1-D3 / I1-I3 filters live in cycle.py (built later), not here.
"""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ib_async import Stock

ET = ZoneInfo("America/New_York")
RULES_PATH = Path("rules.json")
LOG_DIR = Path("logs")
LOG_PATH = LOG_DIR / "safety_log.jsonl"


def _log(result):
    LOG_DIR.mkdir(exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(result) + "\n")


def evaluate(symbol, ib):
    # a) Already holding this symbol?
    for pos in ib.positions():
        if pos.contract.symbol == symbol and pos.position > 0:
            result = {"pass": False, "reasons": ["already in position"], "price": 0.0}
            _log(result)
            return result

    # b) Inside the entry window? (HH:MM strings compare correctly because they are zero-padded)
    rules = json.loads(RULES_PATH.read_text())
    earliest = rules["time_filter"]["earliest_entry_et"]
    latest = rules["time_filter"]["latest_entry_et"]
    now_et = datetime.now(ET).strftime("%H:%M")
    if not (earliest <= now_et <= latest):
        result = {
            "pass": False,
            "reasons": [f"outside entry window {earliest}-{latest} (now {now_et} ET)"],
            "price": 0.0,
        }
        _log(result)
        return result

    # c) Grab a current price snapshot for sizing.
    ib.reqMarketDataType(3)  # 3 = delayed data (free on paper accounts)
    contract = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(contract)
    ticker = ib.reqMktData(contract, "", snapshot=True)
    ib.sleep(2)
    price = ticker.marketPrice()
    if price is None or price != price:  # price != price catches NaN
        price = ticker.last if (ticker.last is not None and ticker.last == ticker.last) else 0.0

    result = {
        "pass": True,
        "reasons": ["time gate ok", "no existing position"],
        "price": float(price) if (price and price == price) else 0.0,
    }
    _log(result)
    return result