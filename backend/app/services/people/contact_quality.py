"""Sanity checks on discovered contact fields.

People are discovered by parsing SERP results, so occasionally something that
isn't a person's job title ends up in the title field. From a live search
audited 2026-07-26 (28 contacts at one company):

    Brian Delahunty   "Wonderful post from Letícia about their…"   <- a feed post
    Eric Geniesse     "Stripe"                                      <- the company
    Ryan Peterman     ""                                            <- nothing
    Christopher K.    Solutions Architect - Marketplace…            <- truncated name

That was ~18% of surfaced contacts either unusable or embarrassing. It matters
more than it looks, because these fields do not just sit in a list — they are
fed to the drafting model. "Hi Christopher K." reads as obviously automated,
which undercuts the one thing the product is selling.

Posture: **clean, don't discard.** Recall is expensive (a discovered contact
took real provider calls) and a person with a bad title is still a real person
worth reaching. So a prose blob or a company name is stripped to ``None``,
leaving the contact intact but honestly unlabelled — and only a candidate with
no usable identity at all is worth rejecting.
"""

from __future__ import annotations

import re

# A real job title is short. Anything past this is a sentence, a summary, or a
# scraped paragraph — LinkedIn headlines top out well below it.
_MAX_TITLE_CHARS = 120

# Sentence-shaped text. Tested only after abbreviations are removed: real
# titles are full of them ("Sr.", "Jr.", "Ph.D.", "Sr. IP Product Engineer"),
# and treating those periods as sentence ends discarded valid titles.
_SENTENCE_RE = re.compile(r"[.!?]\s+\S")

_TITLE_ABBREVIATIONS = re.compile(
    r"\b(sr|jr|dr|mr|ms|mrs|prof|st|inc|ltd|co|corp|ph\.?d|m\.?s|b\.?s|u\.?s|e\.?g|i\.?e)\.",
    re.IGNORECASE,
)

# First-person / post voice. A title never says "I" or "we".
_PROSE_MARKERS = (
    " i ", " i'm", " we ", " we're", " our ", " my ", " you ", " your ",
    "thanks", "congrat", "excited to", "happy to", "thrilled",
    "check out", "read more", "click here", "join us", "hiring for",
    "post from", "posted", "comment", "repost", "shared a",
)

# Placeholder junk some boards and parsers emit.
_JUNK_TITLES = {
    "n/a", "na", "none", "null", "-", "--", "unknown", "location", "title",
    "linkedin", "profile", "view profile", "see more",
}

# "Christopher K." / "Johnson G." — LinkedIn truncates surnames for
# out-of-network profiles.
_TRUNCATED_SURNAME_RE = re.compile(r"^\s*(\S+)\s+([A-Z])\.?\s*$")


def looks_like_prose(value: str) -> bool:
    """True when the text reads as sentence content rather than a job title."""
    text = (value or "").strip()
    if not text:
        return False
    if len(text) > _MAX_TITLE_CHARS:
        return True
    # Drop abbreviation periods before asking "is this a sentence?"
    without_abbreviations = _TITLE_ABBREVIATIONS.sub(" ", text)
    if _SENTENCE_RE.search(without_abbreviations.rstrip(".")):
        return True
    padded = f" {text.lower()} "
    return any(marker in padded for marker in _PROSE_MARKERS)


def clean_title(title: str | None, company_name: str | None = None) -> str | None:
    """Return a usable job title, or ``None`` when the value carries no signal.

    ``None`` is deliberate and better than a wrong title: downstream ranking and
    drafting can both cope with an unknown title, but neither can tell that
    "Wonderful post from Letícia" isn't this person's actual role.
    """
    text = (title or "").strip().strip("|-–—·•").strip()
    if not text:
        return None
    if text.lower() in _JUNK_TITLES:
        return None
    if looks_like_prose(text):
        return None
    # The company name alone is not a role ("Eric Geniesse — Stripe").
    company = (company_name or "").strip().lower()
    if company and text.lower() == company:
        return None
    # A title that is only punctuation/digits tells us nothing either.
    if not re.search(r"[A-Za-z]{2}", text):
        return None
    return text


def greeting_name(full_name: str | None) -> str | None:
    """The name to open a message with.

    Uses the first name alone rather than the stored display name: LinkedIn
    hands back "Christopher K." for out-of-network profiles, and greeting
    someone with a truncated surname is a tell that the message was generated.
    Falls back to the full name when there's nothing to trim.
    """
    name = (full_name or "").strip()
    if not name:
        return None
    truncated = _TRUNCATED_SURNAME_RE.match(name)
    if truncated:
        return truncated.group(1)
    first = name.split()[0]
    # Guard against a leading initial ("J. Smith") — that isn't a usable
    # greeting either, so prefer the next token.
    if len(first.rstrip(".")) <= 1:
        parts = name.split()
        return parts[1] if len(parts) > 1 else first
    return first


def is_usable_contact(candidate: dict) -> bool:
    """False only when there is no identity left to act on.

    Cleaning handles bad titles; this catches the rarer case of a result that
    never described a person — no name and no profile URL — which would show up
    as a blank row the user can do nothing with.
    """
    name = (candidate.get("full_name") or "").strip()
    if not name:
        return False
    if looks_like_prose(name) or name.lower() in _JUNK_TITLES:
        return False
    return True
