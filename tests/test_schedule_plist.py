"""Light tests for the launchd plist builders (pure dict construction)."""
from pathlib import Path

from _util import SCRIPTS, load_module

sync = load_module(SCRIPTS / "schedule-sync.py", "schedule_sync_plist")
LOGS = Path("/tmp/logs")
QUEUE = Path("/tmp/queue")


def test_build_job_plist_shape():
    job = {"id": "daily-cve-digest", "skill": "daily-cve-digest",
           "cadence": {"hour": 7, "minute": 0, "weekdays_only": True},
           "timeout_seconds": 600}
    d = sync.build_job_plist(job, "queue", LOGS, QUEUE)
    assert d["Label"].endswith("daily-cve-digest")
    assert d["RunAtLoad"] is False
    assert d["ProgramArguments"][0] == "/bin/bash"
    assert d["ProgramArguments"][1].endswith("run-scheduled-job.sh")
    assert d["ProgramArguments"][2] == "daily-cve-digest"  # job id
    assert d["ProgramArguments"][4] == "daily-cve-digest"  # skill
    # weekdays_only -> a list of five calendar intervals
    assert isinstance(d["StartCalendarInterval"], list)
    assert len(d["StartCalendarInterval"]) == 5


def test_single_interval_is_dict_not_list():
    job = {"id": "voices-watcher", "skill": "voices-watcher",
           "cadence": {"hour": 7, "minute": 30}}
    d = sync.build_job_plist(job, "queue", LOGS, QUEUE)
    assert d["StartCalendarInterval"] == {"Hour": 7, "Minute": 30}


def test_mode_defaults_and_override():
    base = {"id": "x", "skill": "x", "cadence": {"hour": 1, "minute": 0}}
    assert sync.build_job_plist(base, "queue", LOGS, QUEUE)["ProgramArguments"][3] == "queue"
    override = dict(base, mode="claude-headless")
    assert sync.build_job_plist(
        override, "queue", LOGS, QUEUE)["ProgramArguments"][3] == "claude-headless"


def test_plist_bytes_deterministic():
    job = {"id": "x", "skill": "x", "cadence": {"hour": 1, "minute": 2}}
    d = sync.build_job_plist(job, "queue", LOGS, QUEUE)
    assert sync.plist_bytes(d) == sync.plist_bytes(d)


def test_catch_up_plist():
    d = sync.build_catch_up_plist(LOGS, QUEUE)
    assert d["RunAtLoad"] is True
    assert d["StartInterval"] == 3600
    assert d["ProgramArguments"][1].endswith("catch-up-missed-runs.sh")


# --- operational paths carried through launchd (Phase 0) ---------------------
# The wrapper scripts are bash and can't parse scheduled-jobs.yml, so sync
# resolves log_dir/queue_dir once and passes them via EnvironmentVariables.

def test_job_plist_carries_operational_paths():
    job = {"id": "x", "skill": "x", "cadence": {"hour": 1, "minute": 0}}
    env = sync.build_job_plist(job, "queue", LOGS, QUEUE)["EnvironmentVariables"]
    assert env["RESEARCH_BOT_LOG_DIR"] == str(LOGS)
    assert env["RESEARCH_BOT_QUEUE_DIR"] == str(QUEUE)


def test_catch_up_plist_carries_operational_paths():
    env = sync.build_catch_up_plist(LOGS, QUEUE)["EnvironmentVariables"]
    assert env["RESEARCH_BOT_LOG_DIR"] == str(LOGS)
    assert env["RESEARCH_BOT_QUEUE_DIR"] == str(QUEUE)


def test_category_arg_always_present_even_when_absent():
    """$6 is always passed so the wrapper's `set -u` never sees it unset."""
    job = {"id": "x", "skill": "x", "cadence": {"hour": 1, "minute": 0}}
    args = sync.build_job_plist(job, "queue", LOGS, QUEUE)["ProgramArguments"]
    assert len(args) == 8
    assert args[7] == ""


def test_category_arg_is_passed_through():
    job = {"id": "voices-ai", "skill": "voices-watcher", "category": "voices-ai",
           "cadence": {"hour": 7, "minute": 30}}
    args = sync.build_job_plist(job, "queue", LOGS, QUEUE)["ProgramArguments"]
    assert args[7] == "voices-ai"
    assert args[4] == "voices-watcher"  # skill stays a real skill dir


def test_two_jobs_on_one_skill_get_distinct_labels_and_logs():
    """Multiple jobs may share a skill; identity comes from `id`, not `skill`.

    This is what makes per-category fan-out onto a single skill possible.
    """
    a = sync.build_job_plist(
        {"id": "voices-ai", "skill": "voices-watcher",
         "cadence": {"hour": 7, "minute": 30}}, "queue", LOGS, QUEUE)
    b = sync.build_job_plist(
        {"id": "voices-security", "skill": "voices-watcher",
         "cadence": {"hour": 7, "minute": 35}}, "queue", LOGS, QUEUE)
    assert a["Label"] != b["Label"]
    assert a["StandardOutPath"] != b["StandardOutPath"]
    assert a["ProgramArguments"][4] == b["ProgramArguments"][4] == "voices-watcher"
