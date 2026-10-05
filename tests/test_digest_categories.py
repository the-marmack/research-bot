"""Tests for digest category configs and roster CSVs.

Two layers:

- **Hermetic** — exercise the parser/validator and the shipped `*.example.*`
  files. These run anywhere, including CI with no vault.
- **Vault-guarded** — assert the user's live categories and rosters are
  internally consistent. Skipped when no vault is present.
"""
import csv
import json
import textwrap
from pathlib import Path

import pytest
import yaml

from _util import REPO_ROOT, SCRIPTS, SKILLS, load_module

dc = load_module(SKILLS / "voices-watcher" / "digest_categories.py",
                 "digest_categories")
yf = load_module(SKILLS / "voices-watcher" / "youtube_feeds.py",
                 "youtube_feeds_roster")

VAULT = Path.home() / "Obsidian" / "Research-Brain"
CONFIG = VAULT / "_config"
EXAMPLE_CONFIG = SKILLS / "voices-watcher" / "digest-config.example.md"
EXAMPLE_ROSTER = SKILLS / "voices-watcher" / "roster.example.csv"


def write_category(tmp_path, stem, frontmatter, body=""):
    """Write a category config into a throwaway _config/digests/ tree."""
    digests = tmp_path / "digests"
    digests.mkdir(parents=True, exist_ok=True)
    p = digests / f"{stem}.md"
    p.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return p


VALID = textwrap.dedent("""\
    title: AI Voices
    id: voices-ai
    kind: voices
    digest: true
    email: true
    roster: rosters/voices-ai.csv
    cadence: daily
    tags: [digest]""")


def with_roster(tmp_path, name="voices-ai.csv"):
    rosters = tmp_path / "rosters"
    rosters.mkdir(parents=True, exist_ok=True)
    (rosters / name).write_text(
        ",".join(yf.ROSTER_COLUMNS) + "\n", encoding="utf-8")


# --- roster column contract --------------------------------------------------

def test_roster_columns_shape():
    assert yf.ROSTER_COLUMNS[0] == "handle"
    assert "name" in yf.ROSTER_COLUMNS
    assert len(yf.ROSTER_COLUMNS) == 12


def test_validate_roster_header_accepts_canonical():
    assert yf.validate_roster_header(list(yf.ROSTER_COLUMNS)) is None


def test_validate_roster_header_rejects_reordered():
    reordered = list(yf.ROSTER_COLUMNS)
    reordered[0], reordered[1] = reordered[1], reordered[0]
    problem = yf.validate_roster_header(reordered)
    assert problem and "wrong order" in problem


def test_validate_roster_header_rejects_missing_and_extra():
    assert "missing" in yf.validate_roster_header(["handle", "name"])
    assert "unexpected" in yf.validate_roster_header(
        list(yf.ROSTER_COLUMNS) + ["surprise"])


def test_validate_roster_header_rejects_none():
    assert yf.validate_roster_header(None) is not None


# --- category config parsing -------------------------------------------------

def test_valid_config_has_no_problems(tmp_path):
    with_roster(tmp_path)
    out = dc.load_one(write_category(tmp_path, "voices-ai", VALID), tmp_path)
    assert out["problems"] == []
    assert out["id"] == "voices-ai"


def test_id_must_match_filename_stem(tmp_path):
    with_roster(tmp_path)
    out = dc.load_one(write_category(tmp_path, "different-stem", VALID), tmp_path)
    assert any("filename stem" in p for p in out["problems"])


def test_email_true_with_digest_false_is_an_error(tmp_path):
    with_roster(tmp_path)
    fm = VALID.replace("digest: true", "digest: false")
    out = dc.load_one(write_category(tmp_path, "voices-ai", fm), tmp_path)
    assert any("email: true requires digest: true" in p for p in out["problems"])


def test_dormant_category_is_valid(tmp_path):
    """digest:false + email:false is the dormant state, not an error."""
    with_roster(tmp_path)
    fm = VALID.replace("digest: true", "digest: false").replace(
        "email: true", "email: false")
    out = dc.load_one(write_category(tmp_path, "voices-ai", fm), tmp_path)
    assert out["problems"] == []


def test_quoted_boolean_is_rejected(tmp_path):
    """'true' as a string would be truthy everywhere and silently wrong."""
    with_roster(tmp_path)
    fm = VALID.replace("digest: true", "digest: 'true'")
    out = dc.load_one(write_category(tmp_path, "voices-ai", fm), tmp_path)
    assert any("must be true or false" in p for p in out["problems"])


def test_unknown_cadence_is_rejected(tmp_path):
    with_roster(tmp_path)
    fm = VALID.replace("cadence: daily", "cadence: fortnightly")
    out = dc.load_one(write_category(tmp_path, "voices-ai", fm), tmp_path)
    assert any("cadence" in p for p in out["problems"])


def test_missing_roster_file_is_reported(tmp_path):
    out = dc.load_one(write_category(tmp_path, "voices-ai", VALID), tmp_path)
    assert any("roster not found" in p for p in out["problems"])


def test_missing_required_field_is_reported(tmp_path):
    with_roster(tmp_path)
    fm = "\n".join(l for l in VALID.splitlines() if not l.startswith("title:"))
    out = dc.load_one(write_category(tmp_path, "voices-ai", fm), tmp_path)
    assert any("'title'" in p for p in out["problems"])


def test_bad_id_characters_rejected(tmp_path):
    with_roster(tmp_path)
    fm = VALID.replace("id: voices-ai", "id: Voices_AI")
    p = write_category(tmp_path, "Voices_AI", fm)
    assert any("lowercase" in x for x in dc.load_one(p, tmp_path)["problems"])


def test_no_frontmatter_is_reported(tmp_path):
    digests = tmp_path / "digests"
    digests.mkdir(parents=True)
    p = digests / "voices-ai.md"
    p.write_text("# Just a heading\n", encoding="utf-8")
    assert any("frontmatter" in x for x in dc.load_one(p, tmp_path)["problems"])


def test_defaults_are_applied(tmp_path):
    with_roster(tmp_path)
    cfg = dc.load_one(write_category(tmp_path, "voices-ai", VALID),
                      tmp_path)["config"]
    assert cfg["max_items_per_voice"] == 3
    assert cfg["seed_people_notes"] is True
    assert cfg["email_list"] is None
    assert "substack" in cfg["surfaces"]


def test_explicit_values_override_defaults(tmp_path):
    with_roster(tmp_path)
    fm = VALID + "\nmax_items_per_voice: 10\nemail_list: security"
    cfg = dc.load_one(write_category(tmp_path, "voices-ai", fm),
                      tmp_path)["config"]
    assert cfg["max_items_per_voice"] == 10
    assert cfg["email_list"] == "security"


# --- framing extraction ------------------------------------------------------

def test_framing_section_is_extracted(tmp_path):
    with_roster(tmp_path)
    body = "# AI Voices\n\nintro prose\n\n## Framing\n\nTie to open questions.\n"
    out = dc.load_one(write_category(tmp_path, "voices-ai", VALID, body), tmp_path)
    assert out["framing"] == "Tie to open questions."


def test_framing_strips_html_comments(tmp_path):
    with_roster(tmp_path)
    body = "## Framing\n\n<!-- a note to self -->\nReal guidance.\n"
    out = dc.load_one(write_category(tmp_path, "voices-ai", VALID, body), tmp_path)
    assert "note to self" not in out["framing"]
    assert "Real guidance." in out["framing"]


def test_framing_stops_at_next_h2(tmp_path):
    with_roster(tmp_path)
    body = "## Framing\n\nkeep this\n\n## Notes\n\ndrop this\n"
    out = dc.load_one(write_category(tmp_path, "voices-ai", VALID, body), tmp_path)
    assert "keep this" in out["framing"]
    assert "drop this" not in out["framing"]


def test_framing_absent_is_empty(tmp_path):
    with_roster(tmp_path)
    out = dc.load_one(write_category(tmp_path, "voices-ai", VALID, "# x\n"), tmp_path)
    assert out["framing"] == ""


# --- load_all / active -------------------------------------------------------

def test_load_all_and_active(tmp_path):
    with_roster(tmp_path)
    with_roster(tmp_path, "voices-markets.csv")
    write_category(tmp_path, "voices-ai", VALID)
    dormant = (VALID.replace("id: voices-ai", "id: voices-markets")
               .replace("roster: rosters/voices-ai.csv",
                        "roster: rosters/voices-markets.csv")
               .replace("digest: true", "digest: false")
               .replace("email: true", "email: false"))
    write_category(tmp_path, "voices-markets", dormant)

    cats = dc.load_all(tmp_path)
    assert [c["id"] for c in cats] == ["voices-ai", "voices-markets"]
    assert [c["id"] for c in dc.active(cats)] == ["voices-ai"]


def test_load_all_on_missing_dir_is_empty(tmp_path):
    assert dc.load_all(tmp_path / "nope") == []


# --- the shipped example files (hermetic: no vault required) -----------------

def test_example_roster_matches_the_column_contract():
    with EXAMPLE_ROSTER.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert yf.validate_roster_header(rows[0]) is None
    for row in rows[1:]:
        assert len(row) == len(yf.ROSTER_COLUMNS), row


def test_example_roster_documents_the_org_convention():
    """The (org) suffix is machine-read, so the example must demonstrate it."""
    with EXAMPLE_ROSTER.open(encoding="utf-8") as f:
        roles = [r["role"] for r in csv.DictReader(f)]
    assert any(yf.is_org_role(r) for r in roles)


def test_example_category_config_is_valid(tmp_path):
    """Validate the shipped example against a matching roster."""
    digests = tmp_path / "digests"
    digests.mkdir(parents=True)
    (digests / "voices-all.md").write_text(
        EXAMPLE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    rosters = tmp_path / "rosters"
    rosters.mkdir()
    (rosters / "voices-all.csv").write_text(
        EXAMPLE_ROSTER.read_text(encoding="utf-8"), encoding="utf-8")
    out = dc.load_one(digests / "voices-all.md", tmp_path)
    assert out["problems"] == []


def test_example_category_ships_with_email_disabled():
    """A fresh vault must not mail a half-configured list on its first fire."""
    cfg, _ = dc.split_frontmatter(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    assert cfg["email"] is False


def test_bootstrap_seeds_the_example_files():
    """The examples are only useful if bootstrap actually installs them."""
    boot = load_module(SCRIPTS / "bootstrap-vault.py", "bootstrap_vault_cats")
    targets = {dest for _, dest in boot.EXAMPLE_CONFIGS}
    assert "_config/digests/voices-all.md" in targets
    assert "_config/rosters/voices-all.csv" in targets
    assert {"_config/digests", "_config/rosters"} <= set(boot.VAULT_DIRS)


# --- live vault (skipped without one) ---------------------------------------

def _live_categories():
    if not (CONFIG / "digests").is_dir():
        pytest.skip("no live vault categories")
    return dc.load_all(CONFIG)


def test_live_categories_validate():
    for cat in _live_categories():
        assert cat["problems"] == [], f"{cat['path']}: {cat['problems']}"


def test_live_rosters_match_the_column_contract():
    rosters = sorted((CONFIG / "rosters").glob("*.csv")) \
        if (CONFIG / "rosters").is_dir() else []
    if not rosters:
        pytest.skip("no live rosters")
    for path in rosters:
        with path.open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert yf.validate_roster_header(rows[0]) is None, path.name
        for row in rows[1:]:
            assert len(row) == len(yf.ROSTER_COLUMNS), f"{path.name}: {row}"


def test_live_rosters_are_disjoint():
    """A handle belongs to exactly one roster.

    Dedup state is shared across categories and keyed on URL, which is only
    safe because each URL is fetched by exactly one category's run.
    """
    rosters = sorted((CONFIG / "rosters").glob("*.csv")) \
        if (CONFIG / "rosters").is_dir() else []
    if not rosters:
        pytest.skip("no live rosters")
    owner = {}
    collisions = []
    for path in rosters:
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                h = (row.get("handle") or "").strip()
                if not h:
                    continue
                if h in owner:
                    collisions.append(f"{h}: {owner[h]} and {path.name}")
                owner[h] = path.name
    assert not collisions, "handles in more than one roster: " + "; ".join(collisions)


def test_live_categories_agree_with_scheduled_jobs():
    """Cadence must not drift between the vault config and the repo job list."""
    cats = _live_categories()
    helper = load_module(SCRIPTS / "_catch_up_helper.py", "catch_up_cadence")
    with (SCRIPTS / "scheduled-jobs.yml").open() as f:
        jobs = yaml.safe_load(f)["jobs"]
    by_category = {j["category"]: j for j in jobs if j.get("category")}

    for cat in cats:
        if cat["config"].get("digest") is not True:
            continue
        job = by_category.get(cat["id"])
        assert job is not None, (
            f"category {cat['id']} has digest: true but no job in "
            f"scheduled-jobs.yml — it will never fire")
        assert helper.cadence_kind(job["cadence"]) == cat["config"]["cadence"], (
            f"{cat['id']}: job cadence {job['cadence']} disagrees with config "
            f"cadence {cat['config']['cadence']}")

    for cid in by_category:
        assert any(c["id"] == cid for c in cats), (
            f"job category {cid} has no config at _config/digests/{cid}.md")


def test_cli_serializes_date_fields(tmp_path, capsys):
    """YAML parses unquoted `created: 2026-08-31` into a date, not a string.

    Regression: the CLI crashed on any real config, since every vault note
    carries created/updated. The hermetic fixtures had no date fields.
    """
    with_roster(tmp_path)
    write_category(tmp_path, "voices-ai", VALID + "\ncreated: 2026-08-31")
    rc = dc.main(["digest_categories.py", str(tmp_path)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["config"]["created"] == "2026-08-31"
