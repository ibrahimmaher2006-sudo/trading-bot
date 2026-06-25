"""Register the bot's scheduled jobs with macOS launchd.

Creates LaunchAgent plists in ~/Library/LaunchAgents and loads them:
  cycle      every 5 minutes, all day (cycle.py self-gates to NY market hours)
  prefilter  7x through the morning (09:55-12:55 ET)
  rotate     once before the open (09:25 ET)
  dashboard  once after the close (16:05 ET)

ET times are converted to your Mac's local time at generation, so re-run this
after US daylight-saving changes (March / November) to keep the times correct.
"""

import plistlib
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PROJECT_DIR = Path.cwd()
VENV_PY = PROJECT_DIR / ".venv" / "bin" / "python"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = PROJECT_DIR / "logs"
PREFIX = "com.humbledtrader."


def et_local(h, m):
    """An ET time-of-day expressed as the Mac's local Hour/Minute for launchd."""
    t = datetime.now(ET).replace(hour=h, minute=m, second=0, microsecond=0)
    loc = t.astimezone()
    return {"Hour": loc.hour, "Minute": loc.minute}


def base(label, script):
    return {
        "Label": PREFIX + label,
        "ProgramArguments": [str(VENV_PY), str(PROJECT_DIR / script)],
        "WorkingDirectory": str(PROJECT_DIR),
        "StandardOutPath": str(LOG_DIR / f"{label}.out.log"),
        "StandardErrorPath": str(LOG_DIR / f"{label}.err.log"),
        "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    }


def write_and_load(plist):
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    path = LAUNCH_AGENTS / f"{plist['Label']}.plist"
    with path.open("wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    res = subprocess.run(["launchctl", "load", "-w", str(path)], capture_output=True, text=True)
    print(f"  {plist['Label']}: {'loaded' if res.returncode == 0 else 'FAILED ' + res.stderr.strip()}")


def main():
    LOG_DIR.mkdir(exist_ok=True)
    print(f"Project: {PROJECT_DIR}")
    print(f"Python:  {VENV_PY}\nRegistering launchd agents...")

    cyc = base("cycle", "cycle.py")
    cyc["StartInterval"] = 300                      # every 5 min, self-gates
    write_and_load(cyc)

    pre = base("prefilter", "morning_prefilter.py")
    pre["StartCalendarInterval"] = [et_local(h, m) for h, m in
                                    [(9, 55), (10, 25), (10, 55), (11, 25),
                                     (11, 55), (12, 25), (12, 55)]]
    write_and_load(pre)

    rot = base("rotate", "rotate_logs.py")
    rot["StartCalendarInterval"] = et_local(9, 25)
    write_and_load(rot)

    dash = base("dashboard", "compute_perf.py")
    dash["StartCalendarInterval"] = et_local(16, 5)
    write_and_load(dash)

    print("\nDone. The cycle runs every 5 minutes and self-gates to NY market hours.")
    print("Re-run this after US daylight-saving changes to fix the calendar times.")


if __name__ == "__main__":
    main()