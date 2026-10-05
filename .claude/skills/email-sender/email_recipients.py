#!/usr/bin/env python3
"""email_recipients.py — parse the email-sender distribution list.

Extracts recipient addresses from `email-distribution.md` per the spec in
SKILL.md "## Parsing". Pure string->list logic so it is unit-testable and lives
in exactly one place; the send flow calls this instead of re-deriving the
parser ad hoc on every invocation.

CLI: `python email_recipients.py <path-to-email-distribution.md> [--list NAME]`
prints `{"recipients": [...], "ignored": [...], "segments": {...}}` as JSON.
`recipients` are the extracted, case-insensitively de-duplicated addresses under
any `## Recipients` heading; `ignored` are email-shaped strings found OUTSIDE
those sections (diagnostic only — never sent to). Apply `validate()` per
recipient before sending; a malformed entry is skipped, not fatal.

A bare `## Recipients` heading is the default segment. `## Recipients: AI`
opens a named segment ("ai"). `recipients` is the UNION of the default segment
and every named one, so a file using only the bare heading behaves exactly as it
did before segments existed. Use `recipients_for()` to resolve an actual send.
"""
import json
import re
import sys

# Email-shaped substring (extraction). Matches the SKILL.md "## Parsing" regex.
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# Per-recipient validation applied before sending (stricter single-@ shape).
VALID_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_frontmatter(text):
    """Remove a leading YAML frontmatter block (---\\n...\\n---\\n)."""
    if text.startswith("---"):
        m = FRONTMATTER_RE.match(text)
        if m:
            return text[m.end():]
    return text


def validate(addr):
    """True if addr passes the send-time recipient validation."""
    return bool(VALID_RE.match(addr))


def _dedup_ci(items, already=None):
    """Case-insensitive de-dup, order-preserving. `already` seeds seen keys."""
    seen = set(already or ())
    out = []
    for e in items:
        k = e.lower()
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out, seen


DEFAULT_SEGMENT = "default"


def segment_name(h2_text):
    """Resolve an H2's title to a segment name, or None if out of scope.

    'Recipients'      -> 'default'
    'Recipients: AI'  -> 'ai'
    anything else     -> None  (closes the recipient scope)
    """
    t = h2_text.strip().lower()
    if t == "recipients":
        return DEFAULT_SEGMENT
    if t.startswith("recipients:"):
        return t[len("recipients:"):].strip() or None
    return None


def parse_recipients(text):
    """Parse a distribution-list Markdown doc.

    Returns {"recipients": [...], "ignored": [...], "segments": {...}}:
      - segments: {name: [addresses]} — one entry per `## Recipients[: name]`
        H2 present in the doc, each case-insensitively de-duped.
      - recipients: the UNION across every segment, de-duped, order-preserving.
        A doc with only a bare `## Recipients` therefore yields exactly what it
        did before segments existed.
      - ignored: email-shaped strings outside any recipients section (diagnostic).
    """
    text = strip_frontmatter(text)
    text = COMMENT_RE.sub("", text)

    current = None
    in_fence = False
    per_segment = {}
    ignored = []

    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("```"):          # fenced code block boundary
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if s.startswith("## "):          # H2 opens/closes a recipients scope
            current = segment_name(s[3:])
            if current is not None:
                per_segment.setdefault(current, [])
            continue
        # `###` subsections stay in scope; other lines fall through to matching.
        emails = EMAIL_RE.findall(s)
        if not emails:
            continue
        if current is not None:
            is_bullet = s.startswith("-") or s.startswith("*")
            whole_is_email = EMAIL_RE.fullmatch(s) is not None
            if is_bullet or whole_is_email:
                per_segment[current].extend(emails)
        else:
            ignored.extend(emails)

    segments = {}
    for name, addrs in per_segment.items():
        segments[name], _ = _dedup_ci(addrs)

    union = [a for addrs in per_segment.values() for a in addrs]
    recipients, seen = _dedup_ci(union)
    ignored_dedup, _ = _dedup_ci(ignored, already=seen)
    return {"recipients": recipients, "ignored": ignored_dedup, "segments": segments}


def recipients_for(text, list_name=None):
    """Resolve the actual send-to set for a digest.

    Returns {"recipients": [...], "segment": str, "error": str|None}.

    `list_name=None` sends to the union (today's behaviour). A named list
    resolves to that segment alone. An unknown or empty segment is an ERROR and
    never falls back to the union — silently blasting a niche digest to the full
    list is the failure mode segments exist to prevent.
    """
    parsed = parse_recipients(text)
    segments = parsed["segments"]

    if list_name is None:
        return {"recipients": parsed["recipients"], "segment": "all", "error": None}

    key = list_name.strip().lower()
    if key not in segments:
        found = ", ".join(sorted(segments)) or "(none)"
        return {"recipients": [], "segment": key, "error": (
            f"email-distribution.md has no '## Recipients: {list_name}' section. "
            f"Sections found: [{found}]. Either add that section or clear "
            f"email_list in the category config.")}
    if not segments[key]:
        return {"recipients": [], "segment": key, "error": (
            f"'## Recipients: {list_name}' parsed to zero recipients. Add at "
            f"least one '- you@example.com' bullet under that heading.")}
    return {"recipients": segments[key], "segment": key, "error": None}


def main(argv):
    args = argv[1:]
    list_name = None
    if "--list" in args:
        i = args.index("--list")
        if i + 1 >= len(args):
            print(json.dumps({"error": "--list requires a segment name"}))
            return 2
        list_name = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        print(json.dumps(
            {"error": "usage: email_recipients.py <dist-file> [--list NAME]"}))
        return 2
    try:
        with open(args[0], encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(json.dumps({"error": f"cannot read {args[0]}: {e}"}))
        return 1
    if list_name is None:
        print(json.dumps(parse_recipients(text)))
        return 0
    resolved = recipients_for(text, list_name)
    print(json.dumps(resolved))
    return 1 if resolved["error"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
