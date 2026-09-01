#!/usr/bin/env python3
"""digest_categories.py — parse and validate digest category configs.

A category is one Markdown file at ``vault/_config/digests/{id}.md``: structured
fields in YAML frontmatter, the why-you-care lens in a ``## Framing`` body
section. One file per category so that ``digest`` and ``email`` render as
checkboxes in Obsidian's Properties panel.

The ``id`` is load-bearing — it is simultaneously the category id, the
scheduled-job id, this file's stem, the roster's stem, and the digest's filename
segment. Validation enforces that rather than trusting it.

CLI::

    python digest_categories.py <config-dir>            # validate all, print JSON
    python digest_categories.py <config-dir> --id ai    # just one

Exits non-zero if any config is invalid, so it doubles as a pre-flight check.
"""
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a declared dependency
    yaml = None

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CADENCES = ("daily", "weekly", "biweekly", "monthly", "quarterly")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

REQUIRED = ("id", "title", "kind", "digest", "email", "cadence", "tags")
DEFAULTS = {
    "surfaces": ["substack", "youtube", "blog", "podcast"],
    "max_items_per_voice": 3,
    "seed_people_notes": True,
    "email_list": None,
}


def split_frontmatter(text):
    """Return (frontmatter_dict, body). Raises ValueError if absent/unparseable."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("no YAML frontmatter block at the top of the file")
    if yaml is None:
        raise ValueError("pyyaml is required to parse category configs")
    data = yaml.safe_load(m.group(1))
    if not isinstance(data, dict):
        raise ValueError("frontmatter did not parse to a mapping")
    return data, text[m.end():]


def framing(body):
    """Extract the `## Framing` section, or '' when absent.

    Becomes digest_template_overrides.why_you_care_extra for the category.
    """
    out, capturing = [], False
    for line in body.splitlines():
        if line.startswith("## "):
            capturing = line[3:].strip().lower() == "framing"
            continue
        if capturing:
            out.append(line)
    # Drop HTML comments and surrounding blank lines.
    text = re.sub(r"<!--.*?-->", "", "\n".join(out), flags=re.DOTALL)
    return text.strip()


def validate(cfg, stem, config_dir=None):
    """Return a list of human-readable problems with one parsed config."""
    problems = []

    for field in REQUIRED:
        if field not in cfg:
            problems.append(f"missing required field '{field}'")

    cid = cfg.get("id")
    if cid is not None:
        if not isinstance(cid, str) or not ID_RE.match(cid):
            problems.append(
                f"id {cid!r} must be lowercase alphanumeric with single hyphens")
        elif cid != stem:
            problems.append(
                f"id {cid!r} must equal the filename stem {stem!r} — the id is also "
                f"the job id, roster stem, and digest filename segment")

    for flag in ("digest", "email"):
        if flag in cfg and not isinstance(cfg[flag], bool):
            problems.append(
                f"{flag} must be true or false, got {cfg[flag]!r} "
                f"(quoted 'true' is a string, not a boolean)")

    # email:true + digest:false is unsatisfiable — there is nothing to send.
    if cfg.get("email") is True and cfg.get("digest") is False:
        problems.append(
            "email: true requires digest: true — a category that writes no note "
            "has nothing to send")

    cadence = cfg.get("cadence")
    if cadence is not None and cadence not in CADENCES:
        problems.append(f"cadence {cadence!r} not one of {list(CADENCES)}")

    roster = cfg.get("roster")
    if cfg.get("kind") == "voices" and not roster:
        problems.append("kind 'voices' requires a roster path")
    elif roster and config_dir is not None:
        if not (Path(config_dir) / roster).is_file():
            problems.append(f"roster not found: {roster}")

    tags = cfg.get("tags")
    if tags is not None and not isinstance(tags, list):
        problems.append(f"tags must be a list, got {type(tags).__name__}")

    return problems


def load_one(path, config_dir=None):
    """Parse + validate one category config file.

    Returns {"id", "path", "config", "framing", "problems"}. Never raises for a
    malformed file — the problems list is the report.
    """
    path = Path(path)
    stem = path.stem
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return {"id": stem, "path": str(path), "config": {}, "framing": "",
                "problems": [f"cannot read: {e}"]}
    try:
        cfg, body = split_frontmatter(text)
    except ValueError as e:
        return {"id": stem, "path": str(path), "config": {}, "framing": "",
                "problems": [str(e)]}

    problems = validate(cfg, stem, config_dir if config_dir else path.parent.parent)
    resolved = dict(DEFAULTS)
    resolved.update(cfg)
    return {"id": cfg.get("id", stem), "path": str(path), "config": resolved,
            "framing": framing(body), "problems": problems}


def load_all(config_dir):
    """Load every category under {config_dir}/digests/, sorted by id."""
    config_dir = Path(config_dir)
    digests_dir = config_dir / "digests"
    if not digests_dir.is_dir():
        return []
    return [load_one(p, config_dir)
            for p in sorted(digests_dir.glob("*.md"))]


def active(categories):
    """Categories that should actually produce a digest."""
    return [c for c in categories
            if not c["problems"] and c["config"].get("digest") is True]


def main(argv):
    args = argv[1:]
    want_id = None
    if "--id" in args:
        i = args.index("--id")
        if i + 1 >= len(args):
            print(json.dumps({"error": "--id requires a value"}))
            return 2
        want_id = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        print(json.dumps(
            {"error": "usage: digest_categories.py <config-dir> [--id ID]"}))
        return 2

    cats = load_all(args[0])
    if want_id is not None:
        cats = [c for c in cats if c["id"] == want_id]
        if not cats:
            print(json.dumps({"error": f"no category with id {want_id!r}"}))
            return 1

    print(json.dumps(cats, indent=2))
    return 1 if any(c["problems"] for c in cats) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
