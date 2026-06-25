# Session Review — June 22-23, 2026

## Outcome
Two full unattended live sessions. Zero trades. This is the system working, not failing: every watchlist name was evaluated and correctly rejected.

## What the filters decided
The bot evaluated each name and turned it down for a specific, correct reason:
- **D3 fail** (gap under 3%): morning gaps faded below threshold by the time the bot checked live.
- **D1 fail** (below yesterday's high): stock pulled back under the prior high.
- **D2 fail** (below the 200-day average): downtrending names, screened out by design. This was the most common rejection.
- **I1/I2 fail** (below premarket or today's high): losing momentum.

## Key finding
The D2 filter (200-day uptrend) is doing most of the screening. On these two days it rejected name after name, including healthy companies, because they were not in a long-term uptrend. The strategy is strict and will sit on its hands often. This is a strategy decision to revisit, not a bug.

## Bug found and fixed
- `FDXF` was a bogus ticker in the S&P 500 list (real one is FDX). Removed it. The other 502 tickers are clean.

## Open question for next review
Is the D2 filter too strict for the kind of setups I want to catch? Watch how often it is the sole reason for rejection over the next few sessions before deciding.

## Reminder
The bot is useless without TWS open and the Mac awake. The early connection-refused errors in the logs were from before TWS was launched.