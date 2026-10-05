"""Deterministic schema lint of the data files that scripts parse.

A malformed edit to any of these silently breaks a launchd job or a digest.
These tests catch that before it ships — no AI, no network.
"""
import csv
import json

import yaml

from _util import REPO_ROOT, SKILLS, SCRIPTS

KNOWN_CADENCE_KEYS = {"hour", "minute", "weekdays_only", "day_of_week",
                      "every_n_weeks", "day", "months"}


def _load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def test_scheduled_jobs_yml_valid():
    data = _load_yaml(SCRIPTS / "scheduled-jobs.yml")
    assert data["default_mode"] in {"queue", "claude-headless"}
    assert isinstance(data["jobs"], list) and data["jobs"]
    for job in data["jobs"]:
        assert isinstance(job["id"], str) and job["id"]
        assert isinstance(job["skill"], str) and job["skill"]
        cad = job["cadence"]
        assert isinstance(cad, dict)
        assert set(cad) <= KNOWN_CADENCE_KEYS, f"{job['id']}: unknown cadence keys {set(cad) - KNOWN_CADENCE_KEYS}"
        # a cadence must resolve to a recognizable shape
        assert ("hour" in cad) or ("months" in cad) or ("day" in cad) or ("day_of_week" in cad)
        if "mode" in job:
            assert job["mode"] in {"queue", "claude-headless"}
        if "category" in job:
            # The category is passed to the wrapper as $6 and names the slice of
            # the skill to run. It must equal the job id — that one string is
            # also the config stem, roster stem, and digest filename segment.
            assert isinstance(job["category"], str) and job["category"]
            assert job["category"] == job["id"], (
                f"{job['id']}: category {job['category']!r} must equal the job id")


def test_stack_yml_valid():
    data = _load_yaml(SKILLS / "daily-cve-digest" / "stack.yml")
    assert "version" in data
    assert isinstance(data["ecosystems"], list) and data["ecosystems"]
    for eco in data["ecosystems"]:
        assert {"id", "name", "in_production"} <= set(eco)
    for lib in data["critical_libraries"]:
        assert {"ecosystem", "name"} <= set(lib)
    assert isinstance(data["severity_actions"], dict)


def test_source_registry_yml_valid():
    path = SKILLS / "source-registry" / "registry.yml"
    if not path.exists():
        import pytest
        pytest.skip("registry.yml not present")
    data = _load_yaml(path)
    ids = []
    for src in data["sources"]:
        assert {"id", "url"} <= set(src)
        tier = src.get("credibility_tier", data.get("default_credibility_tier"))
        assert tier in (1, 2, 3), f"{src['id']}: bad credibility_tier {tier}"
        ids.append(src["id"])
    assert len(ids) == len(set(ids)), "duplicate source ids"


def test_voices_csv_header():
    path = REPO_ROOT / "voices.csv"
    if not path.exists():
        import pytest
        pytest.skip("voices.csv not present")
    with open(path, newline="") as f:
        header = next(csv.reader(f))
    assert header[0] == "handle"
    assert "name" in header
    ncols = len(header)
    with open(path, newline="") as f:
        for i, row in enumerate(csv.reader(f)):
            if row:
                assert len(row) == ncols, f"row {i} has {len(row)} cols, expected {ncols}"


def test_evolve_yaml_valid():
    data = _load_yaml(REPO_ROOT / ".evolve.yaml")
    assert data["layout"] in {"auto", "single", "multi", "marketplace"}
    assert data["checks"]["plugin_manifests"] == ["claude"]


def test_plugin_json_valid():
    with open(REPO_ROOT / ".claude-plugin" / "plugin.json") as f:
        data = json.load(f)
    assert data["name"] == "research-bot"
    # strict semver x.y.z
    parts = data["version"].split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)
    assert data.get("description")
