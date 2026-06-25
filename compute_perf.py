"""End-of-day performance: pair today's trades into round-trips, compute P&L and
R-multiples, print a JSON summary, ping Telegram, and write a self-refreshing
HTML dashboard. Run after the close, or any time to see current state.

Never modifies trades.csv.
"""

import csv
import json
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.notify import notify

ET = ZoneInfo("America/New_York")
TRADES_CSV = Path("trades.csv")
POSITIONS_PATH = Path("open_positions.json")
SAFETY_LOG = Path("safety-check-log.json")
DASH_DIR = Path("dashboard")


def load_today_rows():
    if not TRADES_CSV.exists():
        return []
    today = datetime.now(ET).strftime("%Y-%m-%d")
    with TRADES_CSV.open() as f:
        return [r for r in csv.DictReader(f) if r["timestamp_iso"][:10] == today]


def pair_trades(rows):
    """FIFO-pair BUY and SELL rows per symbol into closed round-trips."""
    buys = defaultdict(deque)
    closed = []
    for r in rows:
        sym, side = r["symbol"], r["side"]
        size = int(float(r["size"]))
        price = float(r["fill_price"] or 0)
        if side == "BUY":
            buys[sym].append({"size": size, "price": price})
        elif side == "SELL":
            remaining = size
            while remaining > 0 and buys[sym]:
                lot = buys[sym][0]
                matched = min(remaining, lot["size"])
                pnl = (price - lot["price"]) * matched
                closed.append({
                    "symbol": sym, "qty": matched,
                    "buy_price": lot["price"], "sell_price": price,
                    "pnl": pnl,
                    "pnl_pct": (price - lot["price"]) / lot["price"] * 100 if lot["price"] else 0.0,
                })
                lot["size"] -= matched
                remaining -= matched
                if lot["size"] == 0:
                    buys[sym].popleft()
    return closed


def aggregate(closed):
    total = len(closed)
    wins = [c for c in closed if c["pnl"] > 0]
    losses = [c for c in closed if c["pnl"] < 0]
    sum_w = sum(c["pnl"] for c in wins)
    sum_l = sum(c["pnl"] for c in losses)
    if total == 0:
        pf = "n/a"
    elif not losses:
        pf = "inf"
    else:
        pf = round(sum_w / abs(sum_l), 2)
    best = max(closed, key=lambda c: c["pnl"]) if closed else None
    worst = min(closed, key=lambda c: c["pnl"]) if closed else None
    return {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / total * 100, 1) if total else 0.0,
        "gross_pnl_usd": round(sum(c["pnl"] for c in closed), 2),
        "largest_winner": [best["symbol"], round(best["pnl"], 2)] if best else None,
        "largest_loser": [worst["symbol"], round(worst["pnl"], 2)] if worst else None,
        "avg_winner": round(sum_w / len(wins), 2) if wins else 0.0,
        "avg_loser": round(sum_l / len(losses), 2) if losses else 0.0,
        "profit_factor": pf,
    }


def build_dashboard(summary, closed, positions, last_cycle):
    DASH_DIR.mkdir(exist_ok=True)
    buckets = [
        ("<= -2R", lambda r: r <= -2),
        ("-2 to -1R", lambda r: -2 < r <= -1),
        ("-1 to 0R", lambda r: -1 < r <= 0),
        ("0 to +1R", lambda r: 0 < r <= 1),
        ("+1 to +2R", lambda r: 1 < r <= 2),
        ("+2 to +3R", lambda r: 2 < r <= 3),
        ("> +3R", lambda r: r > 3),
    ]
    counts = [(label, sum(1 for c in closed if fn(c.get("R", 0)))) for label, fn in buckets]
    maxc = max((c for _, c in counts), default=0) or 1
    hist = ""
    for label, c in counts:
        width = int(c / maxc * 100)
        hist += (f'<div class="d-flex align-items-center mb-1">'
                 f'<div style="width:95px" class="small">{label}</div>'
                 f'<div class="flex-grow-1"><div class="bg-primary" '
                 f'style="width:{width}%;height:18px;border-radius:3px">&nbsp;</div></div>'
                 f'<div class="ms-2 small">{c}</div></div>')

    pos_rows = "".join(
        f'<tr><td>{p["symbol"]}</td><td>{p["qty"]}</td><td>${p["entry_price"]:.2f}</td>'
        f'<td>${p.get("current_stop", p.get("initial_stop", 0)):.2f}</td></tr>'
        for p in positions
    ) or '<tr><td colspan="4" class="text-muted">No open positions</td></tr>'

    closed_rows = ""
    for c in closed[-20:][::-1]:
        color = "text-success" if c["pnl"] >= 0 else "text-danger"
        closed_rows += (f'<tr><td>{c["symbol"]}</td><td>{c["qty"]}</td>'
                        f'<td>${c["buy_price"]:.2f}</td><td>${c["sell_price"]:.2f}</td>'
                        f'<td class="{color}">${c["pnl"]:+.2f}</td>'
                        f'<td class="{color}">{c.get("R", 0):+.2f}R</td></tr>')
    closed_rows = closed_rows or '<tr><td colspan="6" class="text-muted">No closed trades today</td></tr>'

    pnl_color = "text-success" if summary["gross_pnl_usd"] >= 0 else "text-danger"
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Trading Bot Dashboard</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head><body class="bg-light"><div class="container py-4">
<div class="d-flex justify-content-between align-items-center mb-2">
<h4 class="mb-0">Trading Bot Dashboard</h4>
<span class="badge bg-success">Bot Status: ACTIVE</span></div>
<p class="text-muted small">Last cycle: {last_cycle}</p>
<div class="row g-3">
<div class="col-md-6"><div class="card"><div class="card-body">
<h6 class="card-title">Today's P&amp;L</h6>
<div class="display-6 {pnl_color}">${summary['gross_pnl_usd']:+.2f}</div>
<div class="small text-muted">{summary['total_trades']} trades, {summary['wins']}W / {summary['losses']}L, win rate {summary['win_rate_pct']}%</div>
</div></div></div>
<div class="col-md-6"><div class="card"><div class="card-body">
<h6 class="card-title">R-Multiple Histogram</h6>{hist}</div></div></div>
<div class="col-md-6"><div class="card"><div class="card-body">
<h6 class="card-title">Open Positions</h6>
<table class="table table-sm mb-0"><thead><tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Stop</th></tr></thead>
<tbody>{pos_rows}</tbody></table></div></div></div>
<div class="col-md-6"><div class="card"><div class="card-body">
<h6 class="card-title">Recent Closed Trades</h6>
<table class="table table-sm mb-0"><thead><tr><th>Sym</th><th>Qty</th><th>Buy</th><th>Sell</th><th>P&amp;L</th><th>R</th></tr></thead>
<tbody>{closed_rows}</tbody></table></div></div></div>
</div></div></body></html>"""
    (DASH_DIR / "index.html").write_text(html)


def main():
    rows = load_today_rows()
    closed = pair_trades(rows)

    stops = {}
    if POSITIONS_PATH.exists():
        try:
            for p in json.loads(POSITIONS_PATH.read_text()):
                stops[p["symbol"]] = p.get("initial_stop", p["entry_price"] * 0.99)
        except Exception:
            pass
    for c in closed:
        stop = stops.get(c["symbol"], c["buy_price"] * 0.99)  # fallback ~1% risk proxy
        risk = c["buy_price"] - stop
        c["R"] = (c["sell_price"] - c["buy_price"]) / risk if risk else 0.0

    summary = aggregate(closed)
    print(json.dumps(summary, indent=2))

    today = datetime.now(ET).strftime("%Y-%m-%d")
    if summary["total_trades"] == 0:
        body = "No closed trades today."
    else:
        bw, wl = summary["largest_winner"], summary["largest_loser"]
        body = (f"Trades: {summary['total_trades']} ({summary['wins']}W / {summary['losses']}L, {summary['win_rate_pct']}%)\n"
                f"P&L: ${summary['gross_pnl_usd']:+.2f}\n"
                f"Best: {bw[0]} ${bw[1]:+.2f}\n"
                f"Worst: {wl[0]} ${wl[1]:+.2f}\n"
                f"PF: {summary['profit_factor']}")
    try:
        notify(f"Daily Summary {today}", body)
    except Exception:
        pass

    positions = []
    if POSITIONS_PATH.exists():
        try:
            positions = json.loads(POSITIONS_PATH.read_text())
        except Exception:
            positions = []

    last_cycle = "no cycle data yet"
    if SAFETY_LOG.exists():
        lines = SAFETY_LOG.read_text().splitlines()
        if lines:
            try:
                obj = json.loads(lines[-1])
                last_cycle = f"{obj.get('ts', '?')} ({obj.get('event', '?')})"
            except Exception:
                pass

    build_dashboard(summary, closed, positions, last_cycle)
    print("Dashboard written to dashboard/index.html")


if __name__ == "__main__":
    main()