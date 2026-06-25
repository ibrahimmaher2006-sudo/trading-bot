"""Autonomous trading cycle. Runs every 5 minutes from the scheduler.

Each run: check the clock, manage open positions (partials, breakeven, trailing
stops), force-close before the bell, and during the trading window scan the
watchlist and open new positions. Every decision is logged to the safety log
and summarized in plain English in journal.md (the brain).

Rules-based: no AI is called at runtime. cycle.py connects with IBKR_CLIENT_ID;
trade.py (spawned for execution) uses IBKR_EXEC_CLIENT_ID, so they never collide.
"""

import csv
import json
import math
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from ib_async import IB, Stock, MarketOrder, StopOrder

from src import journal

load_dotenv()

ET = ZoneInfo("America/New_York")
RULES = json.loads(Path("rules.json").read_text())
WATCHLIST_PATH = Path("watchlist.txt")
POSITIONS_PATH = Path("open_positions.json")
TRADES_CSV = Path("trades.csv")
LOG_DIR = Path("logs")
SAFETY_LOG = Path("safety-check-log.json")

HOST = os.environ["IBKR_HOST"]
PORT = int(os.environ["IBKR_PORT"])
CLIENT_ID = int(os.environ["IBKR_CLIENT_ID"])
PORTFOLIO = float(os.environ["PORTFOLIO_VALUE_USD"])
MAX_TRADES = int(os.environ["MAX_TRADES_PER_DAY"])
MAX_RISK_PCT = float(os.environ["MAX_RISK_PER_TRADE_PCT"])

MAX_POS = int(RULES["risk"]["max_concurrent_positions"])
MIN_GAP = RULES["daily_filters"]["D3_min_gap_pct_from_prior_close"]
RVOL_MIN = RULES["intraday_filters"]["I3_rvol_min"]
RVOL_DAYS = RULES["intraday_filters"]["I3_rvol_lookback_days"]
PARTIAL_R = RULES["exit"]["partial_profit_trigger_R"]
BE_R = RULES["exit"]["breakeven_trigger_R"]


# ----------------------------- helpers -----------------------------

def safety_log(obj):
    LOG_DIR.mkdir(exist_ok=True)
    clean = {k: (bool(v) if isinstance(v, bool) else v) for k, v in obj.items()}
    clean["ts"] = datetime.now(ET).isoformat()
    with SAFETY_LOG.open("a") as f:
        f.write(json.dumps(clean, default=str) + "\n")


def time_gate(now=None):
    now = now or datetime.now(ET)
    if now.weekday() >= 5:
        return "weekend"
    t = now.time()
    if t < dtime(10, 0):
        return "too_early"
    if t >= dtime(16, 0):
        return "closed"
    if t < dtime(10, 5):
        return "manage_only"     # 10:00-10:05
    if t < dtime(15, 30):
        return "ok"              # 10:05-15:30
    if t < dtime(15, 51):
        return "manage_only"     # 15:30-15:51
    return "force_close"         # 15:51-16:00


def to_yahoo(sym):
    return sym.replace(" ", "-")


def _flat(df):
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def fetch_daily(yahoo):
    return _flat(yf.download(yahoo, period="300d", interval="1d",
                             auto_adjust=True, progress=False))


def fetch_intraday(yahoo):
    df = _flat(yf.download(yahoo, period="1d", interval="5m",
                           auto_adjust=True, prepost=True, progress=False))
    if df.empty:
        return df
    if df.index.tz is None:
        df = df.tz_localize("UTC").tz_convert(ET)
    else:
        df = df.tz_convert(ET)
    return df


def load_positions():
    if not POSITIONS_PATH.exists():
        return []
    try:
        return json.loads(POSITIONS_PATH.read_text())
    except (json.JSONDecodeError, ValueError):
        return []


def save_positions(positions):
    tmp = POSITIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(positions, indent=2, default=str))
    os.replace(tmp, POSITIONS_PATH)


def read_watchlist():
    if not WATCHLIST_PATH.exists():
        return []
    out = []
    for line in WATCHLIST_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ticker = line.split("#")[0].strip()
        if ticker:
            out.append(ticker)
    return out


def count_todays_buys():
    if not TRADES_CSV.exists():
        return 0
    today = datetime.now(ET).strftime("%Y-%m-%d")
    n = 0
    with TRADES_CSV.open() as f:
        for r in csv.DictReader(f):
            if r["side"] == "BUY" and r["timestamp_iso"][:10] == today:
                n += 1
    return n


def swing_lows(intraday):
    lows = intraday["Low"].values
    found = []
    for i in range(2, len(lows) - 2):
        if (lows[i] < lows[i - 1] and lows[i] < lows[i - 2]
                and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]):
            found.append(float(lows[i]))
    return found


# ----------------------------- the six filters -----------------------------

def passes_filters(yahoo):
    """Evaluate ALL six filters every time and return full per-filter detail.

    Returns (passed, reasons, price, low_of_day, detail).
      passed     bool   True only if all six filters (D1-D3, I1-I3) pass.
      reasons    list   Human-readable summary strings (back-compat).
      price      float  Latest intraday close (signal price).
      low_of_day float  RTH low, used for the initial stop.
      detail     list   One dict per filter: name, passed, value, threshold, note.

    IMPORTANT: every filter is now evaluated even after one fails, so the
    safety log records which filters bind, not just the first to fail. The
    BUY decision is unchanged: a name is taken only if ALL six pass.
    Filter MATH is unchanged from the prior version; only the control flow
    (no early return) and the logging detail are new.
    """
    detail = []

    def record(name, passed, value, threshold, note=""):
        detail.append({
            "filter": name,
            "pass": bool(passed),
            "value": (round(value, 4) if isinstance(value, float) else value),
            "threshold": (round(threshold, 4) if isinstance(threshold, float) else threshold),
            "note": note,
        })
        return bool(passed)

    daily = fetch_daily(yahoo)
    intraday = fetch_intraday(yahoo)
    if daily.empty or intraday.empty or len(daily) < 2:
        record("data", False, None, None, "no data: empty daily/intraday or <2 daily bars")
        return False, ["no data"], 0.0, 0.0, detail

    price = float(intraday["Close"].iloc[-1])
    yest = daily.iloc[-2]
    today = daily.iloc[-1]
    yesterday_high = float(yest["High"])
    yesterday_close = float(yest["Close"])
    today_open = float(today["Open"])

    # D1: price above yesterday's high
    d1 = record("D1_above_prior_high", price > yesterday_high, price, yesterday_high,
                "signal price vs prior day high")

    # D2: yesterday's close above the 200-day SMA
    if len(daily) >= 201:
        sma200 = float(daily["Close"].iloc[-201:-1].mean())
    else:
        sma200 = float(daily["Close"].iloc[:-1].mean())
    d2 = record("D2_close_above_sma200", yesterday_close > sma200, yesterday_close, sma200,
                "prior close vs 200-day SMA")

    # D3: gapped up at least MIN_GAP%
    gap_pct = (today_open - yesterday_close) / yesterday_close * 100
    d3 = record("D3_gap_pct", gap_pct >= MIN_GAP, gap_pct, float(MIN_GAP),
                "today open vs prior close, percent")

    times = intraday.index
    premarket = intraday[times.time < dtime(9, 30)]
    rth = intraday[times.time >= dtime(9, 30)]
    if rth.empty:
        record("rth", False, None, None, "no RTH bars yet")
        passed = d1 and d2 and d3 and False
        return passed, ["no RTH bars yet"], price, 0.0, detail

    # I1: above the premarket high. If there are no premarket bars, this filter
    # cannot be evaluated; record it as a skip (counts as a PASS for the gate,
    # matching prior behavior, but flagged so you can see it was not truly tested).
    if not premarket.empty:
        pm_high = float(premarket["High"].max())
        i1 = record("I1_above_premarket_high", price > pm_high, price, pm_high,
                    "signal price vs premarket high")
    else:
        i1 = record("I1_above_premarket_high", True, price, None,
                    "SKIPPED: no premarket bars (filter not evaluated, treated as pass)")

    # I2: above today's high so far (joining strength)
    if len(rth) > 1:
        rth_high_prior = float(rth["High"].iloc[:-1].max())
    else:
        rth_high_prior = float(rth["High"].iloc[0])
    i2 = record("I2_above_today_hod", price >= rth_high_prior, price, rth_high_prior,
                "signal price vs prior RTH high")

    # I3: relative volume >= RVOL_MIN (today's volume vs the 14-day average)
    # NOTE: known measurement caveat - today's partial-day volume is compared to a
    # full-day average, so this reads low in the morning. Left unchanged on purpose;
    # this instrumentation pass is logging-only. The value is recorded so the bias
    # is visible in the data before any fix.
    today_vol = float(rth["Volume"].sum())
    if len(daily) >= RVOL_DAYS + 1:
        avg_vol = float(daily["Volume"].iloc[-(RVOL_DAYS + 1):-1].mean())
    else:
        avg_vol = float(daily["Volume"].iloc[:-1].mean())
    rvol = today_vol / avg_vol if avg_vol else 0.0
    i3 = record("I3_rvol", rvol >= RVOL_MIN, rvol, float(RVOL_MIN),
                "cumulative RTH volume / 14-day avg full-day volume (partial-day bias)")

    low_of_day = float(rth["Low"].min())
    passed = d1 and d2 and d3 and i1 and i2 and i3

    # Compact human-readable reasons: list every filter that failed, or an ok summary.
    fails = [d["filter"] for d in detail if not d["pass"]]
    if passed:
        reasons = ["all six pass", f"gap {gap_pct:.2f}%", f"rvol {rvol:.2f}"]
    else:
        reasons = [f"failed: {', '.join(fails)}"]
    return passed, reasons, price, low_of_day, detail


# ----------------------------- order helpers -----------------------------

def place_stop(ib, symbol, qty, stop_price):
    contract = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(contract)
    order = StopOrder("SELL", qty, round(stop_price, 2), outsideRth=True)
    trade = ib.placeOrder(contract, order)
    ib.sleep(1)
    return trade.order.orderId


def cancel_stop(ib, p):
    sid = p.get("stop_order_id")
    if sid is None:
        return
    for o in ib.openOrders():
        if o.orderId == sid:
            ib.cancelOrder(o)
            break


def replace_stop(ib, p, new_stop):
    cancel_stop(ib, p)
    p["stop_order_id"] = place_stop(ib, p["symbol"], p["qty"], new_stop)
    p["current_stop"] = round(new_stop, 2)


def execute(symbol, side, size):
    proc = subprocess.run(
        [sys.executable, "trade.py", "--symbol", symbol, "--side", side, "--size", str(size)],
        capture_output=True, text=True, timeout=30,
    )
    if proc.stdout.strip():
        print(proc.stdout.strip())
    return proc.returncode == 0 and "FILLED" in proc.stdout


def close_position(ib, p):
    contract = Stock(p["symbol"], "SMART", "USD")
    ib.qualifyContracts(contract)
    ib.placeOrder(contract, MarketOrder("SELL", p["qty"], outsideRth=True))
    ib.sleep(1)
    journal.log(f"CLOSE {p['symbol']}", f"Force-closed {p['qty']} @ market before the bell.")


def manage_position(ib, p):
    intr = fetch_intraday(to_yahoo(p["symbol"]))
    if intr.empty:
        return
    price = float(intr["Close"].iloc[-1])
    entry = p["entry_price"]
    R = p["R"]

    if p["state"] == "pre_breakeven":
        if price >= entry + BE_R * R:
            replace_stop(ib, p, entry)
            p["state"] = "post_breakeven_no_partial"
            journal.log(f"BREAKEVEN {p['symbol']}",
                        f"+{BE_R}R hit. Stop moved to entry ${entry:.2f}. Trade is now risk-free.")
        elif price >= entry + PARTIAL_R * R:
            sell_qty = math.ceil(p["qty"] / 3)
            execute(p["symbol"], "SELL", sell_qty)
            p["qty"] -= sell_qty
            replace_stop(ib, p, entry * 0.99)
            p["state"] = "post_breakeven_partial_done"
            journal.log(f"PARTIAL {p['symbol']}",
                        f"+{PARTIAL_R}R hit. Sold {sell_qty} to bank gains. Stop to ${entry * 0.99:.2f}.")
    else:  # post_breakeven_*
        sl = swing_lows(intr)
        if sl:
            newest = sl[-1]
            cur_stop = p.get("current_stop", p["initial_stop"])
            if newest - 0.01 > cur_stop:
                replace_stop(ib, p, newest - 0.01)
                journal.log(f"TRAIL {p['symbol']}", f"Stop trailed up to ${newest - 0.01:.2f}.")


# ----------------------------- main -----------------------------

def connect():
    ib = IB()
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID)
    except Exception:
        time.sleep(5)
        ib.connect(HOST, PORT, clientId=CLIENT_ID)
    return ib


def main():
    status = time_gate()
    if status in ("weekend", "too_early", "closed"):
        safety_log({"event": "skip", "status": status})
        print(f"{status}: nothing to do.")
        return

    ib = connect()
    try:
        positions = load_positions()

        # 3. Remove anything that got stopped out (match by stop order id, never quantity).
        stopped_ids = {f.execution.orderId for f in ib.fills()}
        still_open = []
        for p in positions:
            if p.get("stop_order_id") in stopped_ids:
                journal.log(f"STOP {p['symbol']}",
                            f"Stopped out. Entry ${p['entry_price']:.2f}, stop ${p.get('current_stop', p['initial_stop']):.2f}.")
                safety_log({"event": "stopped_out", "symbol": p["symbol"]})
            else:
                still_open.append(p)
        positions = still_open

        # 4. Manage each open position.
        for p in positions:
            manage_position(ib, p)
        save_positions(positions)

        # 6. Force close before the bell.
        if status == "force_close":
            if positions:
                journal.log("EOD force close", f"Flattening {len(positions)} position(s).")
            for p in positions:
                cancel_stop(ib, p)
                close_position(ib, p)
            save_positions([])
            print("force_close done.")
            return

        # 7. Manage-only windows: no new entries.
        if status == "manage_only":
            print("manage_only: positions managed, no new entries.")
            return

        # 8. Entry scan (status == ok).
        todays_buys = count_todays_buys()
        if todays_buys >= MAX_TRADES:
            print("daily trade cap reached.")
            return

        held = {pos.contract.symbol for pos in ib.positions() if pos.position > 0}
        held |= {p["symbol"] for p in positions}

        for symbol in read_watchlist():
            if len(positions) >= MAX_POS or todays_buys >= MAX_TRADES:
                break
            if symbol in held:
                continue
            passed, reasons, price, lod, detail = passes_filters(to_yahoo(symbol))
            safety_log({
                "event": "evaluate",
                "symbol": symbol,
                "pass": bool(passed),
                "reasons": reasons,
                "price": price,
                "low_of_day": lod,
                "filters": detail,
            })
            if not passed or price <= 0:
                continue

            initial_stop = lod * 0.99
            R = price - initial_stop
            if R <= 0:
                continue
            risk_dollars = PORTFOLIO * (MAX_RISK_PCT / 100)
            size = min(int(risk_dollars / R), int(PORTFOLIO * 0.10 / price))
            if size < 1:
                continue

            if not execute(symbol, "BUY", size):
                journal.log(f"BUY FAILED {symbol}", "Order did not fill; see trades.csv.")
                continue

            stop_id = place_stop(ib, symbol, size, initial_stop)
            positions.append({
                "symbol": symbol, "entry_price": price,
                "entry_time_iso": datetime.now(ET).isoformat(), "qty": size,
                "initial_stop": initial_stop, "current_stop": round(initial_stop, 2),
                "stop_order_id": stop_id, "state": "pre_breakeven", "R": R,
            })
            held.add(symbol)
            todays_buys += 1
            journal.log(f"BUY {symbol}",
                        f"Bought {size} @ ${price:.2f}. Stop ${initial_stop:.2f} (1R = ${R:.2f}).\n"
                        f"Why it passed: {', '.join(reasons)}.")
            safety_log({"event": "entry", "symbol": symbol, "qty": size, "price": price})

        save_positions(positions)
        print(f"cycle ok: {len(positions)} open position(s).")
    except Exception:
        LOG_DIR.mkdir(exist_ok=True)
        with (LOG_DIR / "cycle_errors.log").open("a") as f:
            f.write(f"\n{datetime.now(ET).isoformat()}\n{traceback.format_exc()}\n")
        journal.log("Cycle crashed", "See logs/cycle_errors.log.")
        sys.exit(1)
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()