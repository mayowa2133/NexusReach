"""LLM-based relevance scoring for people discovery candidates.

Uses a single batched LLM call to score each candidate's relevance to
the target job/team.  Gracefully degrades to returning all candidates
unfiltered if no LLM is configured or the call fails.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

RELEVANCE_SYSTEM_PROMPT = """\
You are a recruiter relevance scorer. Given a job description context and \
a list of LinkedIn profile candidates, score each candidate's relevance to \
the target role on a scale of 1-5.

Scoring criteria:
- 5: Same team/department, similar role, strong match
- 4: Same department, related role
- 3: Related department or role, could be useful connection
- 2: Same company but different area
- 1: Not relevant

Return ONLY valid JSON, no other text:
{"scores": [{"index": 0, "score": 3}, {"index": 1, "score": 5}]}
"""

MIN_RELEVANCE_SCORE = 3


async def score_candidate_relevance(
    candidates: list[dict],
    job_title: str,
    company_name: str,
    team_keywords: list[str],
    department: str,
    min_score: int = 1,
) -> list[dict]:
    """Score and filter candidates by relevance to the target job.

    Uses the configured LLM to score each candidate (1-5) based on their
    title and LinkedIn snippet.  Returns candidates scoring >= ``min_score``.

    Graceful degradation:
        - No LLM configured → returns all candidates unfiltered
        - LLM call fails → returns all candidates unfiltered
        - Malformed JSON response → returns all candidates unfiltered

    Args:
        candidates: Person dicts from Brave Search (must have ``snippet`` key).
        job_title: Target job title (e.g. "Senior Software Engineer").
        company_name: Company name.
        team_keywords: Team-specific keywords (e.g. ["payments", "backend"]).
        department: Department name (e.g. "engineering").
        min_score: Minimum relevance score to include (1-5, default 1 = all).

    Returns:
        Filtered list of candidates with ``relevance_score`` added.
    """
    if not candidates:
        return []

    # Build the user prompt with all candidates
    team_str = ", ".join(team_keywords) if team_keywords else "general"
    user_prompt = (
        f"Target role: {job_title} at {company_name}\n"
        f"Department: {department}\n"
        f"Team focus: {team_str}\n\n"
        f"Candidates:\n"
    )

    for i, c in enumerate(candidates[:15]):
        snippet = (c.get("snippet") or "")[:150]
        name = c.get("full_name", "Unknown")
        title = c.get("title", "")
        user_prompt += f"[{i}] {name} — {title}"
        if snippet:
            user_prompt += f' | "{snippet}"'
        user_prompt += "\n"

    # Lazy import to avoid circular dependency and to detect provider
    try:
        from app.clients.llm_client import generate_message
    except ImportError:
        logger.debug("LLM client not available, skipping relevance scoring")
        return candidates

    try:
        result = await generate_message(
            system_prompt=RELEVANCE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=256,
        )
    except (ValueError, Exception) as exc:
        # ValueError = no LLM provider configured
        # Other exceptions = network errors, API failures
        logger.debug("LLM scoring failed (%s), returning all candidates", exc)
        return candidates

    # Parse JSON scores from the LLM response
    draft = result.get("draft", "")
    # Strip markdown code fences if present
    draft = re.sub(r"```(?:json)?\s*", "", draft).strip().rstrip("`")

    try:
        parsed = json.loads(draft)
    except json.JSONDecodeError:
        logger.debug("LLM returned malformed JSON, returning all candidates")
        return candidates

    scores = parsed.get("scores", [])
    if not isinstance(scores, list):
        return candidates

    # Build index → score mapping
    score_map: dict[int, int] = {}
    for entry in scores:
        idx = entry.get("index")
        score = entry.get("score")
        if isinstance(idx, int) and isinstance(score, int) and 0 <= idx < len(candidates):
            score_map[idx] = score

    # Attach scores to all candidates (only first 15 are scored by LLM)
    for i, candidate in enumerate(candidates[:15]):
        candidate["relevance_score"] = score_map.get(i, MIN_RELEVANCE_SCORE)

    # Candidates beyond index 15 get a default score so they aren't silently dropped
    for candidate in candidates[15:]:
        candidate.setdefault("relevance_score", MIN_RELEVANCE_SCORE)

    # Filter by the caller's threshold
    filtered = [
        c for c in candidates
        if c.get("relevance_score", 0) >= min_score
    ]

    # If filtering removed everything and a threshold was applied, return top 2
    if not filtered and candidates and min_score > 1:
        scored = sorted(
            candidates[:15],
            key=lambda c: c.get("relevance_score", 0),
            reverse=True,
        )
        filtered = scored[:2]

    return filtered
