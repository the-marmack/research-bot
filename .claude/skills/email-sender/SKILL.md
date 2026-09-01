---
name: email-sender
description: Send, or preview and show, email delivery of a vault note (digest or research) to your distribution list. Delivery is deterministic — Markdown rendered to styled HTML with the raw `.md` attached, via a committed `render_and_send.py` (no AI call). Scheduled digests auto-send to everyone on the list; research notes prompt `[y/n]` first. A `show_list` action loads and prints the distribution list — who would receive the next send — without sending anything. Recipients come from a plain-Markdown list at `vault/_config/email-distribution.md`. Use when the user asks to email, send, forward, or distribute a digest or research note to their list, OR to show, list, view, preview, check, or validate their email distribution list (who's on it, who would get the next digest) — and immediately after `vault-writer.write_digest` or `vault-writer.write_research` succeeds. Not for composing an ad-hoc personal email or answering a generic SMTP question.
---

# email-sender

The post-write distribution hook. Every vault write worth surfacing beyond the local Obsidian copy goes through here. Scheduled digests fire-and-forget to the distribution list; ad-hoc research notes prompt the user `[y/n]` before sending. The vault note remains the canonical record; email is a delivery channel, not a replacement.

## When to use

- Immediately after `vault-writer.write_digest()` succeeds — invoked from `scheduled-agent-runner` step 11.
- Immediately after `vault-writer.write_research()` succeeds in any Category 1 researcher — researcher invokes `prompt_then_send`.
- User explicitly asks: "email this", "send the latest weekly digest to my distribution list", "show me my distribution list".

## When NOT to use

- Writes to `facts/`, `events/`, `decisions/`, `insights/`, `people/`, `projects/`, `_inbox/` — durable knowledge, not distribution targets. (`auto_send` no-ops on these surfaces.)
- Non-interactive context AND surface is `research` — `prompt_then_send` requires a user; degrade gracefully by skipping.
- Mid-stream (vault write hasn't completed yet — wait for the write).

## Prerequisites

Two pieces of config:

1. **Gmail credentials** at `~/.config/research-bot/env`:
   ```
   GMAIL_SEND_ADDRESS=you@gmail.com
   GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
   ```
   Requires 2-Step Verification enabled on the account. Generate at https://myaccount.google.com/apppasswords ("Mail" → "Other / research-bot"). Use the helper script: `scripts/set-gmail-credentials.sh "you@gmail.com" "xxxx xxxx xxxx xxxx"` (note the leading space to keep the command out of shell history).

2. **Distribution list** at `vault/_config/email-distribution.md`. Copy [`email-distribution.example.md`](./email-distribution.example.md) to that path on first use and edit.

If either is missing, the skill stops and reports — never silently drops.

## Helpers

### `send_note(note_path, subject_override=None, list_name=None)`

The primary action. Steps:

1. Resolve `note_path` to an absolute path; confirm the file exists.
2. Load `vault/_config/email-distribution.md` and resolve the send-to set with
   `email_recipients.recipients_for(text, list_name)` (see [Parsing](#parsing)).
   `list_name=None` (the default) sends to everyone. A named segment sends only to
   that segment; an unknown or empty one stop-and-reports (cases #9/#10) rather than
   falling back to the full list.
3. Confirm `~/.config/research-bot/env` carries `GMAIL_SEND_ADDRESS` and `GMAIL_APP_PASSWORD` (the script re-reads them, but check here so a missing credential surfaces as a clean stop-and-report referencing the setup helper).
4. Derive the **Subject**: `subject_override` if given, else derive from the note (see [Subject derivation](#subject-derivation)).
5. Per-recipient validation: drop any address that doesn't match `^[^\s@]+@[^\s@]+\.[^\s@]+$` (record it for the `skipped` list). A single bad entry doesn't lose the rest.
6. Invoke **`render_and_send.py`** (in this skill folder), piping a JSON payload on stdin:
   ```json
   {"note_path": "<abs path>", "subject": "<derived subject>",
    "bcc": ["<validated recipient>", "…"],
    "vault_footer_path": "digests/weekly/2026-…md",
    "attachments": ["<abs path to extra .md>", "…"]}
   ```
   The script builds the message and sends it: **From**/**To** = `GMAIL_SEND_ADDRESS` (self), **Bcc** = the validated recipients (addresses are NOT disclosed to each other — `send_message` strips the Bcc header before transmit). It renders the note's Markdown (frontmatter stripped) to styled HTML, attaches the raw `.md`, and emits a JSON result on stdout (or an `error`/`error_type` object + non-zero exit on failure — map `error_type` to the matching stop-and-report case below). See [Message body shape](#message-body-shape-v2--html--markdown-attachment).

`attachments` (optional) is a list of absolute paths attached verbatim after the note, each under its own basename. Use it when a parent note (a synthesis) should travel with its child notes. A missing path is a `note_missing` stop-and-report; nothing is sent.

Return:

```python
{
    "sent_to":  ["addr1@example.com", "addr2@example.com"],  # from the script's result
    "skipped":  [{"email": "bad@@invalid", "reason": "invalid format"}],  # from step 5
    "subject":  "[Weekly Intelligence Digest] 2026-06-22 — ...",
    "from":     "you@gmail.com",
    "html":     true,                # false → markdown lib absent, plain-text-only fallback
    "attached": "2026-06-22-weekly-intelligence-digest.md",
    "extra_attachments": []   # basenames of any `attachments` passed in
}
```

### `prompt_then_send(note_path, list_name=None)`

For research notes. Asks the user, then calls `send_note` or skips.

1. Resolve the send-to set (so the prompt can show the recipient count).
2. Ask the user: `"Send this research note to your distribution list (N recipients)? [y/n]"` — also show the first 3 recipients to confirm the right list. When `list_name` is given, name the segment in the prompt.
3. Parse the answer. `y` / `yes` / `send` → call `send_note(note_path, list_name=list_name)`. Anything else → skip.
4. Return `{action: "sent" | "skipped", ...}`.

### `auto_send(note_path, surface, list_name=None)`

Non-interactive path for `scheduled-agent-runner` step 11.

1. If `surface != "digest"` → no-op, return `{action: "noop", reason: "non-digest surface"}`.
2. Resolve the send-to set. Missing/empty → stop-and-report (surfaces in runner summary as `email_failed=...`).
3. Call `send_note(note_path, list_name=list_name)`. Return its result with `action: "sent"`.

This helper **never prompts** — non-interactive scheduled context. Misconfig still stop-and-reports per the rules below; the digest itself remains written.

The runner passes the firing category's `email_list`, and skips this call entirely when the category's `email` flag is false — so a vault-only category never reaches here.

### `show_list(list_name=None)`

User-facing diagnostic. Loads, parses, and prints the distribution-list contents — what would happen on the next send. No mail traffic. Useful before relying on auto-send.

With no argument, print **every segment** with its members plus the union that an unsegmented send would reach. With `list_name`, print just that segment (and stop-and-report if it doesn't exist, listing the ones that do).

## Parsing

The distribution-list file is Markdown. The parser scopes recipient extraction to a single named section so that documentation, format examples, and prose around the list never leak into the send:

1. Strip YAML frontmatter (the `---\n...\n---\n` block at the top, if present).
2. Strip HTML comments (`<!-- ... -->`) — anything inside is ignored, so commenting out a bullet pauses the recipient.
3. Find a recipients heading (H2, case-insensitive). `## Recipients` opens the **default** segment; `## Recipients: <name>` opens a **named** segment (`## Recipients: AI` → `ai`). Begin recipient-parsing **only** at the line after such a heading.
4. Stop recipient-parsing at the next `## ` heading (any title) or at end-of-file — unless that heading is itself a recipients heading, which opens the next segment. Subsections using `###` headings remain in-scope (groupings inside a segment are fine).
5. Inside the active region, a line contributes a recipient if:
   - It starts with `-` or `*` (a Markdown bullet) AND contains an email-shaped substring, OR
   - The entire line, after stripping whitespace, IS an email-shaped substring (no leading bullet required).
6. Lines starting with ` ``` ` (fenced code block boundary) are skipped, and the parser ignores everything between the open and close fence — code-block content is never a recipient.
7. Email regex: `\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b`.
8. Multiple emails on one bullet line are all extracted (`- alice@example.com, bob@example.com` works).
9. Case-insensitive deduplication, applied per segment and again across the union.

`parse_recipients` returns `{recipients, ignored, segments}`. **`recipients` is the union of every segment**, so a file using only the bare `## Recipients` heading behaves exactly as it did before segments existed — and splitting a list into named sections and deleting the bare heading never silently drops anyone from an unsegmented send. `segments` maps each name to its own members.

Sections OTHER than a recipients heading — `## How to edit`, `## Notes`, the document intro, etc. — are scanned for emails for diagnostics only; addresses found there are reported by `show_list` as "ignored (outside ## Recipients)" but never sent to. This lets the template carry inline format examples (`- you@gmail.com`) without making them live entries.

**Resolving a send** uses `recipients_for(text, list_name)`, never the raw parse:

- `list_name=None` → the union (`segment: "all"`).
- A known name → that segment alone.
- An unknown or empty name → **error, never a fallback to the union.** Silently blasting a niche digest to the whole list is the failure mode segments exist to prevent.

Validation:

- File missing → stop-and-report (case #1 below).
- No recipients heading at all → stop-and-report: `"email-distribution.md is missing the '## Recipients' heading. The skill only extracts addresses from bullets under that heading."`
- Heading present but no parsed recipients → stop-and-report: `"'## Recipients' section is empty. Add at least one '- you@example.com' line under that heading."`
- Named segment requested but absent or empty → cases #9/#10 below.

## Stop and report — enumerated cases

Each surfaces a structured error to the caller (and to the runner summary line for scheduled jobs):

1. **Distribution list missing** → `"email-distribution.md not found at vault/_config/email-distribution.md. Copy .claude/skills/email-sender/email-distribution.example.md to that path and edit."`
2. **`## Recipients` heading missing** → `"email-distribution.md exists but has no '## Recipients' heading. The skill only extracts addresses from bullets under that exact heading (case-insensitive). Add a '## Recipients' section and list recipients as bullets under it."`
3. **`## Recipients` section is empty** → `"'## Recipients' section parsed to zero recipients. Add at least one '- you@example.com' bullet under that heading."`
4. **`GMAIL_APP_PASSWORD` missing** → `"GMAIL_APP_PASSWORD not set in ~/.config/research-bot/env. Run 'scripts/set-gmail-credentials.sh \"you@gmail.com\" \"xxxx xxxx xxxx xxxx\"' to set."`
5. **`GMAIL_SEND_ADDRESS` missing** → similar.
6. **SMTP auth failure** → `"Gmail SMTP auth failed for <send-address>. App password may be expired or revoked — regenerate at https://myaccount.google.com/apppasswords."`
7. **SMTP send failure (network, server-level bounce)** → `"Send failed: <smtplib error>. Per-recipient results: [sent=N, skipped=M]."`
8. **Invalid email format on a recipient** → skip that recipient, continue with the rest, surface in the return `skipped` list (NOT a stop-and-report — degraded delivery proceeds).
9. **Named segment not found** → `"email-distribution.md has no '## Recipients: <name>' section. Sections found: [default, ai, security]. Either add that section or clear email_list in the category config."`
10. **Named segment empty** → `"'## Recipients: <name>' parsed to zero recipients. Add at least one '- you@example.com' bullet under that heading."`

Cases #9 and #10 never degrade to sending to everyone — an unresolvable segment means no send at all.

The vault note remains written even if email fails. Email is a delivery channel, not a write-blocker.

## Message body shape (v2 — HTML + Markdown attachment)

Built deterministically by `render_and_send.py` — no AI call in the send path, so scheduled `launchd` runs produce identical, testable output every time. The message is `multipart/mixed`:

```
multipart/mixed
├─ multipart/alternative
│   ├─ text/plain   {note markdown, frontmatter stripped} + footer   ← today's behavior
│   └─ text/html    styled render of the same markdown + footer      ← what mail clients show
└─ attachment       {note}.md  — the RAW vault file, frontmatter INCLUDED
```

- **HTML body**: the note's Markdown (frontmatter stripped) rendered via Python-Markdown (`extra`, `sane_lists`, `tables`, `fenced_code`, `toc`) and wrapped in a self-contained template — an embedded `<style>` block, no external CSS/fonts/remote assets. Styling is restrained: system font stack, ~640px container, bordered/striped tables, monospace code blocks, muted footer. Renders cleanly in Gmail and Apple Mail (the self-send target).
- **Plain-text part**: the raw Markdown + footer, unchanged from v1 — the fallback for clients that don't render HTML.
- **Attachment**: the note file **verbatim, including YAML frontmatter** — a true copy of the canonical vault file, so the Markdown source is always preserved.
- **Footer** (both parts):

  ```
  ---
  Landed in your vault at: {vault_footer_path}
  Sent via research-bot email-sender. Distribution list lives in your vault at _config/email-distribution.md.
  ```

**Graceful fallback**: if the `markdown` package isn't importable in the runtime `python3`, the script omits the HTML part and sends **plain-text-only** (v1 behavior) with the `.md` attachment still included, and returns `"html": false`. A missing dependency never blocks delivery — important for unattended scheduled runs. Install it via `python3 -m pip install -r scripts/requirements.txt`.

## Subject derivation

| Source | Subject template | Example |
|--------|------------------|---------|
| Digest (`vault/digests/{cadence}/...`) | `[{Cadence Title-Case} {Skill Title-Case}] {YYYY-MM-DD} — {first H1 of body, truncated to 60 chars}` | `[Weekly Intelligence Digest] 2026-06-22 — Copilot Q3 roadmap & 3 new CVEs` |
| Research (`vault/research/{topic}/...`) | `[{Topic Title-Case} Research] {YYYY-MM-DD} — {frontmatter.title, truncated to 60 chars}` | `[Copilot Research] 2026-06-22 — Agentic features & SR 11-7 implications` |
| Override | Use `subject_override` verbatim. | n/a |

Truncation at 60 chars + `…` keeps the subject readable. Note frontmatter `title` is the source of truth when present; H1 of body is the fallback.

## Composes with

- [`vault-writer`](../vault-writer/SKILL.md) — successful return triggers email-sender invocation. vault-writer does NOT call email-sender; the calling skill makes the explicit call.
- [`scheduled-agent-runner`](../scheduled-agent-runner/SKILL.md) — step 11 calls `auto_send`.
- Category 1 researchers (`copilot-deep-dive`, `sdlc-best-practice`, `financial-regulator-watch`, `ai-governance-research`, `peer-bank-tech-intel`, `incident-postmortem-research`, `copilot-faq-answerer`, …) — call `prompt_then_send` after `vault-writer.write_research` succeeds.

## Acceptance test (single SMTP round-trip)

0. Install the renderer dependency: `python3 -m pip install -r scripts/requirements.txt` (gives the runtime `python3` the `markdown` package).
1. Create a minimal `email-distribution.md` in the vault with one bullet pointing to the user's own email.
2. Pick any existing digest in `~/Obsidian/Research-Brain/digests/` (ideally one with a table and a code block, to exercise the renderer).
3. Invoke: `email-sender.send_note("<that path>")`.
4. Confirm: email lands in inbox within ~10 seconds; subject follows the template; the body **renders as styled HTML** (headings, tables, code all formatted — not raw `#`/`|` ASCII); footer references the vault path; and a **`.md` attachment** is present whose bytes equal the vault note (frontmatter included). Result JSON reports `"html": true` and `"attached": "<note>.md"`.
5. Fallback drill: run `render_and_send.py` under a `python3` without `markdown` installed (or temporarily force the `ImportError` path); confirm the mail still sends **plain-text-only** with the `.md` attached and the result reports `"html": false` — no crash.
6. Misconfig drill: remove `GMAIL_APP_PASSWORD` from env; re-invoke; confirm the `missing_app_password` stop-and-report (case #4) surfaces exactly as documented.
7. Bad-recipient drill: add `bad@@invalid` to the list; send; confirm the valid recipient gets mail and `skipped` lists the bad entry.
8. Pause drill: wrap a bullet with `<!-- ... -->`; re-parse; confirm that address is excluded.
