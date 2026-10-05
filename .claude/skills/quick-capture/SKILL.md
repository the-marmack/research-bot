---
name: quick-capture
description: Parse a one-line user input matching one of five OB1-borrowed sentence-starter formats (Decision / Person / Insight / Meeting / AI Save) and route to the correct vault folder via vault-writer. The user types "Decision: skip X polling. Context: API too expensive. Owner: me." and the skill creates `vault/decisions/2026-06-20-skip-x-polling.md` with valid frontmatter. Use whenever the user wants to capture something quickly without thinking about which folder or which schema applies.
---

# quick-capture

The fast input path. OB1 prompt-4 gave us five sentence-starter formats; this skill recognizes any of them and lands the note in the right place with the right schema. The user types a single line; the skill picks the surface, builds the frontmatter, writes the body, and confirms.

## When to use

- The user wants to capture a decision, person note, insight, meeting summary, or AI-tool save **without** thinking about folder structure or frontmatter.
- Anytime the user types one of the five recognized formats.
- Inline during a conversation when something durable comes up.

## When NOT to use

- Long-form research, multi-source synthesis, deep-dives — those go through Category 1 research skills.
- Fact-claims requiring verification — that's `claim-extractor` + `verify-claim` → `memory-curator`.
- Scheduled-agent output — those use `digest-writer` directly.

## The five formats

Recognition is pattern-based on the leading sentence-starter:

### 1. Decision

```
Decision: <what>. Context: <why>. Owner: <who>.
```

→ `vault/decisions/{YYYY-MM-DD}-{slug-of-what}.md`
→ Template: `.templates/qc-decision.md`
→ `vault-writer.write_decision(title=<what>, status='proposed', decided_on=<today>, deciders=[<who>], body=<context as body>)`

The status defaults to `proposed`; the user can edit to `accepted` later. Most quick-capture decisions are personal/program-level proposals that get formalized through the ADR process.

### 2. Person note

```
[Name] — [what you learned].
```

→ `vault/people/{slug-of-name}.md`
→ Template: `.templates/qc-person.md`
→ `vault-writer.write_person(handle=<slug-of-name>, name=<name>, ...)` — **patch mode**: if the person already exists (e.g., from a voice roster), append "what you learned" to the body's "What I learned" section, don't overwrite.

### 3. Insight

```
Insight: <realization>. Triggered by: <cause>.
```

→ `vault/insights/{slug-of-realization}.md`
→ Template: `.templates/qc-insight.md`
→ `vault-writer.write_insight(title=<realization>, body=<both, formatted>)`

### 4. Meeting debrief

```
Meeting with <who> about <topic>. Key points: <points>. Action items: <items>.
```

→ `vault/events/{YYYY-MM-DD}/{slug-of-topic}.md`
→ Template: `.templates/qc-meeting.md`
→ `vault-writer.write_event(event_date=<today>, event_type='meeting', title=<topic>, body=<both, formatted>, participants=[<who>])`

### 5. AI save

```
Saving from <tool>: <key takeaway>.
```

→ `vault/insights/{slug-of-takeaway}.md` (with `tags: [insight, ai-coding-tools]`)
→ Template: `.templates/qc-ai-save.md`
→ `vault-writer.write_insight(title=<takeaway>, body=<formatted with tool attribution>)`

## Parsing rules

The skill uses literal sentence-starters as the format trigger (case-insensitive):
- `Decision:` → format 1
- `Insight:` → format 3
- `Meeting with` → format 4
- `Saving from` → format 5
- Anything else with `<Name> — <text>` (em-dash or hyphen-em-dash) → format 2

If the input doesn't match any format clearly, **stop and ask**: "Which capture format did you mean? [decision / person / insight / meeting / ai-save]". Per the stop-and-report guardrail, do not silently misroute.

## Slug derivation

For all formats:
- Lowercase the title.
- Replace non-alphanumeric chars with `-`.
- Collapse repeated `-`.
- Trim leading/trailing `-`.
- Cap at 60 chars.
- For decisions, prepend the date: `{YYYY-MM-DD}-{slug}`.

## Idempotency

`vault-writer`'s per-surface idempotency rules apply:
- Decisions: same-date same-slug → error (the user is making a different decision; they should disambiguate).
- People: existing person → merge per `write_person` rules.
- Insights: existing slug → rewrite body, bump `updated`.
- Events: append-only, same-day same-slug → suffix `-2`.

## Output to user

After writing, return a one-line confirmation with the vault path:

```
✓ captured to vault/decisions/2026-06-20-skip-x-polling.md
```

Plus the [[wikilink]] form so the user can paste it elsewhere: `[[2026-06-20-skip-x-polling]]`.

## Composes with

- [`vault-writer`](../vault-writer/SKILL.md) — every write.
- [`vault-conventions`](../vault-conventions/SKILL.md) — schema for the target surface.
- The 5 templates at `~/Obsidian/Research-Brain/.templates/qc-*.md`.

## Acceptance test (for step 10 done-criteria)

Parse each of these 5 inputs without error and route to the correct surface:

1. `Decision: weekly-review runs Sunday PM. Context: end-of-week reflection beats start-of-week planning for this user. Owner: me.` → `vault/decisions/2026-06-20-weekly-review-runs-sunday-pm.md`
2. `Lenny Rachitsky — pivoted from describing to building research tools for PMs.` → patches `vault/people/lennysan.md` (Lenny exists from a voice roster).
3. `Insight: the Fable 5 export-control story plus Huryn's eval together justify a written internal note before any team considers Fable 5 adoption. Triggered by: noticing the cross-digest connection in the 2026-06-20 weekly review.` → `vault/insights/fable-5-internal-note-before-adoption.md`
4. `Meeting with security architecture team about Copilot AGENTS.md rollout. Key points: golden-path template needs an AGENTS.md stub, secure-coding patterns mirror from CONTRIBUTING.md. Action items: draft stub by EOW, circulate to repo template owners.` → `vault/events/2026-06-20/copilot-agents-md-rollout.md`
5. `Saving from Claude: the "default to refuted=true if uncertain" prompt-engineering line is load-bearing — without it, refute-prompts default to confirmation.` → `vault/insights/default-to-refuted-true-if-uncertain.md`

For ambiguous input ("Some thought I had today"), ask which format.
