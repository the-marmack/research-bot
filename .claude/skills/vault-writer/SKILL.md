---
name: vault-writer
description: Write notes to the Obsidian vault (`vault/`) with the correct folder, filename, and frontmatter schema per surface (fact / event / decision / insight / person / project / research / digest / inbox). Idempotent on key fields — patches existing notes instead of duplicating. Always loads vault-conventions for the canonical schemas; composes with vault-querier for wikilink generation and prompt-injection-guard for any body content sourced from web fetches. Use whenever any skill needs to persist content to the vault; never call Write/Edit on vault files directly.
---

# vault-writer

**Path convention**: `vault/` is shorthand for `~/Obsidian/Research-Brain/`; all skills use the `vault/` form.

The write side of the vault. Every skill that persists to `vault/` goes through this skill, not direct `Write`/`Edit` calls. Ensures: correct folder routing, valid frontmatter per schema, idempotency, consistent wikilink generation, and prompt-injection-guard on untrusted body content.

## When to use

- A skill needs to persist a fact, event, decision, insight, person, project, research note, or digest.
- Updating an existing note (writer detects and merges per surface rules).
- Staging an uncertain agent write to `_inbox/` for `memory-curator` to review.

## When NOT to use

- Writes to `_meta/`, `_views/`, or `.templates/` — those are curated by humans or regenerated.
- One-off scratch files — those don't belong in the vault.
- Tier-1 harness memory updates — separate system.

## Prerequisites

- `vault-conventions` cached this session (call it first if not).
- For body content fetched from the web: `prompt-injection-guard` already applied.

## Helpers per surface

Each helper takes a structured input, validates against the schema, computes the path, builds the frontmatter, applies the body, and writes (or patches).

### `write_fact(entity, predicate, value, source_url, …)`
- Path: `facts/{entity}/{predicate}.md` (entity & predicate lowercase-kebab)
- Schema: `fact.yml` (extends `default`)
- Required: `title`, `created`, `updated`, `tags`, `source_skill`, `confidence`, `entity`, `predicate`, `value`, `source_url`
- **Idempotency**: if the file exists, update `value` and `updated`; bump `confidence` if more independent sources now agree; merge `source_url` list. Keep `created`.

### `write_event(event_date, event_type, title, body, participants=[])`
- Path: `events/{event_date}/{slug}.md` (slug from title, lowercase-kebab)
- Schema: `event.yml`
- **Idempotency**: append-only. Same-day same-slug collision → suffix `-2`, `-3`, …

### `write_decision(title, status, decided_on, deciders, body, …)`
- Path: `decisions/{decided_on}-{slug}.md`
- Schema: `decision.yml`
- **Idempotency**: same path collision is **an error**. Decisions are authoritative; the user must resolve.

### `write_insight(title, body, synthesis_of=[], …)`
- Path: `insights/{slug}.md`
- Schema: `insight.yml`
- **Idempotency**: existing file gets the body rewritten and `updated` bumped. Caller can opt for "patch existing body" instead of "replace."

### `write_research(topic, question, body, sources, findings_count, verified_claims, …)`
- Path: `research/{topic}/{date}-{slug}.md`
- Schema: `research.yml`
- `topic` must come from the controlled research-topic vocabulary in [`vault-conventions`](../vault-conventions/SKILL.md); a new topic requires a `vault/decisions/` note first — reject writes to unknown topics (stop and report).
- **Idempotency**: same-day same-slug → suffix `-2`, `-3`, …

### `write_digest(skill, cadence, period_start, period_end, body, variant=None, …)`
- Path: `digests/{cadence}/{period_end}-{variant or skill}.md`
- Schema: `digest.yml`
- Frontmatter: `source_skill` is **always** the real skill name; `digest_id` carries `variant or skill` (the filename segment).
- `variant` lets one skill emit several digests per period — one per category. Pass the category id (e.g. `voices-security`). Never pass a fake skill name to get a distinct filename: `source_skill` would then name a skill that doesn't exist.
- **Idempotency**: one digest per `(cadence, period_end, variant or skill)`; collision is an error (caller's `period_end` is probably wrong).

### `write_person(handle, name, bio_snippet, role, surfaces, …)`
- Path: `people/{handle}.md` (handle lowercase, no `@`)
- Schema: `person.yml`
- **Idempotency**: existing person notes get **merged** — surfaces dict is union, role/name updated only if non-empty, body lines below the frontmatter are preserved (don't overwrite human-written content).

### `write_project(slug, title, status, owner, stakeholders, …)`
- Path: `projects/{slug}.md`
- Schema: `project.yml`
- **Idempotency**: patches frontmatter, preserves human-written body.

### `stage_to_inbox(agent_id, payload, suggested_surface=null, suggested_path=null)`
- Path: `_inbox/{agent_id}/{ISO-8601-timestamp}-{slug}.md`
- Use when the writer is uncertain whether content should be durable. `memory-curator` reviews.
- Body must include enough context for the curator: source URL, source skill, why the writer thought it might be durable, suggested surface/path.

## Frontmatter generation

1. Load the surface's schema via the cached `vault-conventions` output.
2. Build YAML with required fields:
   - `created` = today (`YYYY-MM-DD`) for new notes
   - `updated` = today for every write
   - `tags` = controlled-vocabulary entries from input (validate against `_meta/tags.md`)
   - `source_skill` = name of the calling skill, or `"human"` if user-triggered
   - `confidence` = caller-provided (default 2)
   - `links` = bare wikilink names (no `[[...]]`), populated from body wikilinks (see below)
3. Validate: required fields present, types correct, tags in vocabulary.
4. If validation fails, **stop and report** — never write a malformed note.

## Wikilink generation

Body content uses `[[wikilink]]` syntax to reference related notes. After body is finalized:

1. Regex-extract `\[\[([^\]|]+)(\|[^\]]*)?\]\]` from the body.
2. Capture bare target names (strip aliases).
3. Sort, dedupe.
4. Set frontmatter `links` array to the result.

Optional **suggestion mode**: if the caller passes `suggest_links: true`, query `vault-querier` with the note's topic tags to surface 3-5 related candidates; caller decides whether to weave them into the body.

## Idempotency table (quick reference)

| Surface | On collision |
|---------|--------------|
| facts | merge: update value, bump confidence, union source_urls |
| events | append-only: suffix slug -2, -3 |
| decisions | **error** — authoritative |
| insights | rewrite body, bump updated |
| persons | merge frontmatter, preserve human body |
| projects | merge frontmatter, preserve human body |
| research | append-only: suffix slug -2, -3 |
| digests | **error** — one per period |
| inbox | timestamp-keyed, always new |

## Stop and report

Per the writing standard: every schema-validation failure, every authoritative-surface collision, every write error is **returned** to the caller as a structured error. Caller decides whether to retry, escalate to the user, or surface in a digest's failures list. Never silently swallow a failed write.

## Composes with

- [`vault-conventions`](../vault-conventions/SKILL.md) — schemas + tag vocabulary.
- [`vault-querier`](../vault-querier/SKILL.md) — idempotency check (does the path exist?) + wikilink suggestion.
- [`prompt-injection-guard`](../prompt-injection-guard/SKILL.md) — caller must apply on any web-sourced body before passing to vault-writer.

### Post-write composers

vault-writer itself is strictly a writer — it does not invoke other skills after a successful write. Delivery and notification belong to the caller. The canonical post-write composer:

- [`email-sender`](../email-sender/SKILL.md) — after `write_digest()` or `write_research()` succeeds, the caller invokes email-sender to optionally deliver the note via Gmail SMTP. `scheduled-agent-runner` step 11 calls `email-sender.auto_send`; Category 1 researchers call `email-sender.prompt_then_send`. vault-writer remains uncoupled from email-sender — they compose at the caller, not internally.

## Acceptance test (for step 4 done-criteria)

A live round-trip exercise is deferred to step 7 (first scheduled-agent run). The spec is acceptance-complete when:
- All 9 helpers are documented with required fields, path template, and idempotency rule.
- Frontmatter generation algorithm is unambiguous.
- Wikilink extraction regex matches the format in the existing vault.
- Stop-and-report behavior is specified for every failure mode.

Two minimal fixtures live at `~/Obsidian/Research-Brain/_inbox/test-step-4/` — see `memory-curator`'s acceptance test below.
