"""Push notifications to your phone via Telegram (with an optional ntfy fallback).

Reads credentials from .env. Fire-and-forget: a failure here never breaks the bot.
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
NOTIFY_URL = os.environ.get("NOTIFY_URL", "").strip()
LOG_DIR = Path("logs")


def _log_error(exc):
    try:
        LOG_DIR.mkdir(exist_ok=True)
        with (LOG_DIR / "notify_errors.log").open("a") as f:
            f.write(f"{exc}\n")
    except Exception:
        pass


def notify(title, body, priority="default"):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": f"*{title}*\n{body}",
                    "parse_mode": "Markdown",
                },
                timeout=5,
            )
        except Exception as exc:
            _log_error(exc)

    if NOTIFY_URL:
        try:
            requests.post(
                NOTIFY_URL,
                data=body.encode("utf-8"),
                headers={"Title": title, "Priority": priority},
                timeout=5,
            )
        except Exception as exc:
            _log_error(exc)