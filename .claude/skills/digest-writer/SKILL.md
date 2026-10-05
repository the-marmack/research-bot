---
name: digest-writer
description: Canonical formatter for digests and research reports. Enforces a 5-section structure (TL;DR → What Changed → Why You Care → Detailed Findings → Sources) with the regulated-org lens applied to "Why You Care" and credibility-tier badges on every source. Delegates the actual file write to vault-writer, landing the digest at `vault/digests/{cadence}/YYYY-MM-DD-{skill}.md` (for scheduled agents) or `vault/research/{topic}/YYYY-MM-DD-{slug}.md` (for on-demand research). Every Category 2 scheduled agent and every Category 1 research skill writes through this skill. Use whenever a scheduled agent or research skill is formatting its final output — after claims are extracted and verified, immediately before the vault-writer write.
---

# digest-writer

**Path convention**: `vault/` is shorthand for `~/Obsidian/Research-Brain/`; all skills use the `vault/` form.

The canonical output formatter for everything that lands in `vault/digests/` or `vault/research/`. Skills hand it raw findings + metadata; it produces a markdown document with the standard 5-section structure and delegates the file write to `vault-writer`.

## Why a separate skill

Three reasons it's not just inlined per-skill:
1. **One review surface** — when the user reviews any Monday-morning digest, the layout is identical, so attention goes to content.
2. **One place to audit citations** — every digest passes through the same source-tier badge + accessed-date discipline. Months later, every digest is auditable.
3. **One place to enforce the regulated-org lens** — "Why You Care" framing is centralized.

## When to use

- Every Category 2 scheduled agent at end of run.
- Every Category 1 on-demand research skill when finalizing output.
- Any ad-hoc digest the user wants formatted to the standard.

## When NOT to use

- Individual fact / event / decision writes — those go through `vault-writer.write_fact/event/decision` directly.
- Quick captures via the `quick-capture` skill — different format, different surface.
- `_inbox/` stages — those are pre-curation, no formatting needed.

## Input

```json
{
  "skill": "weekly-intelligence-digest",
  "destination": "digests" | "research",
  "cadence": "daily | weekly | biweekly | monthly | quarterly",  // for digests
  "variant": "voices-security",                                    // optional, for digests
  "title": "Security Voices",                                      // optional, overrides the H1
  "topic": "copilot",                                              // for research
  "slug": "what-changed",                                          // optional, derived from title if absent
  "period_start": "2026-06-13",
  "period_end": "2026-06-20",
  "tldr": ["bullet 1", "bullet 2", "bullet 3"],
  "items": [
    {
      "title": "Copilot Enterprise audit log now exports to S3",
      "what_changed": "Audit log gained S3 export with KMS encryption.",
      "why_you_care": "Regulated buyers can ingest into SIEM via S3 directly, replacing the manual CSV-download path.",
      "source_url": "https://github.blog/changelog/2026-06-19-...",
      "source_id": "github-changelog",
      "source_tier": 1,
      "accessed_at": "2026-06-20",
      "verified": true,
      "confidence": 3,
      "tags": ["copilot", "ghas"]
    }
  ],
  "failures": [
    {"source_id": "anthropic-news", "reason": "HTML scrape returned 0 items"}
  ],
  "previous_digest": "2026-06-13-weekly-intelligence-digest.md"  // optional, for "since last digest" framing
}
```

For `destination: research`, `topic` must come from the controlled research-topic vocabulary in [`vault-conventions`](../vault-conventions/SKILL.md) — a new topic requires a `vault/decisions/` note first.

For `destination: digests`, `variant` is passed straight through to `vault-writer.write_digest` — it sets the filename segment and the `digest_id` frontmatter field while `source_skill` stays the real skill. Use it when one skill emits several digests per period (one per category); omit it otherwise. When `variant` is set, `title` supplies the document H1 (e.g. `# Security Voices — 2026-08-31`) so a category digest reads under its own name rather than the skill's.

## Output document structure

```markdown
# {title or Skill Title} — {period_end}

**Period**: {period_start} → {period_end}{, since [[previous_digest]]}

## TL;DR

- {tldr[0]}
- {tldr[1]}
- {tldr[2]}

## What Changed

{For each item, top-level bullet with title + the `what_changed` sentence + an inline citation badge}

- **{item.title}** — {item.what_changed} [[T{item.source_tier}]({item.source_url})] (accessed {item.accessed_at})

## Why You Care

{Regulated-finance framing — compliance-relevant lens. For each item, a single plain-language sentence on why it matters for a regulated org running thousands of devs under GHAS, Copilot, SR 11-7, FFIEC, etc.}

- {item.title}: {item.why_you_care}

## Detailed Findings

{Per-item full body. Show source_tier badge, link, confidence marker, related vault notes via [[wikilinks]].}

### {item.title}

{Full body of the item — quoted anchors, links to related facts, what to do next.}

- Source: [{source_id}]({source_url}) (tier {source_tier}, accessed {accessed_at})
- Confidence: {confidence}/3{, #disputed if disputed}
- Related: {[[wikilinks]] to facts/insights/research}

## Sources

{Numbered list of every source consulted this run, including ones that failed. Per "stop and report": failures must appear here, not be silently dropped.}

1. [{source_name}]({source_url}) — tier {source_tier}, accessed {accessed_at} — {N items surfaced}
…
N. {source_name} — **failed**: {failure.reason}
```

## Tier badges

- `T1` — vendor / regulator primary source (gold standard, no further verification needed for vendor's own claims)
- `T2` — quality industry analysis (NIST, OpenSSF, named analysts)
- `T3` — untrusted / unverified (must be verified before publishing claims)

Render in the markdown as `[T1]` / `[T2]` / `[T3]` linked to the URL.

## "Why You Care" framing

Every "Why You Care" line must connect the change to one of:
- SDLC modernization (Copilot rollout, dev productivity, golden paths)
- Regulated finance (SR 11-7 model risk, FFIEC, OCC, SOX ITGC, NYDFS, AI governance)
- GitHub admin operations (CodeQL, Dependabot, GHAS, audit log, Actions hardening)
- Peer-bank intelligence

If a finding doesn't connect to any of these, ask: is it actually worth being in the digest? Drop it or move to a non-digest surface (research, insight).

## Delegate the write

Call `vault-writer.write_digest(...)` (for scheduled digests) or `vault-writer.write_research(...)` (for on-demand research) with the formatted body + the frontmatter the helper computes. Do not call `Write` directly on vault files.

## Failures section

Per the stop-and-report guardrail: every `failures[]` entry from `feed-watcher` (sources that didn't poll) gets a line in the **Sources** section as `**failed**: {reason}`. Never silently omit a source.

## Composes with

- [`vault-writer`](../vault-writer/SKILL.md) — the actual file write.
- [`vault-conventions`](../vault-conventions/SKILL.md) — schema for digest frontmatter.
- [`vault-querier`](../vault-querier/SKILL.md) — looking up related notes for `[[wikilinks]]` in Detailed Findings.

## Acceptance test (for step 6 done-criteria)

Generate a digest with 2 items, 1 failure, period 2026-06-13 → 2026-06-20, for skill `weekly-intelligence-digest`. Confirm:
- Document has all 5 sections in order.
- TL;DR has 3 bullets.
- Each item appears in What Changed, Why You Care, and Detailed Findings.
- Tier badges render as `[T1]` etc., linked to the source URL.
- The failed source appears in Sources marked `**failed**`.
- The write lands at `vault/digests/weekly/2026-06-20-weekly-intelligence-digest.md`.

Exercised live on every `weekly-intelligence-digest` run.
