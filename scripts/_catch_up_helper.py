#!/usr/bin/env python3
"""
_catch_up_helper.py — invoked by catch-up-missed-runs.sh.

DEPLOYED to ~/Library/Application Support/research-bot/scripts/ — source of truth
is the version in the repo. Re-run schedule-sync.py to deploy edits.

Takes <base-dir> as arg. Reads {base-dir}/scheduled-jobs.yml and state files at
{base-dir}/state/. Invokes the deployed wrapper at {base-dir}/scripts/run-scheduled-job.sh.

With --expire, skips catch-up and instead deletes queue markers older than their
job's cadence-based expiry window (see EXPIRY_DAYS). Markers whose job id isn't
in scheduled-jobs.yml are never auto-deleted.
"""

import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

LOG_DIR_DEFAULT = "~/Library/Logs/research-bot"
QUEUE_DIR_DEFAULT = "~/Obsidian/Research-Brain/_inbox/scheduled-jobs"

DOW_MAP = {
    "sunday": 6, "monday": 0, "tuesday": 1, "wednesday": 2,
    "thursday": 3, "friday": 4, "saturday": 5,
}

# Marker auto-expiry: a queue marker older than its job's window is stale —
# the next scheduled fire has already superseded it (or will imminently).
EXPIRY_DAYS = {
    "daily": 3,       # daily + weekdays_only cadences
    "weekly": 14,
    "biweekly": 21,
    "monthly": 45,
    "quarterly": 120,  # any months-list cadence
}


def most_recent_fire(cadence: dict, now: datetime):
    hour = cadence.get("hour", 0)
    minute = cadence.get("minute", 0)

    months = cadence.get("months")
    if months:
        day = cadence.get("day", 1)
        for delta in range(0, 366):
            cand = (now - timedelta(days=delta))
            if cand.month not in months or cand.day != day:
                continue
            cand = cand.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if cand <= now:
                return cand
        return None

    if "day" in cadence:
        day = cadence["day"]
        for delta in range(0, 62):
            cand = (now - timedelta(days=delta))
            if cand.day != day:
                continue
            cand = cand.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if cand <= now:
                return cand
        return None

    dow_name = cadence.get("day_of_week")
    if dow_name:
        target = DOW_MAP[dow_name.lower()]
        for delta in range(0, 14):
            cand = (now - timedelta(days=delta))
            if cand.weekday() != target:
                continue
            cand = cand.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if cand > now:
                continue
            return cand
        return None

    weekdays_only = cadence.get("weekdays_only", False)
    for delta in range(0, 14):
        cand = (now - timedelta(days=delta))
        cand = cand.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if cand > now:
            continue
        if weekdays_only and cand.weekday() >= 5:
            continue
        return cand
    return None


def cadence_kind(cadence: dict) -> str:
    """Classify a scheduled-jobs.yml cadence dict into an EXPIRY_DAYS key."""
    if cadence.get("months"):
        return "quarterly"
    if "day" in cadence:
        return "monthly"
    if cadence.get("day_of_week"):
        return "biweekly" if cadence.get("every_n_weeks", 1) > 1 else "weekly"
    return "daily"  # plain daily and weekdays_only both expire on the daily window


def expiry_days(cadence: dict) -> int:
    return EXPIRY_DAYS[cadence_kind(cadence)]


def parse_marker_filename(filename: str):
    """Split a 'YYYY-MM-DD-{job-id}.md' marker filename into (date, job_id).

    Returns (None, None) for anything that doesn't match the marker shape.
    """
    if not filename.endswith(".md"):
        return None, None
    stem = filename[:-3]
    if len(stem) < 12 or stem[10] != "-":
        return None, None
    try:
        marker_date = datetime.strptime(stem[:10], "%Y-%m-%d").date()
    except ValueError:
        return None, None
    return marker_date, stem[11:]


def expired_markers(marker_filenames, jobs_config: dict, today: date):
    """Pure expiry policy: which queue markers are stale enough to delete?

    A marker expires when its date is strictly older than its job's cadence
    window (EXPIRY_DAYS). Returns (expired, preserved_unknown): markers whose
    job id isn't in jobs_config — or whose filename doesn't parse — are never
    expired; they come back in preserved_unknown for logging.
    """
    jobs_by_id = {j["id"]: j for j in jobs_config.get("jobs", [])}
    expired, preserved_unknown = [], []
    for filename in marker_filenames:
        marker_date, job_id = parse_marker_filename(filename)
        if marker_date is None or job_id not in jobs_by_id:
            preserved_unknown.append(filename)
            continue
        if (today - marker_date).days > expiry_days(jobs_by_id[job_id]["cadence"]):
            expired.append(filename)
    return expired, preserved_unknown


def past_expiry(cadence: dict, expected: datetime, now: datetime) -> bool:
    """True when a missed fire is already past its marker-expiry window.

    Guard for catch-up: retro-writing a marker for such a run would recreate
    exactly what expiry just deleted.
    """
    return (now.date() - expected.date()).days > expiry_days(cadence)


def build_wrapper_env(cfg: dict) -> dict:
    """Environment for a catch-up wrapper invocation.

    The wrapper reads its log/queue paths from these vars (schedule-sync.py bakes
    the same pair into every plist). Resolving them here from the same config
    keeps a catch-up-fired run writing to the same places as a launchd-fired one.
    """
    env = dict(os.environ)
    env["RESEARCH_BOT_LOG_DIR"] = str(
        Path(cfg.get("log_dir", LOG_DIR_DEFAULT)).expanduser())
    env["RESEARCH_BOT_QUEUE_DIR"] = str(
        Path(cfg.get("queue_dir", QUEUE_DIR_DEFAULT)).expanduser())
    return env


def run_expiry(cfg: dict, today: date):
    """Delete expired queue markers. Invoked hourly after the catch-up pass."""
    queue_dir = Path(cfg.get("queue_dir", QUEUE_DIR_DEFAULT)).expanduser()
    if not queue_dir.is_dir():
        print(f"  expiry: queue dir not found ({queue_dir}) — nothing to do")
        return
    filenames = sorted(p.name for p in queue_dir.glob("*.md"))
    expired, preserved_unknown = expired_markers(filenames, cfg, today)
    for filename in expired:
        (queue_dir / filename).unlink()
        print(f"  expired marker deleted: {filename}")
    for filename in preserved_unknown:
        print(f"  expiry: unknown/unparseable marker preserved: {filename}")
    kept = len(filenames) - len(expired)
    print(f"=== expiry summary: {len(expired)} deleted, {kept} kept "
          f"({len(preserved_unknown)} unknown preserved) ===")


def read_last_run(state_dir: Path, job_id: str):
    p = state_dir / f"{job_id}.last-run"
    if not p.exists():
        return None
    try:
        return datetime.fromisoformat(p.read_text().strip().replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def main():
    args = [a for a in sys.argv[1:] if a != "--expire"]
    expire_only = "--expire" in sys.argv[1:]
    if len(args) < 1:
        print("usage: _catch_up_helper.py <base-dir> [--expire]", file=sys.stderr)
        sys.exit(64)

    base_dir = Path(args[0]).resolve()
    cfg_path = base_dir / "scheduled-jobs.yml"
    scripts_dir = base_dir / "scripts"
    state_dir = base_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    if expire_only:
        run_expiry(cfg, date.today())
        return

    default_mode = cfg.get("default_mode", "queue")
    wrapper = scripts_dir / "run-scheduled-job.sh"
    wrapper_env = build_wrapper_env(cfg)

    now = datetime.utcnow()
    caught_up = skipped = no_state = 0

    for job in cfg["jobs"]:
        job_id = job["id"]
        skill = job["skill"]
        mode = job.get("mode", default_mode)
        timeout = job.get("timeout_seconds", 600)
        every_n = job["cadence"].get("every_n_weeks", 1)

        expected = most_recent_fire(job["cadence"], now)
        if expected is None:
            print(f"  {job_id}: no past scheduled fire — skip")
            skipped += 1
            continue

        last_run = read_last_run(state_dir, job_id)
        if last_run is not None and last_run >= expected:
            print(f"  {job_id}: up to date (last={last_run.isoformat()}, expected={expected.isoformat()})")
            skipped += 1
            continue

        # No-backfill-past-expiry guard: a missed run older than its marker
        # expiry window would just recreate a marker expiry deletes.
        if past_expiry(job["cadence"], expected, now):
            print(f"  {job_id}: missed fire {expected.isoformat()} is past its "
                  f"{expiry_days(job['cadence'])}-day expiry window — skip backfill")
            skipped += 1
            continue

        if last_run is None:
            print(f"  {job_id}: no state — first time; firing catch-up for {expected.isoformat()}")
            no_state += 1
        else:
            print(f"  {job_id}: MISSED (last={last_run.isoformat()}, expected={expected.isoformat()}) — firing catch-up")

        result = subprocess.run(
            ["bash", str(wrapper), job_id, mode, skill, str(timeout), str(every_n),
             str(job.get("category", ""))],
            capture_output=True, text=True, env=wrapper_env,
        )
        print(f"    wrapper exit={result.returncode}")
        if result.stderr:
            print(f"    stderr: {result.stderr.strip()}")
        caught_up += 1

    print(f"=== catch-up summary: {caught_up} fired, {skipped} skipped, {no_state} first-time ===")


if __name__ == "__main__":
    main()
