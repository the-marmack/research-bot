"""Deterministic tests for the email MIME builder + send driver.

Exercises render_and_send.py without sending mail: SMTP is monkeypatched.
"""
import json
import io
import os
from contextlib import redirect_stdout

import pytest

from _util import SKILLS, load_module

RAS_PATH = SKILLS / "email-sender" / "render_and_send.py"

SAMPLE_NOTE = """---
title: Test Digest
tags: [test]
---
# Weekly Intelligence Digest

## TL;DR

Some **bold** text and a [link](https://example.com).

| Source | Tier |
|--------|------|
| GitHub | A    |

- item one
- item two

```python
print("hello")
```
"""


@pytest.fixture
def ras(tmp_path, monkeypatch):
    """Load render_and_send with RESEARCH_BOT_ENV pointed at a temp env file."""
    env = tmp_path / "env"
    env.write_text("GMAIL_SEND_ADDRESS=me@gmail.com\nGMAIL_APP_PASSWORD=secretpw\n")
    monkeypatch.setenv("RESEARCH_BOT_ENV", str(env))
    mod = load_module(RAS_PATH, "render_and_send")
    from pathlib import Path
    mod.ENV_PATH = Path(str(env))
    mod._ENV_FILE = env  # test handle
    return mod


@pytest.fixture
def note(tmp_path):
    p = tmp_path / "2026-07-21-test-digest.md"
    p.write_text(SAMPLE_NOTE, encoding="utf-8")
    return p


def test_strip_frontmatter(ras):
    out = ras.strip_frontmatter(SAMPLE_NOTE)
    assert not out.startswith("---")
    assert "# Weekly Intelligence Digest" in out


def test_read_env(ras):
    env = ras.read_env(ras.ENV_PATH)
    assert env["GMAIL_SEND_ADDRESS"] == "me@gmail.com"
    assert env["GMAIL_APP_PASSWORD"] == "secretpw"


def _walk_types(msg):
    return [p.get_content_type() for p in msg.walk()]


def test_build_message_multipart_structure(ras, note):
    payload = {"note_path": str(note), "subject": "[Test] subject",
               "bcc": ["a@x.com", "b@y.com"], "vault_footer_path": "digests/x.md"}
    msg, html_used, attached, _ = ras.build_message(payload, "me@gmail.com")
    assert html_used is True
    assert attached == "2026-07-21-test-digest.md"
    assert msg.get_content_type() == "multipart/mixed"
    assert msg["To"] == "me@gmail.com" and msg["From"] == "me@gmail.com"
    assert msg["Bcc"] == "a@x.com, b@y.com"
    types = _walk_types(msg)
    assert "multipart/alternative" in types
    assert "text/plain" in types
    assert "text/html" in types


def test_html_body_renders_markdown(ras, note):
    payload = {"note_path": str(note), "subject": "s", "bcc": [],
               "vault_footer_path": "digests/x.md"}
    msg, _, _, _ = ras.build_message(payload, "me@gmail.com")
    html = next(p.get_payload(decode=True).decode()
                for p in msg.walk() if p.get_content_type() == "text/html")
    assert "<table>" in html            # table rendered
    assert "<h1" in html                # heading rendered
    assert "<code>" in html or "<pre>" in html
    assert "rb-container" in html and "<style>" in html


def test_attachment_is_raw_note_with_frontmatter(ras, note):
    payload = {"note_path": str(note), "subject": "s", "bcc": [],
               "vault_footer_path": "digests/x.md"}
    msg, _, _, _ = ras.build_message(payload, "me@gmail.com")
    att = next(p for p in msg.walk() if p.get_content_disposition() == "attachment")
    assert att.get_payload(decode=True) == note.read_text().encode("utf-8")
    assert att.get_filename() == "2026-07-21-test-digest.md"


def test_plain_part_has_no_frontmatter(ras, note):
    payload = {"note_path": str(note), "subject": "s", "bcc": [],
               "vault_footer_path": "digests/x.md"}
    msg, _, _, _ = ras.build_message(payload, "me@gmail.com")
    plain = next(p.get_payload(decode=True).decode()
                 for p in msg.walk() if p.get_content_type() == "text/plain")
    assert "# Weekly Intelligence Digest" in plain
    assert "title: Test Digest" not in plain


def test_markdown_absent_falls_back_to_plain(ras, note, monkeypatch):
    monkeypatch.setattr(ras, "HAVE_MARKDOWN", False)
    payload = {"note_path": str(note), "subject": "s", "bcc": [],
               "vault_footer_path": "digests/x.md"}
    msg, html_used, _, _ = ras.build_message(payload, "me@gmail.com")
    assert html_used is False
    types = _walk_types(msg)
    assert "text/html" not in types
    assert "text/plain" in types
    assert any(p.get_content_disposition() == "attachment" for p in msg.walk())


def _run_main(ras, payload, monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port):
            sent["host"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            sent["login"] = (u, p)

        def send_message(self, m):
            sent["subject"] = m["Subject"]

    monkeypatch.setattr(ras.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = ras.main()
    return rc, json.loads(buf.getvalue()), sent


def test_main_success(ras, note, monkeypatch):
    payload = {"note_path": str(note), "subject": "[Test] s",
               "bcc": ["a@x.com", "b@y.com"], "vault_footer_path": "digests/x.md"}
    rc, result, sent = _run_main(ras, payload, monkeypatch)
    assert rc == 0
    assert result["html"] is True
    assert result["sent_to"] == ["a@x.com", "b@y.com"]
    assert result["attached"] == "2026-07-21-test-digest.md"
    assert sent["login"] == ("me@gmail.com", "secretpw")
    assert sent["host"] == ("smtp.gmail.com", 465)


def test_main_missing_app_password(ras, note, monkeypatch):
    ras._ENV_FILE.write_text("GMAIL_SEND_ADDRESS=me@gmail.com\n")
    payload = {"note_path": str(note), "subject": "s"}
    rc, err, _ = _run_main(ras, payload, monkeypatch)
    assert rc == 1
    assert err["error_type"] == "missing_app_password"


def test_main_missing_note(ras, monkeypatch):
    payload = {"note_path": "/nope/missing.md", "subject": "s"}
    rc, err, _ = _run_main(ras, payload, monkeypatch)
    assert rc == 1
    assert err["error_type"] == "note_missing"


def test_main_bad_input(ras, monkeypatch):
    payload = {"subject": "s"}  # missing note_path
    rc, err, _ = _run_main(ras, payload, monkeypatch)
    assert rc == 1
    assert err["error_type"] == "bad_input"


def test_main_smtp_auth_failure(ras, note, monkeypatch):
    class FailSMTP:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            raise ras.smtplib.SMTPAuthenticationError(535, b"bad")

        def send_message(self, m):
            pass

    monkeypatch.setattr(ras.smtplib, "SMTP_SSL", FailSMTP)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"note_path": str(note), "subject": "s", "bcc": ["a@x.com"]})))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = ras.main()
    assert rc == 1
    assert json.loads(buf.getvalue())["error_type"] == "smtp_auth"


def test_extra_attachments_are_attached_verbatim(ras, note, tmp_path):
    child_a = tmp_path / "child-a.md"
    child_b = tmp_path / "child-b.md"
    child_a.write_text("---\ntitle: A\n---\n# A\n", encoding="utf-8")
    child_b.write_text("# B body only\n", encoding="utf-8")
    payload = {"note_path": str(note), "subject": "s", "bcc": [],
               "vault_footer_path": "research/x.md",
               "attachments": [str(child_a), str(child_b)]}
    msg, _, main_name, extra = ras.build_message(payload, "me@gmail.com")
    atts = [p for p in msg.walk() if p.get_content_disposition() == "attachment"]
    names = [a.get_filename() for a in atts]
    assert names == ["2026-07-21-test-digest.md", "child-a.md", "child-b.md"]
    assert main_name == "2026-07-21-test-digest.md"
    assert extra == ["child-a.md", "child-b.md"]
    assert atts[1].get_payload(decode=True) == child_a.read_bytes()
    assert atts[2].get_payload(decode=True) == child_b.read_bytes()


def test_extra_attachment_missing_is_note_missing_error(ras, note, monkeypatch):
    payload = {"note_path": str(note), "subject": "s", "bcc": ["a@x.com"],
               "attachments": [str(note.parent / "does-not-exist.md")]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = ras.main()
    out = json.loads(buf.getvalue())
    assert rc == 1
    assert out["error_type"] == "note_missing"
    assert "does-not-exist.md" in out["error"]


def test_no_attachments_key_keeps_single_attachment(ras, note):
    payload = {"note_path": str(note), "subject": "s", "bcc": []}
    msg, _, _, extra = ras.build_message(payload, "me@gmail.com")
    atts = [p for p in msg.walk() if p.get_content_disposition() == "attachment"]
    assert len(atts) == 1
    assert extra == []
