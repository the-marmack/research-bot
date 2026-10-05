#!/usr/bin/env python3
"""render_and_send.py — the email-sender skill's deterministic send path.

Renders a vault note's Markdown to a styled HTML email, builds a
multipart/mixed message (multipart/alternative body: text/plain = raw
Markdown, text/html = rendered + styled) with the *raw* note attached as a
`.md` file, and sends it via Gmail SMTP.

This exists so the multipart / HTML / attachment construction is
deterministic and testable rather than re-derived by an agent on every
unattended `launchd` run. No AI, no network model call.

Invocation (from the email-sender skill, after it has resolved the note
path, parsed + validated recipients, and derived the subject):

    echo '{"note_path": "...", "subject": "...", "bcc": ["a@x.com"],
           "attachments": ["optional/extra/note.md", "..."],
           "vault_footer_path": "digests/weekly/2026-...md"}' \
        | python3 render_and_send.py

Reads a single JSON object from stdin. Prints a single JSON result object
to stdout. Exit 0 on send, exit 1 on a stop-and-report failure (with
`error` / `error_type` in the JSON).

Credentials come from `~/.config/research-bot/env` (override with the
RESEARCH_BOT_ENV env var for testing): GMAIL_SEND_ADDRESS + GMAIL_APP_PASSWORD.

Graceful degradation: if the `markdown` package is not importable, the
message is sent plain-text-only (exactly the pre-HTML behavior) with the
`.md` attachment still included, and the result reports `"html": false`.
A missing dependency never breaks delivery.
"""

import json
import os
import re
import smtplib
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

try:
    import markdown as _markdown

    HAVE_MARKDOWN = True
except ImportError:
    HAVE_MARKDOWN = False


ENV_PATH = Path(os.environ.get("RESEARCH_BOT_ENV", "~/.config/research-bot/env")).expanduser()

FOOTER_TEMPLATE = (
    "Landed in your vault at: {vault_path}\n"
    "Sent via research-bot email-sender. "
    "Distribution list lives in your vault at _config/email-distribution.md."
)

# Restrained, email-client-safe styling. Gmail / Apple Mail (the self-send
# target) render an embedded <style> block well. No external CSS, no remote
# assets, no web fonts — everything is self-contained.
HTML_STYLE = """
  body { margin: 0; padding: 0; background: #f4f5f7; }
  .rb-container {
    max-width: 640px; margin: 0 auto; padding: 28px 32px;
    background: #ffffff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 Helvetica, Arial, sans-serif;
    color: #1f2328; font-size: 15px; line-height: 1.6;
  }
  .rb-container h1 { font-size: 24px; line-height: 1.3; margin: 0 0 16px;
    padding-bottom: 8px; border-bottom: 2px solid #e1e4e8; }
  .rb-container h2 { font-size: 19px; margin: 28px 0 10px;
    padding-bottom: 6px; border-bottom: 1px solid #e1e4e8; }
  .rb-container h3 { font-size: 16px; margin: 22px 0 8px; }
  .rb-container p { margin: 0 0 14px; }
  .rb-container a { color: #0969da; text-decoration: none; }
  .rb-container a:hover { text-decoration: underline; }
  .rb-container ul, .rb-container ol { margin: 0 0 14px; padding-left: 24px; }
  .rb-container li { margin: 4px 0; }
  .rb-container blockquote {
    margin: 0 0 14px; padding: 2px 16px; color: #57606a;
    border-left: 3px solid #d0d7de; }
  .rb-container code {
    font-family: "SF Mono", SFMono-Regular, Consolas, "Liberation Mono",
                 Menlo, monospace;
    font-size: 13px; background: #f0f1f3; padding: 2px 5px;
    border-radius: 4px; }
  .rb-container pre {
    background: #f6f8fa; padding: 14px 16px; border-radius: 6px;
    overflow-x: auto; border: 1px solid #e1e4e8; }
  .rb-container pre code { background: none; padding: 0; font-size: 13px; }
  .rb-container table {
    border-collapse: collapse; width: 100%; margin: 0 0 16px;
    font-size: 14px; }
  .rb-container th, .rb-container td {
    border: 1px solid #d0d7de; padding: 7px 11px; text-align: left;
    vertical-align: top; }
  .rb-container th { background: #f6f8fa; font-weight: 600; }
  .rb-container tr:nth-child(even) td { background: #fafbfc; }
  .rb-container hr {
    border: none; border-top: 1px solid #e1e4e8; margin: 24px 0; }
  .rb-footer {
    margin-top: 28px; padding-top: 14px; border-top: 1px solid #e1e4e8;
    color: #8b949e; font-size: 12px; line-height: 1.5; }
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>{style}</style>
</head>
<body>
<div class="rb-container">
{body_html}
<div class="rb-footer">{footer_html}</div>
</div>
</body>
</html>"""


def strip_frontmatter(text):
    """Remove a leading YAML frontmatter block (---\\n...\\n---\\n)."""
    if text.startswith("---"):
        # Match the opening --- line and the next --- line.
        m = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.DOTALL)
        if m:
            return text[m.end():]
    return text


def read_env(path):
    """Parse KEY=value lines from the credentials env file."""
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        env[key.strip()] = val.strip()
    return env


def render_html(body_md, footer_text):
    """Render Markdown body + footer to a styled, self-contained HTML doc."""
    body_html = _markdown.markdown(
        body_md,
        extensions=["extra", "sane_lists", "tables", "fenced_code", "toc"],
        output_format="html5",
    )
    footer_html = footer_text.replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;"
    ).replace("\n", "<br>\n")
    return HTML_TEMPLATE.format(
        style=HTML_STYLE, body_html=body_html, footer_html=footer_html
    )


def build_message(payload, from_addr):
    """Assemble the multipart/mixed message.

    Returns (msg, html_used, note_attachment_name, extra_attachment_names).
    """
    note_path = Path(payload["note_path"]).expanduser()
    raw_text = note_path.read_text(encoding="utf-8")
    body_md = strip_frontmatter(raw_text)
    footer_text = FOOTER_TEMPLATE.format(
        vault_path=payload.get("vault_footer_path", str(note_path))
    )

    plain_body = f"{body_md.rstrip()}\n\n---\n{footer_text}\n"

    outer = MIMEMultipart("mixed")
    outer["Subject"] = payload["subject"]
    outer["From"] = from_addr
    outer["To"] = from_addr
    bcc = payload.get("bcc", [])
    if bcc:
        outer["Bcc"] = ", ".join(bcc)

    alt = MIMEMultipart("alternative")
    # Plain part first, HTML second — mail clients render the last part they
    # can display (RFC 2046 §5.1.4), so HTML wins where supported.
    alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    html_used = False
    if HAVE_MARKDOWN:
        alt.attach(MIMEText(render_html(body_md, footer_text), "html", "utf-8"))
        html_used = True
    outer.attach(alt)

    # Attach the raw note verbatim (frontmatter included) as a .md file.
    attachment = MIMEApplication(
        raw_text.encode("utf-8"), _subtype="octet-stream"
    )
    attachment.add_header(
        "Content-Disposition", "attachment", filename=note_path.name
    )
    outer.attach(attachment)

    # Optional extra attachments (e.g. child research notes under a parent).
    # Each is attached verbatim under its own basename; a missing path raises
    # FileNotFoundError so the caller gets a clean stop-and-report.
    extra_names = []
    for extra in payload.get("attachments", []) or []:
        extra_path = Path(extra).expanduser()
        part = MIMEApplication(extra_path.read_bytes(), _subtype="octet-stream")
        part.add_header(
            "Content-Disposition", "attachment", filename=extra_path.name
        )
        outer.attach(part)
        extra_names.append(extra_path.name)

    return outer, html_used, note_path.name, extra_names


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as e:
        print(json.dumps({"error": f"invalid JSON payload: {e}",
                          "error_type": "bad_input"}))
        return 1

    for key in ("note_path", "subject"):
        if not payload.get(key):
            print(json.dumps({"error": f"missing required field: {key}",
                              "error_type": "bad_input"}))
            return 1

    env = read_env(ENV_PATH)
    from_addr = env.get("GMAIL_SEND_ADDRESS")
    app_password = env.get("GMAIL_APP_PASSWORD")
    if not from_addr:
        print(json.dumps({
            "error": ("GMAIL_SEND_ADDRESS not set in "
                      "~/.config/research-bot/env."),
            "error_type": "missing_send_address"}))
        return 1
    if not app_password:
        print(json.dumps({
            "error": ("GMAIL_APP_PASSWORD not set in "
                      "~/.config/research-bot/env. Run "
                      "'scripts/set-gmail-credentials.sh' to set."),
            "error_type": "missing_app_password"}))
        return 1

    try:
        msg, html_used, attached_name, extra_names = build_message(
            payload, from_addr)
    except FileNotFoundError as e:
        print(json.dumps({
            "error": f"note or attachment not found: {e.filename or payload['note_path']}",
            "error_type": "note_missing"}))
        return 1

    bcc = payload.get("bcc", [])
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(from_addr, app_password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        print(json.dumps({
            "error": (f"Gmail SMTP auth failed for {from_addr}. App password "
                      "may be expired or revoked — regenerate at "
                      "https://myaccount.google.com/apppasswords."),
            "error_type": "smtp_auth"}))
        return 1
    except (smtplib.SMTPException, OSError) as e:
        print(json.dumps({
            "error": f"Send failed: {e}",
            "error_type": "smtp_send"}))
        return 1

    print(json.dumps({
        "sent_to": bcc,
        "subject": payload["subject"],
        "from": from_addr,
        "html": html_used,
        "attached": attached_name,
        "extra_attachments": extra_names,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
