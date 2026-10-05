---
name: weekly-review
description: OB1-borrowed weekly review skill. Scans the vault's writes from the past 7 days (across digests/, research/, events/, decisions/, facts/, insights/, _inbox/, people/, projects/) and produces an end-of-week synthesis at vault/digests/weekly/YYYY-MM-DD-weekly-review.md with the OB1 structure (Week at a Glance / Themes / Open Loops / Connections / Gaps / Focus). Unlike weekly-intelligence-digest, the source is the vault itself, not external feeds. Runs on Sunday PM by default (configurable). Use when the user asks to run the weekly review or synthesize what the vault accumulated this week — and on its Sunday-evening schedule.
---

# weekly-review

The end-of-week synthesis skill, lifted from Nate Jones's OB1 prompt 5 (Weekly Review). Where `weekly-intelligence-digest` answers "what changed in the world?", **this** skill answers "what changed in *my brain* — what did the toolkit and I write to the vault — and what does it mean?"

Source: the vault. Not external feeds. This skill is what closes the OB1 "Build the Thread" loop — accumulated insight over a week becomes a single review note.

## Agent config (consumed by `scheduled-agent-runner`)

```yaml
agent_name: weekly-review
cadence: weekly
schedule_hint: "Sunday 18:00 local"   # see open question in skills-plan.md re: Sun PM vs Fri PM vs Mon AM
source_filter:
  custom: vault                         # NOT source-registry, NOT a roster — the vault itself
  surfaces:
    - digests
    - research
    - events
    - decisions
    - facts
    - insights
    - _inbox
    - people
    - projects
  exclude:
    - _meta                             # conventions are durable infra, not weekly activity
    - _views                            # regenerated, not authored
    - .templates
  window_days: 7
verify_loadbearing: false               # this is reflection, not fact-claim production
curate_findings: false                  # findings stay in the review; no _inbox staging
template: ob1-weekly-review             # custom format — NOT the standard 5-section digest
```

## OB1 review structure (verbatim from `02-companion-prompts.md`)

The output document has **6 sections** instead of the standard digest's 5. This is a template-override case for `digest-writer`:

```markdown
# Weekly Review — {period_end}

**Period**: {period_start} → {period_end}

## Week at a Glance

{One-paragraph summary of the week. What was the dominant activity? How many durable notes
written? How many decisions made? How many inbox items pending? Aim for 3-5 sentences.}

## Themes

{Cluster the week's writes by topic, not by surface. 2-5 themes total. For each:
- name the theme in 3-5 words
- list the supporting notes via [[wikilinks]]
- one sentence on why this thread is forming}

## Open Loops

{Unresolved action items, decisions in status: proposed, #open-tagged notes, inbox items
awaiting curation, and explicit open questions from any note's "Open Questions" section.
List with target [[wikilink]] and one-line description. This is the section the user
scans on Monday morning to plan the week.}

## Connections

{Notes that link to each other or share entities — the [[wikilink]] graph forming in the
vault. Especially call out cross-digest synergies (one digest's finding amplifying or
contradicting another). This is where "Build the Thread" pays off.}

## Gaps

{What's missing from the vault that should be there? Topics with zero coverage, voices
with no recent activity, decisions that should exist but don't, research questions
raised but unanswered.}

## Focus suggestions

{Three to five concrete things the user could prioritize next week, drawn from Open
Loops + Gaps + the program's [[sdlc-modernization]] direction. Each as one line, action-
oriented.}
```

## Workflow

1. **Scan the vault** for files where frontmatter `created >= period_start` OR `updated >= period_start`. Use `vault-querier` filesystem grep + glob (or shell `find ... -newer`).
2. **Group by surface** to count weekly activity (N decisions, N facts, N digests, etc.).
3. **Cluster by topic** using frontmatter `tags` and body content for the Themes section.
4. **Surface open loops** by querying for `status: proposed` decisions, `#open` tags, `_inbox/` files, and explicit "Open Questions" headings.
5. **Map connections** via `vault-querier` backlinks across the week's notes — find pairs / triangles where multiple notes reference the same entity.
6. **Identify gaps** by intersecting the week's tags against the controlled vocabulary in `_meta/tags.md` — which tags went unused, suggesting under-covered topics.
7. **Synthesize focus suggestions** from open loops + gaps + the user's program context.
8. **Write** to `vault/digests/weekly/YYYY-MM-DD-weekly-review.md` via `digest-writer` with the `ob1-weekly-review` template override.

## Composes with

- `vault-conventions`, `vault-querier` — read-only scan of the vault.
- `digest-writer` (with custom template) + `vault-writer.write_digest` — output.
- `seen-tracker` — track which notes were already covered in last week's review (avoid re-listing).
- Does **not** use `source-fetcher`, `source-registry`, `feed-watcher`, `claim-extractor`, `verify-claim`, `memory-curator` — those are external-content tools.

## Acceptance test (for step 9 done-criteria)

Scan the past 7 days of vault writes (period 2026-06-13 → 2026-06-20 for the first run — given vault was scaffolded on 2026-06-20, "this week" effectively means "the bootstrap").

Confirm:
- Output at `vault/digests/weekly/YYYY-MM-DD-weekly-review.md` has all 6 OB1 sections in order.
- Week at a Glance includes counts (N notes written, N decisions, N inbox pending, etc.).
- Themes section clusters the week's writes around 2-5 themes (toolkit kickoff, vault adoption, voices roster, supply-chain awareness, etc.).
- Open Loops includes the open questions from `skills-plan.md` and the 3 pending `_inbox/` items.
- Connections section identifies at least one cross-digest synergy.
- Focus suggestions for next week are concrete and actionable.
