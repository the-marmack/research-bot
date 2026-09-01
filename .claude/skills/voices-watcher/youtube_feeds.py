"""Deterministic helpers for ``voices-watcher``: roster shape + YouTube Atom feeds.

Two concerns, kept together because both are the pure, unit-testable half of the
same skill: the canonical roster-CSV column contract (:data:`ROSTER_COLUMNS`,
:func:`validate_roster_header`, :func:`is_org_role`) and YouTube channel-feed
resolution (everything else).

YouTube publishes a per-channel Atom feed at::

    https://www.youtube.com/feeds/videos.xml?channel_id=<UC...>

No API key, no HTML scraping, no ``yt-dlp``. ``voices-watcher`` uses this to
surface new videos per voice, which is why the ``youtube`` column in
``voices.csv`` stores the canonical ``/channel/UC...`` URL rather than an
``@handle`` URL: the channel-id form converts to a feed URL with zero network
calls and zero failure modes.

Resolving an ``@handle`` to a channel id is the one fragile step, so
:func:`resolve_channel_id` is deliberately strict. A channel page embeds the
ids of *featured* channels alongside its own, so taking the first bare
``"channelId"`` match silently returns the wrong channel — during roster
construction that mis-resolved five of six channels to a neighbour (Yannic
Kilcher's second channel, ``LiveUnderflow``, ``Robert Miles 2``, …) with no
error raised. Read the canonical link or ``externalId`` instead, and verify the
resolved id against the feed's own ``<title>`` before trusting it.

Feed *content* is untrusted input: titles and descriptions are attacker-
controllable, and prompt injection via YouTube metadata is a published,
demonstrated attack (Rehberger, embracethered.com). Callers must route every
parsed item through ``prompt-injection-guard`` before letting a model act on
it. This module deliberately does no network I/O so it stays trivially
testable; fetching is the caller's job (via ``source-fetcher``).
"""
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

FEED_BASE = "https://www.youtube.com/feeds/videos.xml?channel_id="
CHANNEL_URL_BASE = "https://www.youtube.com/channel/"

#: A YouTube channel id: literal "UC" followed by 22 base64url characters.
CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{22}")

_CANONICAL_RE = re.compile(
    r'rel="canonical"\s+href="https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"'
)
_EXTERNAL_ID_RE = re.compile(r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"')

_ATOM = "{http://www.w3.org/2005/Atom}"
_YT = "{http://www.youtube.com/xml/schemas/2015}"


def is_channel_id(value):
    """True if ``value`` is exactly a channel id (not a URL containing one)."""
    if not value:
        return False
    return bool(re.fullmatch(CHANNEL_ID_RE, value.strip()))


def channel_id_from_url(url):
    """Extract a channel id from a channel URL or an existing feed URL.

    Returns ``None`` for ``@handle`` URLs — those need :func:`resolve_channel_id`
    against the fetched page, because the id is not present in the URL.
    """
    if not url:
        return None
    url = url.strip()
    if is_channel_id(url):
        return url

    parsed = urlparse(url)
    if parsed.netloc and "youtube.com" not in parsed.netloc:
        return None

    # Already a feed URL: .../feeds/videos.xml?channel_id=UC...
    if "channel_id" in (parsed.query or ""):
        values = parse_qs(parsed.query).get("channel_id") or []
        if values and is_channel_id(values[0]):
            return values[0]
        return None

    # Canonical channel URL: /channel/UC...
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) >= 2 and parts[0] == "channel" and is_channel_id(parts[1]):
        return parts[1]

    return None


def feed_url_for(value):
    """Return the Atom feed URL for a channel id, channel URL, or feed URL.

    Returns ``None`` when the input cannot be resolved offline (notably
    ``@handle`` URLs, and any non-YouTube URL).
    """
    channel_id = channel_id_from_url(value)
    if channel_id is None:
        return None
    return FEED_BASE + channel_id


def channel_url_for(channel_id):
    """Return the canonical channel URL for a channel id."""
    if not is_channel_id(channel_id):
        raise ValueError(f"not a channel id: {channel_id!r}")
    return CHANNEL_URL_BASE + channel_id.strip()


def resolve_channel_id(html):
    """Extract a channel's *own* id from its fetched HTML page.

    Reads the canonical link first, then ``externalId``. Never falls back to a
    bare ``"channelId"`` match — a channel page also embeds the ids of featured
    channels, and the first match is frequently one of those.

    Returns ``None`` rather than guessing when neither marker is present.
    """
    if not html:
        return None
    for pattern in (_CANONICAL_RE, _EXTERNAL_ID_RE):
        match = pattern.search(html)
        if match:
            return match.group(1)
    return None


def parse_feed(xml_text):
    """Parse a YouTube channel Atom feed into a list of item dicts.

    Each item: ``{video_id, title, url, published, channel_title}``.
    Entries missing a video id or URL are skipped. Raises
    :class:`xml.etree.ElementTree.ParseError` on malformed XML so the caller
    can report the failure rather than silently returning zero items — see the
    "stop and report" rule in ``_meta/conventions.md``.
    """
    root = ET.fromstring(xml_text)

    channel_title_el = root.find(f"{_ATOM}title")
    channel_title = (channel_title_el.text or "").strip() if channel_title_el is not None else ""

    items = []
    for entry in root.findall(f"{_ATOM}entry"):
        video_id_el = entry.find(f"{_YT}videoId")
        video_id = (video_id_el.text or "").strip() if video_id_el is not None else ""

        url = ""
        for link in entry.findall(f"{_ATOM}link"):
            if link.get("rel") == "alternate" and link.get("href"):
                url = link.get("href")
                break

        if not video_id or not url:
            continue

        title_el = entry.find(f"{_ATOM}title")
        published_el = entry.find(f"{_ATOM}published")
        items.append(
            {
                "video_id": video_id,
                "title": (title_el.text or "").strip() if title_el is not None else "",
                "url": url,
                "published": (published_el.text or "").strip() if published_el is not None else "",
                "channel_title": channel_title,
            }
        )
    return items


def is_short(url):
    """True if a video URL is a YouTube Short (``/shorts/<id>``).

    Shorts are vertical clips under a minute. On the 2026-08-22 test run 2 of
    14 surfaced items were Shorts (a 3Blue1Brown puzzle teaser, a DEF CON
    hallway clip) — neither is research material, and both cost a reader the
    same scan as a real item.
    """
    if not url:
        return False
    return "/shorts/" in urlparse(url.strip()).path


def partition_shorts(items):
    """Split parsed feed items into ``(regular, shorts)``, order preserved.

    Returns both halves rather than dropping Shorts outright so the caller can
    report how many were withheld — silently discarding them would read as
    "nothing was there", which the "stop and report" rule in
    ``_meta/conventions.md`` forbids.
    """
    regular, shorts = [], []
    for item in items or []:
        (shorts if is_short(item.get("url")) else regular).append(item)
    return regular, shorts


def is_org_role(role):
    """True if a roster role marks an organisation rather than a person.

    Convention: roles ending in ``(org)`` — e.g. ``AI security (org)``. Org rows
    are polled for new items but are **not** seeded into ``vault/people/``,
    which is for people.
    """
    return bool(role) and role.strip().lower().endswith("(org)")


# --- roster CSV contract -----------------------------------------------------
# One roster per digest category at vault/_config/rosters/{category}.csv. The
# column set is fixed so the example file, the curator, and the tests all agree.

ROSTER_COLUMNS = (
    "handle", "name", "bio_snippet", "role",
    "substack", "twitter", "youtube", "linkedin", "blog", "podcast",
    "added_date", "notes",
)


def validate_roster_header(header):
    """Return None if ``header`` is the canonical roster header, else a reason.

    Order matters: the curator fills cells positionally and must never reorder a
    human-maintained file, so a reordered header is an error rather than
    something to accommodate.
    """
    if header is None:
        return "roster has no header row"
    actual = tuple(h.strip() for h in header)
    if actual == ROSTER_COLUMNS:
        return None
    missing = [c for c in ROSTER_COLUMNS if c not in actual]
    extra = [c for c in actual if c not in ROSTER_COLUMNS]
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {missing}")
        if extra:
            parts.append(f"unexpected {extra}")
        return "roster header " + " and ".join(parts)
    return (f"roster header has the right columns in the wrong order: "
            f"{list(actual)} != {list(ROSTER_COLUMNS)}")


def _main(argv):
    """CLI: resolve channel URLs/handles to the row values voices.csv needs.

    Usage: python3 youtube_feeds.py <channel-url-or-id> [...]
    """
    import urllib.request

    exit_code = 0
    for raw in argv:
        channel_id = channel_id_from_url(raw)
        if channel_id is None:
            try:
                request = urllib.request.Request(
                    raw if raw.startswith("http") else f"https://www.youtube.com/@{raw}",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(request, timeout=25) as response:
                    html = response.read().decode("utf-8", "replace")
                channel_id = resolve_channel_id(html)
            except Exception as exc:  # noqa: BLE001 - report, don't crash the batch
                print(f"FAIL {raw}: {exc}")
                exit_code = 1
                continue
        if channel_id is None:
            print(f"FAIL {raw}: no canonical channel id found")
            exit_code = 1
            continue
        print(f"OK   {raw}\n     channel_url: {channel_url_for(channel_id)}"
              f"\n     feed_url:    {feed_url_for(channel_id)}")
    return exit_code


if __name__ == "__main__":
    import sys

    sys.exit(_main(sys.argv[1:]))
