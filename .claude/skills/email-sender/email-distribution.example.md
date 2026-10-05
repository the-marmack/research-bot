---
title: Email Distribution
created: 2026-06-21
updated: 2026-06-21
tags: [config]
source_skill: human
confidence: 3
links: []
---

# Email Distribution

Everyone listed below receives:

- **Every scheduled digest** when its job fires (no per-digest opt-in needed).
- **Any research note** you choose to forward — you'll be asked `[y/n]` per note before it sends.

## How to edit

Add a bullet per recipient **under the `## Recipients` heading below**. The skill only parses bullets in that one section — bullets in this "How to edit" section (or anywhere else in the file) are ignored. All of these bullet formats work:

```
- you@gmail.com
- you@gmail.com — Self (optional note after the em-dash is ignored)
- Alice <alice@example.com>
- alice@example.com, bob@example.com   (both extracted from one bullet)
```

To **pause** an entry without deleting it, wrap the bullet in an HTML comment inside the `## Recipients` section:

```
<!-- - paused.person@example.com — out on PTO until July -->
```

You can write whatever prose, notes, or additional sections you want above or below `## Recipients` — only that section's bullets become recipients.

## Optional: narrower lists per digest

If some digests should reach a smaller audience than others, add **named segments** alongside (or instead of) the bare list:

```
## Recipients: Security
- ciso@example.com — CISO
- appsec-lead@example.com

## Recipients: AI
- vp.eng@example.com — VP Eng
```

Point a digest at one by setting `email_list: security` in its category config (`vault/_config/digests/<id>.md`). A digest with no `email_list` goes to **everyone across all sections**, so adding segments never quietly narrows an existing send. A digest naming a segment that doesn't exist **fails loudly** rather than falling back to everyone.

Segment names are case-insensitive (`## Recipients: Security` → `security`). A person can appear in more than one segment; they receive one copy per digest, not duplicates within a digest.

## Recipients

- you@gmail.com — Self (always include this — useful for verification + your own copy)

<!-- Add more bullets below as you grow your distribution.
     - vp.eng@example.com — VP Eng
     - ciso@example.com — CISO
-->

## Notes

This file is loaded fresh on every email-sender invocation. There is no edit-time hook — a missing `## Recipients` heading or an empty section will surface at the next scheduled-digest fire as `email_failed=<reason>`. The digest itself still lands in the vault; only the send fails.

To validate ahead of the next run, ask Claude Code: `"show me my email distribution list"` — `email-sender.show_list` loads + parses + prints the current recipients without sending anything.
