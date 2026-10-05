#!/usr/bin/env python3
"""
schedule-sync.py — declarative deploy + install/uninstall for scheduled jobs.

Two-step flow on every run:

  1. DEPLOY: copy operational scripts and the config from the repo to
     ~/Library/Application Support/research-bot/ — a TCC-unprotected location
     where launchd-spawned bash can read them without any Documents-folder
     permission grant.

  2. RECONCILE: generate one ~/Library/LaunchAgents/research-bot.{job-id}.plist
     per job (referencing the DEPLOYED scripts) + one research-bot.catch-up.plist.
     Load new/changed via `launchctl bootstrap`; unload + remove orphans via
     `launchctl bootout`. Idempotent.

State is implicit: the set of `research-bot.*.plist` files on disk IS the install
state. The deploy step ensures the deployed copies match the repo source.

Re-run schedule-sync.py whenever you:
  - edit scheduled-jobs.yml (add/remove jobs, change cadences)
  - edit run-scheduled-job.sh, catch-up-missed-runs.sh, or _catch_up_helper.py
    (these are deployed; sync copies them to the deploy location)

Usage:
    python3 scripts/schedule-sync.py             # deploy + sync (idempotent)
    python3 scripts/schedule-sync.py --dry-run   # report only
    python3 scripts/schedule-sync.py --remove-all  # uninstall every job
"""

import argparse
import filecmp
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

PLIST_PREFIX = "research-bot."
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
BASE_DIR = Path.home() / "Library" / "Application Support" / "research-bot"
DEPLOY_SCRIPTS_DIR = BASE_DIR / "scripts"
DEPLOY_STATE_DIR = BASE_DIR / "state"
DEPLOY_CFG = BASE_DIR / "scheduled-jobs.yml"
CATCH_UP_LABEL = f"{PLIST_PREFIX}catch-up"
LOG_DIR_DEFAULT = Path.home() / "Library" / "Logs" / "research-bot"
QUEUE_DIR_DEFAULT = Path.home() / "Obsidian" / "Research-Brain" / "_inbox" / "scheduled-jobs"

# Files in <repo>/scripts/ that get DEPLOYED to ~/Library/Application Support/research-bot/scripts/
DEPLOYABLE_SCRIPTS = (
    "run-scheduled-job.sh",
    "catch-up-missed-runs.sh",
    "_catch_up_helper.py",
)

DOW_MAP_LAUNCHD = {
    "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
    "thursday": 4, "friday": 5, "saturday": 6,
}


def cadence_to_calendar_intervals(cadence: dict) -> list:
    hour = cadence.get("hour", 0)
    minute = cadence.get("minute", 0)
    out = []

    months = cadence.get("months")
    if months:
        day = cadence.get("day", 1)
        for m in months:
            out.append({"Month": int(m), "Day": int(day), "Hour": int(hour), "Minute": int(minute)})
        return out

    if "day" in cadence:
        out.append({"Day": int(cadence["day"]), "Hour": int(hour), "Minute": int(minute)})
        return out

    dow_name = cadence.get("day_of_week")
    if dow_name:
        wd = DOW_MAP_LAUNCHD[dow_name.lower()]
        out.append({"Weekday": wd, "Hour": int(hour), "Minute": int(minute)})
        return out

    if cadence.get("weekdays_only"):
        for wd in (1, 2, 3, 4, 5):
            out.append({"Weekday": wd, "Hour": int(hour), "Minute": int(minute)})
        return out

    out.append({"Hour": int(hour), "Minute": int(minute)})
    return out


def plist_env(log_dir: Path, queue_dir: Path) -> dict:
    """Operational paths baked into every plist.

    The wrapper scripts are bash and cannot parse scheduled-jobs.yml, so sync
    resolves `log_dir` / `queue_dir` once and passes them through launchd. Each
    script keeps a hardcoded fallback so manual invocation still works.
    """
    return {
        "RESEARCH_BOT_LOG_DIR": str(log_dir),
        "RESEARCH_BOT_QUEUE_DIR": str(queue_dir),
    }


def build_job_plist(job: dict, default_mode: str, log_dir: Path, queue_dir: Path) -> dict:
    job_id = job["id"]
    skill = job["skill"]
    mode = job.get("mode", default_mode)
    timeout = int(job.get("timeout_seconds", 600))
    every_n = int(job["cadence"].get("every_n_weeks", 1))

    # $6 (category) is always appended, empty for uncategorized jobs, so the
    # wrapper's `set -u` never sees an unset positional.
    program_args = [
        "/bin/bash",
        str(DEPLOY_SCRIPTS_DIR / "run-scheduled-job.sh"),
        job_id, mode, skill, str(timeout), str(every_n),
        str(job.get("category", "")),
    ]
    log_file = str(log_dir / f"{job_id}.log")
    intervals = cadence_to_calendar_intervals(job["cadence"])
    sci = intervals[0] if len(intervals) == 1 else intervals

    return {
        "Label": f"{PLIST_PREFIX}{job_id}",
        "ProgramArguments": program_args,
        "EnvironmentVariables": plist_env(log_dir, queue_dir),
        "StartCalendarInterval": sci,
        "StandardOutPath": log_file,
        "StandardErrorPath": log_file,
        "RunAtLoad": False,
    }


def build_catch_up_plist(log_dir: Path, queue_dir: Path) -> dict:
    log_file = str(log_dir / "catch-up.log")
    return {
        "Label": CATCH_UP_LABEL,
        "ProgramArguments": [
            "/bin/bash",
            str(DEPLOY_SCRIPTS_DIR / "catch-up-missed-runs.sh"),
        ],
        "EnvironmentVariables": plist_env(log_dir, queue_dir),
        "RunAtLoad": True,
        "StartInterval": 3600,
        "StandardOutPath": log_file,
        "StandardErrorPath": log_file,
    }


def plist_bytes(d: dict) -> bytes:
    return plistlib.dumps(d, fmt=plistlib.FMT_XML, sort_keys=True)


def launchctl_bootstrap(plist_path: Path):
    uid = os.getuid()
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
                   check=False, capture_output=True)


def launchctl_bootout(label: str):
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                   check=False, capture_output=True)


def deploy_operational_files(repo_root: Path, dry_run: bool) -> tuple:
    """Copy operational scripts + config from repo to deploy dir.
    Returns (copied, unchanged) counts."""
    copied = unchanged = 0
    DEPLOY_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True) if not dry_run else None
    DEPLOY_STATE_DIR.mkdir(parents=True, exist_ok=True) if not dry_run else None

    # Scripts
    for name in DEPLOYABLE_SCRIPTS:
        src = repo_root / "scripts" / name
        dst = DEPLOY_SCRIPTS_DIR / name
        if not src.exists():
            continue
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            print(f"  UNCHANGED  scripts/{name}")
            unchanged += 1
            continue
        verb = "would-deploy" if dry_run else "DEPLOYED"
        print(f"  {verb}   scripts/{name}")
        if not dry_run:
            shutil.copy2(src, dst)
            os.chmod(dst, 0o755)
            copied += 1

    # Config
    src_cfg = repo_root / "scripts" / "scheduled-jobs.yml"
    if src_cfg.exists():
        if DEPLOY_CFG.exists() and filecmp.cmp(src_cfg, DEPLOY_CFG, shallow=False):
            print(f"  UNCHANGED  scheduled-jobs.yml")
            unchanged += 1
        else:
            verb = "would-deploy" if dry_run else "DEPLOYED"
            print(f"  {verb}   scheduled-jobs.yml")
            if not dry_run:
                shutil.copy2(src_cfg, DEPLOY_CFG)
                copied += 1

    return copied, unchanged


def migrate_legacy_state(repo_root: Path, dry_run: bool):
    """If state files exist in the old <repo>/.state/schedule/ location, move them
    to the new deploy location at ~/Library/Application Support/research-bot/state/."""
    legacy = repo_root / ".state" / "schedule"
    if not legacy.exists():
        return
    files = list(legacy.iterdir())
    if not files:
        return
    print(f"  MIGRATING  {len(files)} state files from {legacy} → {DEPLOY_STATE_DIR}")
    if dry_run:
        return
    DEPLOY_STATE_DIR.mkdir(parents=True, exist_ok=True)
    for f in files:
        dst = DEPLOY_STATE_DIR / f.name
        if not dst.exists():
            shutil.copy2(f, dst)
        f.unlink()
    try:
        legacy.rmdir()
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, do not change anything")
    ap.add_argument("--remove-all", action="store_true",
                    help="uninstall every research-bot.* launch agent and exit")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    cfg_path = repo_root / "scripts" / "scheduled-jobs.yml"

    if not cfg_path.exists():
        print(f"ERROR: missing {cfg_path}", file=sys.stderr)
        sys.exit(1)

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    default_mode = cfg.get("default_mode", "queue")
    log_dir = Path(os.path.expanduser(cfg.get("log_dir", str(LOG_DIR_DEFAULT))))
    queue_dir = Path(os.path.expanduser(cfg.get("queue_dir", str(QUEUE_DIR_DEFAULT))))
    catch_up_enabled = cfg.get("catch_up_on_login", True)

    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    if not args.dry_run:
        log_dir.mkdir(parents=True, exist_ok=True)

    existing = {p.stem: p for p in LAUNCH_AGENTS_DIR.glob(f"{PLIST_PREFIX}*.plist")}

    if args.remove_all:
        print(f"--remove-all: uninstalling {len(existing)} agents")
        for label, path in existing.items():
            if args.dry_run:
                print(f"  [dry-run] would remove {label}")
                continue
            launchctl_bootout(label)
            path.unlink()
            print(f"  REMOVED  {label}")
        return

    print(f"=== Phase 1: deploy operational files → {BASE_DIR} ===")
    deploy_operational_files(repo_root, args.dry_run)
    migrate_legacy_state(repo_root, args.dry_run)

    print(f"\n=== Phase 2: reconcile launchd plists ===")
    desired = {}
    for job in cfg["jobs"]:
        label = f"{PLIST_PREFIX}{job['id']}"
        desired[label] = build_job_plist(job, default_mode, log_dir, queue_dir)
    if catch_up_enabled:
        desired[CATCH_UP_LABEL] = build_catch_up_plist(log_dir, queue_dir)

    counts = {"created": 0, "updated": 0, "removed": 0, "unchanged": 0}
    actions = []

    for label, plist in desired.items():
        path = LAUNCH_AGENTS_DIR / f"{label}.plist"
        new_bytes = plist_bytes(plist)
        if not path.exists():
            actions.append(("CREATED", label, path, new_bytes))
            counts["created"] += 1
        else:
            old_bytes = path.read_bytes()
            if old_bytes != new_bytes:
                actions.append(("UPDATED", label, path, new_bytes))
                counts["updated"] += 1
            else:
                actions.append(("UNCHANGED", label, path, None))
                counts["unchanged"] += 1

    for label, path in existing.items():
        if label not in desired:
            actions.append(("REMOVED", label, path, None))
            counts["removed"] += 1

    for verb, label, path, body in actions:
        if verb == "UNCHANGED":
            print(f"  {verb:<9} {label}")
            continue
        print(f"  {verb:<9} {label}  ({path.name})")
        if args.dry_run:
            continue
        if verb == "REMOVED":
            launchctl_bootout(label)
            path.unlink()
        else:
            if verb == "UPDATED":
                launchctl_bootout(label)
            path.write_bytes(body)
            os.chmod(path, 0o644)
            launchctl_bootstrap(path)

    print()
    print(f"=== schedule-sync summary{'  (dry-run)' if args.dry_run else ''} ===")
    print(f"  created:   {counts['created']}")
    print(f"  updated:   {counts['updated']}")
    print(f"  removed:   {counts['removed']}")
    print(f"  unchanged: {counts['unchanged']}")
    print(f"  catch-up:  {'enabled' if catch_up_enabled else 'disabled'}")
    print(f"  deploy:    {BASE_DIR}")


if __name__ == "__main__":
    main()
