"""Deterministic tests for the email distribution-list parser.

The parser decides WHO receives email, so its behavior is load-bearing.
"""
from pathlib import Path

import pytest

from _util import SKILLS, load_module

er = load_module(SKILLS / "email-sender" / "email_recipients.py", "email_recipients")


def parse(text):
    return er.parse_recipients(text)


def test_basic_bullets_under_recipients():
    doc = """## Recipients
- alice@example.com
- bob@example.com
"""
    assert parse(doc)["recipients"] == ["alice@example.com", "bob@example.com"]


def test_frontmatter_is_stripped():
    doc = """---
title: Email Distribution
tags: [config]
---
## Recipients
- alice@example.com
"""
    assert parse(doc)["recipients"] == ["alice@example.com"]


def test_only_recipients_section_is_live():
    doc = """## How to edit
- example@nowhere.com
## Recipients
- real@example.com
## Notes
- footer@example.com
"""
    out = parse(doc)
    assert out["recipients"] == ["real@example.com"]
    # emails outside the section are reported as ignored, never sent
    assert "example@nowhere.com" in out["ignored"]
    assert "footer@example.com" in out["ignored"]


def test_html_comment_pauses_a_recipient():
    doc = """## Recipients
- active@example.com
<!-- - paused@example.com — out on PTO -->
"""
    out = parse(doc)
    assert out["recipients"] == ["active@example.com"]
    assert "paused@example.com" not in out["recipients"]
    assert "paused@example.com" not in out["ignored"]


def test_multiple_emails_on_one_bullet():
    doc = """## Recipients
- alice@example.com, bob@example.com
"""
    assert parse(doc)["recipients"] == ["alice@example.com", "bob@example.com"]


def test_case_insensitive_dedup_preserves_first():
    doc = """## Recipients
- Alice@Example.com
- alice@example.com
"""
    assert parse(doc)["recipients"] == ["Alice@Example.com"]


def test_fenced_code_block_is_ignored():
    doc = """## Recipients
- real@example.com
```
- codeblock@example.com
```
"""
    out = parse(doc)
    assert out["recipients"] == ["real@example.com"]
    assert "codeblock@example.com" not in out["recipients"]


def test_bare_email_line_without_bullet_counts():
    doc = """## Recipients
plain@example.com
"""
    assert parse(doc)["recipients"] == ["plain@example.com"]


def test_recipients_heading_is_case_insensitive():
    doc = """## RECIPIENTS
- a@example.com
"""
    assert parse(doc)["recipients"] == ["a@example.com"]


def test_subsection_stays_in_scope():
    doc = """## Recipients
### Leadership
- ciso@example.com
### Engineering
- vp@example.com
"""
    assert parse(doc)["recipients"] == ["ciso@example.com", "vp@example.com"]


def test_no_recipients_section_yields_empty():
    doc = """## Notes
- someone@example.com
"""
    assert parse(doc)["recipients"] == []


def test_validate_accepts_normal_and_rejects_malformed():
    assert er.validate("a@b.co")
    assert not er.validate("bad@@invalid")
    assert not er.validate("no-at-sign.com")
    assert not er.validate("has space@example.com")


def test_live_distribution_list_parses():
    """Sanity: if a live list exists, it parses to at least one valid recipient.

    Asserts structure, never identities — the live list is personal data and
    must not be mirrored into this repo.
    """
    live = Path.home() / "Obsidian/Research-Brain/_config/email-distribution.md"
    if not live.exists():
        pytest.skip("live distribution list not present")
    out = parse(live.read_text(encoding="utf-8"))
    assert out["recipients"], "live distribution list parsed to zero recipients"
    assert all(er.validate(a) for a in out["recipients"])


# --- named segments (Phase 2) -------------------------------------------------
# `## Recipients` is the default segment; `## Recipients: <name>` opens a named
# one. `recipients` stays the union so unsegmented files behave as they always did.

def test_bare_recipients_is_the_default_segment():
    doc = """## Recipients
- alice@example.com
"""
    out = parse(doc)
    assert out["segments"] == {"default": ["alice@example.com"]}
    assert out["recipients"] == ["alice@example.com"]


def test_named_segment_parses():
    doc = """## Recipients: AI
- ai@example.com
"""
    out = parse(doc)
    assert out["segments"] == {"ai": ["ai@example.com"]}


def test_multiple_named_segments_are_separate():
    doc = """## Recipients: AI
- ai@example.com

## Recipients: Security
- sec@example.com
"""
    out = parse(doc)
    assert out["segments"]["ai"] == ["ai@example.com"]
    assert out["segments"]["security"] == ["sec@example.com"]


def test_segment_names_are_case_insensitive():
    doc = """## RECIPIENTS: Security
- sec@example.com
"""
    assert "security" in parse(doc)["segments"]


def test_recipients_is_the_union_of_all_segments():
    """The backward-compat guarantee: splitting into named sections and dropping
    the bare heading must not silently lose anyone from an unsegmented send."""
    doc = """## Recipients: AI
- ai@example.com

## Recipients: Security
- sec@example.com
"""
    assert parse(doc)["recipients"] == ["ai@example.com", "sec@example.com"]


def test_union_dedups_a_person_in_two_segments():
    doc = """## Recipients: AI
- both@example.com

## Recipients: Security
- both@example.com
"""
    out = parse(doc)
    assert out["recipients"] == ["both@example.com"]
    assert out["segments"]["ai"] == out["segments"]["security"] == ["both@example.com"]


def test_subsection_stays_in_scope_inside_a_named_segment():
    doc = """## Recipients: AI
### Researchers
- r@example.com
"""
    assert parse(doc)["segments"]["ai"] == ["r@example.com"]


def test_non_recipients_h2_still_closes_scope_and_ignores():
    doc = """## Recipients: AI
- ai@example.com

## Notes
- someone@example.com
"""
    out = parse(doc)
    assert out["segments"]["ai"] == ["ai@example.com"]
    assert out["ignored"] == ["someone@example.com"]


def test_empty_segment_name_is_out_of_scope():
    """`## Recipients:` with nothing after the colon names no segment."""
    doc = """## Recipients:
- nobody@example.com
"""
    out = parse(doc)
    assert out["segments"] == {}
    assert out["ignored"] == ["nobody@example.com"]


# --- recipients_for: resolving an actual send --------------------------------

def test_recipients_for_no_name_returns_union():
    doc = """## Recipients: AI
- ai@example.com

## Recipients: Security
- sec@example.com
"""
    out = er.recipients_for(doc)
    assert out["error"] is None
    assert out["segment"] == "all"
    assert out["recipients"] == ["ai@example.com", "sec@example.com"]


def test_recipients_for_named_returns_only_that_segment():
    doc = """## Recipients: AI
- ai@example.com

## Recipients: Security
- sec@example.com
"""
    out = er.recipients_for(doc, "ai")
    assert out["error"] is None
    assert out["recipients"] == ["ai@example.com"]


def test_recipients_for_unknown_segment_errors_and_does_not_fall_back():
    """A typo must not blast a niche digest to the whole list."""
    doc = """## Recipients
- everyone@example.com
"""
    out = er.recipients_for(doc, "typo")
    assert out["error"] is not None
    assert out["recipients"] == []
    assert "default" in out["error"]  # names the segments that do exist


def test_recipients_for_empty_segment_errors():
    doc = """## Recipients: AI

## Recipients: Security
- sec@example.com
"""
    out = er.recipients_for(doc, "ai")
    assert out["error"] is not None
    assert out["recipients"] == []
