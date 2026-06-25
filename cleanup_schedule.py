"""Unload and remove all of the bot's launchd agents. Safe to re-run."""

import subprocess
from pathlib import Path

LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
PREFIX = "com.humbledtrader."


def main():
    found = sorted(LAUNCH_AGENTS.glob(f"{PREFIX}*.plist"))
    if not found:
        print("Nothing to clean.")
        return
    for path in found:
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        path.unlink()
        print(f"Removed {path.name}")
    print(f"CLEANUP DONE: {len(found)} agent(s) removed.")


if __name__ == "__main__":
    main()