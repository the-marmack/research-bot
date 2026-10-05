---
title: All Voices
id: voices-all
kind: voices
digest: true
email: false
roster: rosters/voices-all.csv
cadence: daily
tags: [digest]
surfaces: [substack, youtube, blog, podcast]
max_items_per_voice: 3
seed_people_notes: true
created: 2026-01-01
updated: 2026-01-01
source_skill: human
confidence: 3
---

# All Voices

One digest category. Copy this file per category you want — `voices-ai.md`,
`voices-security.md`, whatever fits your interests — and give each its own
roster CSV alongside it in `rosters/`.

## How the flags work

`digest` and `email` are independent, giving three usable states:

| `digest` | `email` | Meaning |
|---|---|---|
| `true` | `true` | Full push — the note is written and sent |
| `true` | `false` | Vault-only — written, read it in Obsidian, never mailed |
| `false` | `false` | Dormant — the roster is tracked and curated, nothing is produced |

`email: true` with `digest: false` is a configuration error: there is nothing to
send. This file ships with `email: false` on purpose — a fresh vault shouldn't
mail anyone until you've checked the distribution list.

Both flags render as checkboxes in Obsidian's Properties panel, so switching a
category to vault-only or dormant is a click. Neither needs a `schedule-sync.py`
run. Removing a category's job entirely does.

## The id is load-bearing

`id` must equal this file's name without the extension. That one string is also
the scheduled-job id, the roster filename stem, and the digest filename segment:

```
_config/digests/voices-all.md      ← this file
_config/rosters/voices-all.csv     ← its roster
digests/daily/YYYY-MM-DD-voices-all.md   ← what it produces
```

## Fields

- `roster` — path relative to `_config/`. Must exist.
- `cadence` — `daily`, `weekly`, `biweekly`, `monthly`, or `quarterly`. Must agree
  with the matching job in the toolkit's `scripts/scheduled-jobs.yml`; a test
  enforces that they don't drift.
- `email_list` — *(optional)* the name of a `## Recipients: <name>` segment in
  `_config/email-distribution.md`. Omit it and the digest goes to everyone. Name a
  segment that doesn't exist and the send fails loudly rather than falling back to
  the full list.
- `tags` — must come from the controlled vocabulary in `_meta/tags.md`.
- `surfaces` — which roster columns to poll. X/Twitter is deliberately not polled.
- `max_items_per_voice` — caps a single voice (or a conference channel that dumps
  dozens of talks at once) from swamping the digest.
- `seed_people_notes` — whether to keep `people/{handle}.md` in sync. Rows whose
  `role` ends in `(org)` are polled but never seeded regardless.

## Framing

<!-- This section becomes the digest's "Why You Care" lens. Rewrite it for the
     category — it is the one place the digest learns what matters to you. -->

These are commentators, not vendors. Tie threads back to the questions actually
open in your work. If a post is off-topic for that context, surface the title
only — don't manufacture a reason to care.

Video items carry a title and link only; no transcript is fetched. Infer
relevance from the title alone, and if the title doesn't support a confident
line, omit it rather than speculating about content you have not seen.
