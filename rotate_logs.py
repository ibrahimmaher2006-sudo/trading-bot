"""Housekeeping: archive yesterday's logs, trim trades.csv to 90 days, cap the
safety log. Safe to run any time of day; exits 0 even with nothing to do.
"""

import csv
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
LOG_DIR = Path("logs")
ARCHIVE = LOG_DIR / "archive"
TRADES_CSV = Path("trades.csv")
SAFETY_LOG = Path("safety-check-log.json")


def main():
    moved = 0
    today = datetime.now(ET).date()
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    if LOG_DIR.exists():
        for f in LOG_DIR.iterdir():
            if f.is_file() and f.suffix in (".log", ".jsonl"):
                mdate = datetime.fromtimestamp(f.stat().st_mtime, ET).date()
                if mdate < today:
                    dest = ARCHIVE / mdate.isoformat()
                    dest.mkdir(parents=True, exist_ok=True)
                    os.replace(f, dest / f.name)
                    moved += 1

    if TRADES_CSV.exists():
        cutoff = today - timedelta(days=90)
        with TRADES_CSV.open() as fh:
            data = list(csv.reader(fh))
        if data:
            header, rows = data[0], data[1:]
            keep, old = [], []
            for r in rows:
                try:
                    d = datetime.fromisoformat(r[0]).date()
                except Exception:
                    keep.append(r)
                    continue
                (keep if d >= cutoff else old).append(r)
            if old:
                arch = ARCHIVE / f"trades_{today:%Y%m%d}.csv"
                write_header = not arch.exists()
                with arch.open("a", newline="") as fh:
                    w = csv.writer(fh)
                    if write_header:
                        w.writerow(header)
                    w.writerows(old)
                with TRADES_CSV.open("w", newline="") as fh:
                    w = csv.writer(fh)
                    w.writerow(header)
                    w.writerows(keep)
                moved += 1

    if SAFETY_LOG.exists() and SAFETY_LOG.stat().st_size > 5 * 1024 * 1024:
        os.replace(SAFETY_LOG, ARCHIVE / f"{today:%Y%m%d}_{SAFETY_LOG.name}")
        moved += 1

    print(f"Rotated {moved} file(s) to {ARCHIVE}/")


if __name__ == "__main__":
    main()