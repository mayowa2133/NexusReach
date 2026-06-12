"""Bullet and text normalization primitives for resume artifacts."""

from __future__ import annotations

import logging
import re


from app.utils.company_identity import slugify_company_name

logger = logging.getLogger(__name__)


def _clean(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def _slugify_label(value: str | None, fallback: str) -> str:
    slug = slugify_company_name(value) or ""
    return slug or fallback


_BULLET_MARKER_RE = re.compile(r"^[\-•·▪►]\s*")


_PARTICLE_CONCAT_RE = re.compile(
    r"\b(and|or|with|using|from|on|in|by|for|to|via|plus|of)([A-Z][a-z])"
)


_PARTICLE_ACRONYM_RE = re.compile(
    r"\b(and|or|with|using|from|on|in|by|for|to|via|plus|of)([A-Z]{2,}\b)"
)


_LOWER_CONCAT_RE = re.compile(
    r"\b(and|or|with|from|via|plus)("
    r"design|ensemble|data|test|tested|tests|build|builds|"
    r"deploy|deploys|implement|implements|integrate|integrates|"
    r"deliver|delivers|sample|samples|series|set|sets|focus|focused|"
    r"context|user|users|manage|managed|monitor|monitors|"
    r"maintain|maintained|virtual|rolling|stream|streams|"
    r"queries|query|service|services|model|models|api|apis|"
    r"client|clients|server|servers|database|databases|dashboard|"
    r"feature|features|metric|metrics|pipeline|pipelines|"
    r"workflow|workflows|signal|signals|library|libraries|"
    r"export|exports|import|imports|endpoint|endpoints|"
    r"preview|previews|release|releases|component|components|"
    r"session|sessions|request|requests|response|responses|"
    r"token|tokens|thread|threads|queue|queues"
    r")\b"
)


_ARTICLE_CONCAT_RE = re.compile(
    r"\b(a|an)("
    r"virtual|sample|series|set|service|model|user|client|server|"
    r"database|dashboard|feature|metric|pipeline|workflow|signal|"
    r"library|design|context|focus|build|deploy|test|monitor"
    r")\b"
)


def _normalize_bullet_text(text: str) -> str:
    """Clean PDF-extraction artifacts:
    - join hyphenated line wraps (e.g. "archi-\ntecture" -> "architecture")
    - collapse intra-bullet soft wraps (newline inside a bullet -> space)
    - fix stray space-before-punctuation (e.g. "Swift ,Xcode" -> "Swift, Xcode")
    - re-insert dropped spaces between particle + Capital (e.g. "andPydantic"
      -> "and Pydantic", "onVirtual" -> "on Virtual")
    - re-insert dropped spaces for known particle+lower concats
      (e.g. "anddesign", "fromrolling", "avirtual")
    - normalize whitespace
    """
    if not text:
        return ""
    # Join hyphenated line-wraps: "archi-\ntecture" -> "architecture"
    text = re.sub(r"([A-Za-z])-\s*\n\s*([A-Za-z])", r"\1\2", text)
    # Collapse remaining newlines inside the bullet to a single space.
    text = re.sub(r"\s*\n\s*", " ", text)
    # Fix "word ,word" / "word , word" -> "word, word". Applies to , ; :
    text = re.sub(r"\s+([,;:])", r"\1", text)
    # Ensure space after comma/semicolon if a word follows immediately.
    text = re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", text)
    # Space before `+Capital` when it looks like an N+1 enumeration boundary
    # (e.g. "LangChain +OpenAI" -> "LangChain + OpenAI"). Skip all-caps runs
    # like "+EV" which are acronym markers, not list joins.
    text = re.sub(r"(\+)([A-Z][a-z])", r"\1 \2", text)
    # Re-insert dropped spaces: particle directly glued to a Capital-Lower word.
    text = _PARTICLE_CONCAT_RE.sub(r"\1 \2", text)
    # Same for ALL-CAPS acronyms glued to a particle ("andLLM" -> "and LLM").
    text = _PARTICLE_ACRONYM_RE.sub(r"\1 \2", text)
    # Fix "word -word" (stray space before hyphen) -> "word-word"
    # when the hyphen joins two word tokens (not an em-dash-like pause).
    text = re.sub(r"([A-Za-z])\s+-([A-Za-z])", r"\1-\2", text)
    # Particle + lowercase-word concats from PDF (curated suffix list).
    text = _LOWER_CONCAT_RE.sub(r"\1 \2", text)
    text = _ARTICLE_CONCAT_RE.sub(r"\1 \2", text)
    # Collapse double spaces.
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _split_description_bullets(description: str | None) -> list[str]:
    """Split a description blob into individual bullets.

    Prefer real bullet markers (•/-/·/▪) at line starts. Lines that do NOT
    start with a marker are treated as continuations of the previous bullet
    (handles resume PDFs that wrap long bullets across lines).
    """
    text = (description or "").strip()
    if not text:
        return []

    raw_lines = [ln.strip() for ln in re.split(r"\n+", text) if ln.strip()]
    has_markers = any(_BULLET_MARKER_RE.match(ln) for ln in raw_lines)

    bullets: list[str] = []
    if has_markers:
        for ln in raw_lines:
            if _BULLET_MARKER_RE.match(ln):
                bullets.append(_BULLET_MARKER_RE.sub("", ln).strip())
            else:
                if bullets:
                    # Re-join with newline so _normalize_bullet_text can repair wraps.
                    bullets[-1] = f"{bullets[-1]}\n{ln}"
                else:
                    bullets.append(ln)
    else:
        bullets = raw_lines

    cleaned: list[str] = []
    for b in bullets:
        normalized = _normalize_bullet_text(b)
        if len(normalized) >= 2:
            cleaned.append(normalized)
    return cleaned


def _split_project_bullets(description: str | None) -> list[str]:
    parts = _split_description_bullets(description)
    if parts:
        return parts[:3]
    text = (description or "").strip()
    if not text:
        return []
    sentences = [
        _normalize_bullet_text(part).strip().lstrip("-•·▪ ").strip()
        for part in re.split(r"(?<=[.!?])\s+", text)
    ]
    return [part for part in sentences if len(part) > 2][:3]


def _extract_phone(raw_text: str | None) -> str | None:
    if not raw_text:
        return None
    match = re.search(r"(\+?1?[\s\-.(]*\d{3}[\s\-.)]*\d{3}[\s\-]*\d{4})", raw_text)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"{digits[:3]} {digits[3:6]} {digits[6:]}"


def _merge_unique(values: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean_value = _clean(value)
        normalized = clean_value.lower()
        if not clean_value or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(clean_value)
    return merged


def _metric_tokens(text: str) -> set[str]:
    return set(re.findall(r"\b\d[\d,]*\+?%?\b|\b\d+\+\b", text))


_METRIC_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<value>\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?:\s*/\s*\$?\d+(?:\.\d+)?)?(?:\+|%|[KkMmBb])?)"
    r"(?![A-Za-z0-9])"
)


_METRIC_UNIT_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of",
    "on", "or", "over", "per", "the", "through", "to", "using", "via", "while",
    "with", "within",
}


def _quantifiable_measure_spans(text: str) -> list[tuple[int, int]]:
    """Return spans for numeric impact phrases worth bolding in resume bullets."""
    spans: list[tuple[int, int]] = []
    for match in _METRIC_VALUE_RE.finditer(text):
        start, end = match.span("value")
        value = match.group("value")
        cursor = end
        unit_count = 0

        while unit_count < 3:
            unit_match = re.match(r"\s+([A-Za-z][A-Za-z0-9+/#.-]*)", text[cursor:])
            if unit_match is None:
                break
            raw_unit = unit_match.group(1)
            unit = raw_unit.strip(".,;:")
            if not unit or unit.lower() in _METRIC_UNIT_STOPWORDS:
                break
            cursor += unit_match.start(1) + len(unit)
            unit_count += 1
            if cursor < len(text) and text[cursor] in ",.;:":
                break

        digits_only = re.sub(r"\D", "", value)
        is_bare_year = (
            len(digits_only) == 4
            and 1900 <= int(digits_only) <= 2099
            and not re.search(r"[+%KkMmBb$/]", value)
        )
        if is_bare_year and unit_count == 0:
            continue

        spans.append((start, cursor))
    return spans


def _latex_plain_text(line: str) -> str:
    text = _clean(line)
    substitutions = [
        (re.compile(r"\\href\{[^{}]*\}\{([^{}]*)\}"), r"\1"),
        (re.compile(r"\\url\{([^{}]*)\}"), r"\1"),
        (re.compile(r"\\textbf\{([^{}]*)\}"), r"\1"),
        (re.compile(r"\\textit\{([^{}]*)\}"), r"\1"),
        (re.compile(r"\\hl\{([^{}]*)\}"), r"\1"),
        (re.compile(r"\\sout\{([^{}]*)\}"), r"\1"),
    ]
    previous = ""
    while previous != text:
        previous = text
        for pattern, replacement in substitutions:
            text = pattern.sub(replacement, text)
    text = re.sub(r"^\\item\s*", " ", text)
    text = text.replace(r"\\", " ")
    text = re.sub(r"\\([&%$#_{}])", r"\1", text)
    text = re.sub(r"\\textbackslash\{\}", r"\\", text)
    text = re.sub(r"\\[a-zA-Z*]+(?:\[[^\]]*\])?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return _clean(text)


def _resume_body_contains_term(body: str, term: str) -> bool:
    normalized = _clean(term).lower()
    if not normalized:
        return False
    if re.fullmatch(r"[a-z0-9+#.]+", normalized):
        return re.search(
            rf"(?<![a-z0-9+#.]){re.escape(normalized)}(?![a-z0-9+#.])",
            body,
        ) is not None
    return normalized in body
