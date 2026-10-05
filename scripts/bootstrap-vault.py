#!/usr/bin/env python3
"""
bootstrap-vault.py — create the Tier-2 Obsidian vault this toolkit writes into.

Most Category 1 and 2 skills fail loudly without a vault, and the conventions
they read (`_meta/conventions.md`, `_meta/tags.md`, `_meta/inbox-rules.md`,
`_meta/schema/*.yml`) are not something a new user can invent. This script
copies the generic scaffold from `vault-template/` into place and creates the
folder tree that `_meta/conventions.md` documents.

Idempotent, like schedule-sync.py: existing files are never overwritten unless
you pass --force, so re-running after an upgrade is safe and re-running on a
populated vault does nothing.

Usage:
    python3 scripts/bootstrap-vault.py                 # create/patch the vault
    python3 scripts/bootstrap-vault.py --dry-run       # report only
    python3 scripts/bootstrap-vault.py --force         # overwrite _meta scaffold
    python3 scripts/bootstrap-vault.py --vault PATH    # non-default location
"""

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "vault-template"
DEFAULT_VAULT = Path.home() / "Obsidian" / "Research-Brain"

# The folder tree from _meta/conventions.md "Layout". Keep in sync with it —
# the conventions file is the spec, this list is the implementation.
VAULT_DIRS = [
    "_meta",
    "_meta/schema",
    "_config",
    "_config/digests",
    "_config/rosters",
    "_inbox",
    "_views",
    ".templates",
    "people",
    "projects",
    "decisions",
    "insights",
    "facts",
    "events",
    "research",
    "digests",
    "digests/daily",
    "digests/weekly",
    "digests/biweekly",
    "digests/monthly",
    "digests/quarterly",
]

# Example configs that ship inside the skills that consume them. Copied to
# _config/ under their real names only if nothing is there yet — these are the
# files a user edits by hand, so clobbering them would be destructive.
EXAMPLE_CONFIGS = [
    (
        REPO_ROOT / ".claude/skills/email-sender/email-distribution.example.md",
        "_config/email-distribution.md",
    ),
    (
        REPO_ROOT
        / ".claude/skills/executive-summary-writer/exec-preferences.example.md",
        "_config/exec-preferences.md",
    ),
    # One working digest category so a fresh vault has something to run.
    # Seeded with email disabled — a half-configured distribution list must not
    # send mail on the first scheduled fire.
    (
        REPO_ROOT / ".claude/skills/voices-watcher/digest-config.example.md",
        "_config/digests/voices-all.md",
    ),
    (
        REPO_ROOT / ".claude/skills/voices-watcher/roster.example.csv",
        "_config/rosters/voices-all.csv",
    ),
]


class Reporter:
    """Collects actions so --dry-run and a real run print the same summary."""

    def __init__(self, dry_run):
        self.dry_run = dry_run
        self.created = []
        self.copied = []
        self.skipped = []

    def mkdir(self, path):
        if path.is_dir():
            return
        self.created.append(path)
        if not self.dry_run:
            path.mkdir(parents=True, exist_ok=True)

    def copy(self, src, dst, force=False):
        if dst.exists() and not force:
            self.skipped.append(dst)
            return
        self.copied.append(dst)
        if not self.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    def summary(self, vault):
        verb = "Would create" if self.dry_run else "Created"
        print(f"Vault: {vault}")
        print(f"  {verb} {len(self.created)} folder(s)")
        print(f"  {'Would copy' if self.dry_run else 'Copied'} {len(self.copied)} file(s)")
        if self.skipped:
            print(f"  Left {len(self.skipped)} existing file(s) untouched")
        for p in self.copied:
            print(f"    + {p.relative_to(vault)}")
        if self.dry_run:
            print("\nDry run — nothing was written.")


def bootstrap(vault, template_dir=TEMPLATE_DIR, dry_run=False, force=False):
    """Create the vault tree and populate it from the template.

    Returns the Reporter so callers (and tests) can inspect what happened.
    """
    if not template_dir.is_dir():
        raise FileNotFoundError(f"vault template not found at {template_dir}")

    r = Reporter(dry_run)

    r.mkdir(vault)
    for rel in VAULT_DIRS:
        r.mkdir(vault / rel)

    # Copy every tracked template file, preserving its relative path.
    for src in sorted(template_dir.rglob("*")):
        if not src.is_file():
            continue
        r.copy(src, vault / src.relative_to(template_dir), force=force)

    # Seed user-editable configs from the skills' own examples. Never forced —
    # these hold real recipient lists once the user edits them.
    for src, rel in EXAMPLE_CONFIGS:
        if src.is_file():
            r.copy(src, vault / rel, force=False)

    return r


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Scaffold the Tier-2 Obsidian vault for the research-bot toolkit."
    )
    ap.add_argument(
        "--vault", type=Path, default=DEFAULT_VAULT,
        help=f"vault location (default: {DEFAULT_VAULT})",
    )
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    ap.add_argument(
        "--force", action="store_true",
        help="overwrite existing _meta/.templates scaffold (never touches _config)",
    )
    args = ap.parse_args(argv)

    try:
        r = bootstrap(
            args.vault.expanduser(), dry_run=args.dry_run, force=args.force
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    r.summary(args.vault.expanduser())
    if not args.dry_run:
        print(
            "\nNext:\n"
            "  1. Open the vault in Obsidian (optional — it is plain Markdown).\n"
            "  2. Edit _config/email-distribution.md if you want email delivery.\n"
            "  3. Open Claude Code in the repo and try a prompt from PROMPTING.md."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
