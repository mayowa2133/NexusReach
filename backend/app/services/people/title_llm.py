"""LLM tie-break for person titles the keyword classifier cannot bucket.

The keyword classifier in ``classify.py`` defaults ambiguous titles to the
peers bucket, which silently pollutes results with titles like "Partner",
"Talent Champion", or "Specialist II". This module batch-classifies only that
ambiguous tail with a single LLM call per search (capped), caches verdicts in
Redis by normalized title for 30 days, and fails soft to the keyword result
on any error - so it can never make a search slower than the LLM timeout or
break one outright.
"""

from __future__ import annotations

import json
import logging
import re

from app.clients import llm_client, search_cache_client

logger = logging.getLogger(__name__)

TITLE_CLASS_CACHE_PREFIX = "people:title_class:v1:"
TITLE_CLASS_CACHE_TTL_SECONDS = 30 * 86400
MAX_TITLES_PER_CALL = 15
VALID_BUCKETS = {"recruiter", "hiring_manager", "peer", "other"}

_SYSTEM_PROMPT = (
    "You classify job titles for a networking tool. For each title, decide "
    "which contact bucket the person belongs to at their company:\n"
    '- "recruiter": talent acquisition, sourcing, recruiting, people ops hiring roles\n'
    '- "hiring_manager": leads a team that hires (manager, director, head, VP, lead with reports)\n'
    '- "peer": individual contributor doing the work\n'
    '- "other": cannot tell, or not a working role (board member, investor, intern alumni)\n'
    "Respond with ONLY a JSON object mapping each input title verbatim to one "
    "bucket string. No prose, no markdown fences."
)


def normalize_title_key(title: str | None) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _cache_key(normalized: str) -> str:
    return TITLE_CLASS_CACHE_PREFIX + normalized


async def resolve_ambiguous_titles(titles: list[str]) -> dict[str, str]:
    """Classify ambiguous titles, returning {normalized_title: bucket}.

    Buckets are from ``VALID_BUCKETS``; "other" means the LLM could not place
    the title and callers should keep their keyword fallback. Returns {} on
    any failure.
    """
    normalized = []
    seen: set[str] = set()
    for raw in titles:
        key = normalize_title_key(raw)
        if key and key not in seen:
            seen.add(key)
            normalized.append(key)
    if not normalized:
        return {}
    normalized = normalized[:MAX_TITLES_PER_CALL]

    resolved: dict[str, str] = {}
    uncached: list[str] = []
    for key in normalized:
        try:
            cached = await search_cache_client.get_json(_cache_key(key))
        except Exception:
            cached = None
        if isinstance(cached, str) and cached in VALID_BUCKETS:
            resolved[key] = cached
        else:
            uncached.append(key)

    if not uncached:
        return resolved

    try:
        result = await llm_client.generate_message(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=json.dumps(uncached),
            max_tokens=512,
        )
        raw = result.get("draft") or ""
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in LLM response")
        parsed = json.loads(raw[start : end + 1])
        for title, bucket in parsed.items():
            key = normalize_title_key(title)
            if key in uncached and isinstance(bucket, str) and bucket in VALID_BUCKETS:
                resolved[key] = bucket
                try:
                    await search_cache_client.set_json(
                        _cache_key(key), bucket, ttl_seconds=TITLE_CLASS_CACHE_TTL_SECONDS
                    )
                except Exception:
                    logger.debug("title class cache write failed", exc_info=True)
    except Exception:
        logger.warning(
            "LLM title tie-break failed for %d titles; keeping keyword buckets",
            len(uncached),
            exc_info=True,
        )

    return resolved
