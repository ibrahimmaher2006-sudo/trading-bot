# Trading Bot Journal

This is the bot's brain. Every meaningful event lands here in plain English.
Once a week, Claude reads this file and pulls out patterns.

**BEFORE TRADES START — do these around 9:15 PM**

Get into the project and activate the environment:

```
cd ~/Desktop/trading-bot && source .venv/bin/activate
```

_Puts you in the right folder with the right Python — your prompt should show `(.venv)`._

Confirm Python can reach TWS (open TWS on paper first):

```
python test_connect.py
```

_Should print `Connected: True` and `DUQ850400` — proves the handshake works this session._

Keep the Mac awake through the window (leave this running in its own window):

```
caffeinate -dimsu
```

_Blocks sleep so the bot keeps firing overnight — `Ctrl+C` it in the morning._

Build a fresh watchlist from live data:

```
python morning_prefilter.py
```

_Scans the S&P 500 right now and writes today's gappers to `watchlist.txt`._

Confirm the four scheduled agents are loaded:

```
launchctl list | grep humbledtrader
```

_Should list cycle, prefilter, rotate, dashboard — proves the scheduler is live._

---

**DURING TRADE TIME — 9:30 PM to ~4 AM**

Watch the cycle work in real time:

```
tail -f logs/cycle.out.log
```

_Streams each 5-minute cycle; `Ctrl+C` stops watching but does NOT stop the bot._

(Optional) Prove the phone alert path still works:

```
python -c "from src.notify import notify; notify('Bot check', 'Still alive')"
```

_Your phone should buzz within a second — confirms Telegram is wired._

That's it for during. Buys, stops, and partials fire automatically and hit your phone. You can go to bed after midnight; just leave caffeinate running and the lid open.

---

**AFTER TRADE TIME — in the morning**

Release the Mac (in the caffeinate window):

```
Ctrl+C
```

_Lets the Mac sleep normally again — the bot keeps running regardless._

Regenerate the day's summary and dashboard:

```
python compute_perf.py
```

_Prints the P&L scorecard and rebuilds `dashboard/index.html`._

Check whether anything traded:

```
cat journal.md
```

_Trade events appear here in plain English; empty means zero trades (normal)._

---

**ERROR CHECKS — run these if something seems off**

Confirm TWS is reachable right now:

```
python test_connect.py
```

_`Connected: True` = fine; a hang or failure = TWS is closed or API toggle dropped._

See the most recent cycle outcomes:

```
tail -5 logs/cycle.out.log
```

_Fresh `cycle ok` / `closed` lines mean cycles are firing; check the timestamp with `ls -la logs/cycle.out.log` if unsure how recent._

Check for current connection errors (read the TIMESTAMP, not just the content):

```
ls -la logs/cycle.err.log
```

_If the time hasn't changed in several minutes, any error inside is stale, not live._

Clear stale logs and trigger one fresh cycle to get a clean read:

```
rm -f logs/cycle.out.log logs/cycle.err.log && launchctl start com.humbledtrader.cycle
```

_Wipes old noise and fires one cycle now; then check both logs are clean._

Read the fresh result after that:

```
tail -3 logs/cycle.out.log && cat logs/cycle.err.log
```

_An empty err log = no current problem; the err file only matters during market hours since off-hours cycles exit before connecting._

---

## 2026-06-22 — Connection established
- Connected Python to Interactive Brokers (TWS) on the paper account.
- Paper account confirmed: DUQ850400. The DU prefix means simulated money, no real funds at risk.
- Connection test passed (Connected: True).
- No trades yet. Next up: the strategy rules file, then a live buy/sell test when US markets are open.
