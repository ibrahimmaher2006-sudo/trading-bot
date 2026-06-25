# IBKR Automated Paper-Trading Bot

A fully automated paper-trading system for US equities, built on Interactive Brokers, following a "Trend Join Long" gap-and-go momentum strategy. The bot scans the S&P 500 premarket, evaluates a six-filter entry rule on a 5-minute timeframe, manages risk and exits automatically, sends Telegram alerts, logs every decision, and runs unattended on a schedule via macOS launchd.

**This is a learning and strategy-testing project. It trades simulated money only. Nothing here is financial advice, and the strategy has not been shown to have a profitable edge.**

## What it does

- **Scans** the S&P 500 each morning via Yahoo Finance, writing a watchlist of the day's biggest gappers.
- **Evaluates** six filters per candidate (three daily, three intraday) and takes a position only when all six pass.
- **Manages** open positions automatically: partial profit at +0.75R, stop to breakeven at +1R, then trails the stop under swing lows.
- **Force-closes** all positions before the market closes, so nothing is held overnight.
- **Logs** every evaluation with a full per-filter breakdown to `safety-check-log.json`, and writes plain-English trade entries to an Obsidian journal.
- **Alerts** to Telegram on every trade event plus a daily performance summary.
- **Runs itself** every five minutes via launchd, self-gating to New York market hours.

## The strategy: Trend Join Long

Long only, 5-minute candles. A stock qualifies only if all six filters pass.

**Daily filters**
- **D1** — price above yesterday's high (breaking out)
- **D2** — yesterday's close above the 200-day SMA (long-term uptrend)
- **D3** — gapped up at least 3% from the prior close

**Intraday filters**
- **I1** — price above the premarket high
- **I2** — price above today's high so far (joining strength, not buying a fade)
- **I3** — relative volume at least 2x the 14-day average

**Timing** — enter only between 10:05 and 15:30 ET; force-close at 15:51 ET.

**Risk** — at most 1% of the account per trade, no position over 10% of the account, at most 5 concurrent positions.

## Architecture

| File | Role |
|------|------|
| `cycle.py` | The autonomous loop. Runs every 5 min, evaluates all six filters, manages positions, force-closes before the bell. |
| `morning_prefilter.py` | Scans the S&P 500 for gappers, writes `watchlist.txt`. |
| `strategy.py` | Single-symbol gate check used by the manual `bot.py` tool. |
| `trade.py` | Order executor; runs as a separate process with its own client ID. |
| `bot.py` | Manual single-symbol dev tool. |
| `build_tickers.py` | Generates the S&P 500 ticker universe from Wikipedia. |
| `compute_perf.py` | End-of-day P&L, R-multiples, and HTML dashboard. |
| `rotate_logs.py` | Log archiving and housekeeping. |
| `setup_schedule.py` / `cleanup_schedule.py` | Register/remove the launchd agents. |
| `src/journal.py` | Writes plain-English entries to the Obsidian journal. |
| `src/notify.py` | Telegram push notifications. |
| `rules.json` | The entire strategy as data: filters, timing, exits, risk limits. |

## Setup

Requires Python 3.12+, an IBKR paper account, and TWS (or IB Gateway) running locally.
python -m venv .venv

source .venv/bin/activate

pip install -r requirements.txt
Configure a `.env` file (not committed) with your IBKR connection settings, portfolio sizing, and Telegram credentials. Then register the scheduler:

python setup_schedule.py

## Status and honesty notes

- Validated across live unattended paper sessions. The six-filter logic runs correctly and rejects names for specific, logged reasons.
- The bot evaluates strictly and trades rarely by design.
- Known open item: the relative-volume filter (I3) compares partial-day volume against a full-day average, which biases it low in the morning. Logged but not yet corrected.
- The strategy's edge is unproven. The bot is a testing instrument, not a money-maker.

## Disclaimer

Paper trading only. Day trading loses money for most retail traders. This project is for learning system design and honestly testing a strategy before any real capital is ever considered. Not financial advice.