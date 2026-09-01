---
title: _config — skill-read operational config
created: 2026-06-21
updated: 2026-06-23
tags: [meta]
source_skill: human
confidence: 3
links: [conventions]
---

# _config/ — skill-read operational config

This folder holds **skill-read operational configuration** — settings, recipient lists, channel routing, and audience-adaptation preferences used by skills at run time. It is distinct from `_meta/` (schemas, conventions, controlled vocabularies) and from durable knowledge folders (`facts/`, `research/`, etc.). Knowledge ABOUT a person belongs in `people/{handle}.md`; per-audience writing preferences live here.

## Authority + handling rules

| Property | Setting |
|----------|---------|
| Authority | curated (human-edited) |
| Indexed by `vault-querier`? | **no** (operational config, not knowledge) |
| Backlinked in `_views/`? | **no** |
| Should `memory-curator` ever touch this? | **no** |
| Should `vault-writer` ever write here? | **no** — write to `_inbox/` or the appropriate durable folder instead |
| Validation | each consuming skill validates on load and stops-and-reports on schema errors |

## Current files

| File | Consumed by | Purpose |
|------|-------------|---------|
| `email-distribution.md` | [`email-sender`](../../research-bot/.claude/skills/email-sender/SKILL.md) | Markdown bullet list of email recipients — everyone listed gets every scheduled digest |
| `exec-preferences.md` | [`executive-summary-writer`](../../research-bot/.claude/skills/executive-summary-writer/SKILL.md) | Per-audience preferences (length, voice, format, emphasis) for executive summaries |
| `digests/{id}.md` | [`voices-watcher`](../../research-bot/.claude/skills/voices-watcher/SKILL.md), `scheduled-agent-runner` | One file per digest category — frontmatter holds `digest` / `email` flags, roster path, cadence, and optional `email_list`; the body's `## Framing` section supplies the why-you-care lens |
| `rosters/{id}.csv` | [`voices-watcher`](../../research-bot/.claude/skills/voices-watcher/SKILL.md), [`voices-roster-curator`](../../research-bot/.claude/skills/voices-roster-curator/SKILL.md) | The people and channels polled for one category. A handle belongs to exactly one roster |

## How to add a new config file

1. The consuming skill defines the format in its `SKILL.md` and ships a `*.example.md` template inside its skill folder in the toolkit repo.
2. Copy the template here and edit in Obsidian. The file lives in your vault (Obsidian-editable, not in the public toolkit repo).
3. The skill parses + validates on every load and surfaces errors via stop-and-report. Fix before the next scheduled run that depends on it.

## Why Markdown not YAML?

YAML in `_config/` doesn't compose with Obsidian — no preview, no link autocomplete, no validation hints. Markdown is the vault's native format. Skills that need structured data either parse Markdown bullets (the cheap-and-readable path used by `email-sender`) or put structured fields in YAML frontmatter (which Obsidian DOES render). Pure standalone `.yml` files are reserved for the toolkit's repo-side config (e.g. `scripts/scheduled-jobs.yml`).

**Tabular data: CSV is permitted.** Roster files under `rosters/*.csv` are the one exception. Obsidian has no native primitive for a 12-column, 60-row table that a human maintains by hand; a Markdown table at that width is unmaintainable, and YAML would be worse. CSV is also what `voices-roster-curator` already reads and writes, and it stays editable in a spreadsheet. The rule stands for everything else: **structured config is Markdown-with-frontmatter, tabular roster data is CSV, and standalone `.yml` remains reserved for repo-side config.**

## Why not `_meta/`?

`_meta/` holds **schemas + vocabularies** — the rules for the knowledge in the vault. `_config/` holds **operational config** — the wiring for skills that send vault content outward. Same folder layout but different concerns; keeping them separate avoids muddying the vault-querier index with non-knowledge YAML.
