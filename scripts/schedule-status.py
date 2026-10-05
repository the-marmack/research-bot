#!/usr/bin/env python3
"""
schedule-status.py — read-only status of the toolkit's scheduled jobs.

Reports per-job:
  - cadence (from yml)
  - install state (plist exists? launchctl loaded?)
  - last run timestamp + last exit code (from state files)
  - last log line (from log file)
  - next scheduled fire (best-effort computation)

Plus: lists any orphan research-bot.* plists on disk that aren't in the config
(drift) so you know to run schedule-sync.py.
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

PLIST_PREFIX = "research-bot."
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
BASE_DIR = Path.home() / "Library" / "Application Support" / "research-bot"
DEPLOY_STATE_DIR = BASE_DIR / "state"
LOG_DIR_DEFAULT = Path.home() / "Library" / "Logs" / "research-bot"


DOW_MAP_NAME = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def next_fire(cadence: dict, now: datetime) -> datetime:
    """Next fire time strictly > now, approximate. Mirrors most_recent_fire."""
    hour = cadence.get("hour", 0)
    minute = cadence.get("minute", 0)

    months = cadence.get("months")
    if months:
        day = cadence.get("day", 1)
        for delta in range(0, 400):
            cand = (now + timedelta(days=delta))
            if cand.month not in months or cand.day != day:
                continue
            cand = cand.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if cand > now:
                return cand
        return None

    if "day" in cadence:
        day = cadence["day"]
        for delta in range(0, 62):
            cand = (now + timedelta(days=delta))
            if cand.day != day:
                continue
            cand = cand.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if cand > now:
                return cand
        return None

    dow_name = cadence.get("day_of_week")
    if dow_name:
        target = DOW_MAP_NAME[dow_name.lower()]
        for delta in range(0, 14):
            cand = (now + timedelta(days=delta))
            if cand.weekday() != target:
                continue
            cand = cand.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if cand > now:
                return cand
        return None

    weekdays_only = cadence.get("weekdays_only", False)
    for delta in range(0, 14):
        cand = (now + timedelta(days=delta))
        cand = cand.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if cand <= now:
            continue
        if weekdays_only and cand.weekday() >= 5:
            continue
        return cand
    return None


def get_launchctl_loaded() -> set:
    """Return set of labels currently loaded in launchctl."""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=False).stdout
        labels = set()
        for line in out.splitlines()[1:]:
            parts = line.split()
            if not parts:
                continue
            label = parts[-1]
            if label.startswith(PLIST_PREFIX):
                labels.add(label)
        return labels
    except Exception:
        return set()


def read_state(state_dir: Path, job_id: str) -> tuple:
    last_run = state_dir / f"{job_id}.last-run"
    last_exit = state_dir / f"{job_id}.last-exit-code"
    lr = last_run.read_text().strip() if last_run.exists() else "—"
    ec = last_exit.read_text().strip() if last_exit.exists() else "—"
    return lr, ec


def last_log_line(log_dir: Path, job_id: str) -> str:
    p = log_dir / f"{job_id}.log"
    if not p.exists():
        return ""
    try:
        lines = p.read_text().splitlines()
        for ln in reversed(lines):
            if ln.strip():
                return ln.strip()[-120:]
    except Exception:
        pass
    return ""


def main():
    repo_root = Path(__file__).resolve().parent.parent
    cfg_path = repo_root / "scripts" / "scheduled-jobs.yml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    # State + logs live in the deployed location (TCC-unprotected). Status
    # reads from the deployed paths so it shows the same numbers launchd uses.
    log_dir = Path(cfg.get("log_dir", str(LOG_DIR_DEFAULT))).expanduser()
    state_dir = DEPLOY_STATE_DIR
    default_mode = cfg.get("default_mode", "queue")
    catch_up_enabled = cfg.get("catch_up_on_login", True)

    loaded = get_launchctl_loaded()
    on_disk = {p.stem for p in LAUNCH_AGENTS_DIR.glob(f"{PLIST_PREFIX}*.plist")}
    now = datetime.utcnow()

    print(f"=== research-bot scheduled jobs status — {now.isoformat()}Z ===")
    print(f"Config:   {cfg_path}")
    print(f"Default mode:  {default_mode}")
    print(f"Catch-up:      {'enabled' if catch_up_enabled else 'disabled'}")
    print()

    header = f"  {'job-id':<32}  {'mode':<14}  {'next fire (UTC)':<20}  {'last run':<22}  exit  installed?"
    print(header)
    print("  " + "-" * (len(header) - 2))

    desired_labels = set()
    for job in cfg["jobs"]:
        job_id = job["id"]
        mode = job.get("mode", default_mode)
        label = f"{PLIST_PREFIX}{job_id}"
        desired_labels.add(label)
        nxt = next_fire(job["cadence"], now)
        nxt_s = nxt.strftime("%Y-%m-%d %H:%M") if nxt else "—"
        last_run, exit_code = read_state(state_dir, job_id)
        if last_run != "—":
            last_run = last_run[:19]
        on_disk_ok = label in on_disk
        loaded_ok = label in loaded
        install_state = (
            "ok" if (on_disk_ok and loaded_ok)
            else "on-disk only" if on_disk_ok
            else "MISSING"
        )
        print(f"  {job_id:<32}  {mode:<14}  {nxt_s:<20}  {last_run:<22}  {exit_code:<4}  {install_state}")

    # Catch-up agent
    if catch_up_enabled:
        label = f"{PLIST_PREFIX}catch-up"
        desired_labels.add(label)
        on_disk_ok = label in on_disk
        loaded_ok = label in loaded
        install_state = (
            "ok" if (on_disk_ok and loaded_ok)
            else "on-disk only" if on_disk_ok
            else "MISSING"
        )
        print(f"  {'catch-up':<32}  {'(hourly+login)':<14}  {'(continuous)':<20}  {'—':<22}  {'—':<4}  {install_state}")

    # Orphans
    orphans = on_disk - desired_labels
    if orphans:
        print()
        print("⚠  ORPHAN plists on disk that aren't in config (run schedule-sync.py to remove):")
        for label in sorted(orphans):
            print(f"   - {label}")

    # Last log lines (compact)
    print()
    print("Recent log activity:")
    for job in cfg["jobs"]:
        line = last_log_line(log_dir, job["id"])
        if line:
            print(f"  {job['id']:<32}  {line}")


if __name__ == "__main__":
    main()
