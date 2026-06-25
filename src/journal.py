"""The Obsidian brain: append plain-English entries to journal.md, and ping
Telegram with the same event so you see it live on your phone.

Called by cycle.py on every meaningful decision. Once a week you have Claude
read journal.md and pull out patterns.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.notify import notify

ET = ZoneInfo("America/New_York")
JOURNAL_PATH = Path("journal.md")


def log(title, body=""):
    ts = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    entry = f"\n### {ts} - {title}\n"
    if body:
        entry += f"{body}\n"
    try:
        with JOURNAL_PATH.open("a") as f:
            f.write(entry)
    except Exception:
        pass  # the journal is never allowed to break trading logic
    try:
        notify(title, body)
    except Exception:
        pass  # nor is the phone alert