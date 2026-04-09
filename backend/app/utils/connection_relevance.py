"""Score LinkedIn connections by relevance to a specific job context.

Pure utility — no DB access. Parses connection headlines to extract
role type, department, team signals, and seniority, then scores each
connection against a JobContext for warm-path ranking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.utils.job_context import (
    DEPARTMENT_MAP,
    IC_MANAGER_ROLES,
    SENIORITY_PATTERNS,
    TECHNICAL_KEYWORDS_MAP,
    JobContext,
    _contains_keyword,
)

# ---------------------------------------------------------------------------
# Local keyword sets (avoids importing from people_service.py)
# ---------------------------------------------------------------------------

_RECRUITER_KEYWORDS: set[str] = {
    "recruiter",
    "recruiting",
    "sourcer",
    "sourcing",
    "talent acquisition",
    "talent scout",
    "university programs",
    "campus recruiter",
    "talent partner",
}

_MANAGER_KEYWORDS: set[str] = {
    "manager",
    "director",
    "head of",
    "vp",
    "vice president",
}

_ENGINEER_KEYWORDS: set[str] = {
    "engineer",
    "developer",
    "scientist",
    "analyst",
    "architect",
    "swe",
    "sde",
    "sre",
}

SENIORITY_RANK: dict[str, int] = {
    "intern": 0,
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "staff": 4,
    "lead": 4,
    "principal": 5,
    "manager": 5,
    "director": 6,
    "vp": 7,
    "executive": 8,
}

# Regex to split headline into segments on | • , ;
_SEGMENT_SPLIT = re.compile(r"[|•;]")

# Patterns for "at Company" / "@ Company" extraction
_AT_COMPANY = re.compile(r"\b(?:at|@)\s+([^|•;,()]+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Headline signals
# ---------------------------------------------------------------------------


@dataclass
class HeadlineSignals:
    role_type: str = "other"  # "recruiter" | "manager" | "engineer" | "other"
    department: str | None = None
    team_keywords: list[str] = field(default_factory=list)
    seniority: str | None = None
    product_hint: str | None = None


def parse_headline(headline: str | None) -> HeadlineSignals:
    """Extract structured signals from a LinkedIn headline."""
    if not headline or not headline.strip():
        return HeadlineSignals()

    text = " ".join(headline.split()).lower()
    signals = HeadlineSignals()

    # --- Role type ---
    if any(_contains_keyword(text, kw) for kw in _RECRUITER_KEYWORDS):
        signals.role_type = "recruiter"
    elif _is_people_manager(text):
        signals.role_type = "manager"
    elif any(_contains_keyword(text, kw) for kw in _ENGINEER_KEYWORDS):
        signals.role_type = "engineer"

    # --- Department (highest specificity wins) ---
    best_dept: str | None = None
    best_words = 0
    for keyword, dept in DEPARTMENT_MAP.items():
        if _contains_keyword(text, keyword):
            word_count = len(keyword.split())
            if word_count > best_words:
                best_words = word_count
                best_dept = dept
    signals.department = best_dept

    # --- Team keywords (up to 2) ---
    matched_teams: list[str] = []
    for label, keywords in TECHNICAL_KEYWORDS_MAP.items():
        for kw in keywords:
            if _contains_keyword(text, kw):
                matched_teams.append(label)
                break
        if len(matched_teams) >= 2:
            break
    signals.team_keywords = matched_teams

    # --- Seniority ---
    for pattern, level in SENIORITY_PATTERNS:
        if re.search(pattern, text):
            signals.seniority = level
            break

    # --- Product hint (text after | or • that isn't the company name) ---
    segments = _SEGMENT_SPLIT.split(headline)
    if len(segments) > 1:
        # Take the last meaningful segment as the product hint
        for seg in reversed(segments[1:]):
            cleaned = seg.strip()
            if cleaned and len(cleaned) > 2 and len(cleaned) < 80:
                low = cleaned.lower()
                # Skip generic suffixes
                if low in ("remote", "hybrid", "onsite", "us", "uk", "canada"):
                    continue
                signals.product_hint = cleaned
                break

    return signals


def _is_people_manager(text: str) -> bool:
    """Check if headline indicates a people-manager (not IC-manager like PM)."""
    if not any(_contains_keyword(text, kw) for kw in _MANAGER_KEYWORDS):
        return False
    # Exclude IC-manager roles
    for pattern in IC_MANAGER_ROLES:
        if re.search(pattern, text):
            return False
    return True


# ---------------------------------------------------------------------------
# Relevance scoring
# ---------------------------------------------------------------------------


def score_connection_relevance(
    headline: str | None,
    company_name: str | None,
    job_context: JobContext,
) -> tuple[int, HeadlineSignals, str]:
    """Score a connection's relevance to a job. Returns (score, signals, label)."""
    signals = parse_headline(headline)

    if not headline or not headline.strip():
        label = f"At {company_name}" if company_name else "Connection"
        return 5, signals, label

    score = 0
    reasons: list[str] = []

    # Recruiter bonus (25 pts)
    if signals.role_type == "recruiter":
        score += 25
        reasons.append("Recruiter")

    # Department match (30 pts)
    dept_match = signals.department is not None and signals.department == job_context.department
    if dept_match:
        score += 30
        reasons.append("Same department")

    # Team keyword overlap (10 pts each, max 20)
    job_teams = set(job_context.team_keywords)
    conn_teams = set(signals.team_keywords)
    overlap = job_teams & conn_teams
    team_pts = min(len(overlap) * 10, 20)
    score += team_pts
    if overlap:
        reasons.append("Same team")

    # Product/team name match (15 pts)
    if signals.product_hint and job_context.product_team_names:
        hint_lower = signals.product_hint.lower()
        for product in job_context.product_team_names:
            if product.lower() in hint_lower or hint_lower in product.lower():
                score += 15
                reasons.append("Same product")
                break

    # Seniority proximity (10 pts)
    if signals.seniority and job_context.seniority:
        rank_a = SENIORITY_RANK.get(signals.seniority, 2)
        rank_b = SENIORITY_RANK.get(job_context.seniority, 2)
        distance = abs(rank_a - rank_b)
        seniority_pts = max(0, 10 - distance * 3)
        score += seniority_pts
        if seniority_pts >= 7:
            reasons.append("Similar level")

    # Manager in same department bonus (10 pts)
    if signals.role_type == "manager" and dept_match:
        score += 10

    # Build label
    if "Same team" in reasons or ("Same department" in reasons and "Same product" in reasons):
        label = "Same team"
    elif "Same department" in reasons:
        label = "Same department"
    elif "Recruiter" in reasons:
        label = "Recruiter"
    elif "Similar level" in reasons:
        label = "Similar role"
    else:
        label = f"At {company_name}" if company_name else "Connection"

    return min(score, 100), signals, label


# ---------------------------------------------------------------------------
# Warm-path reason generation
# ---------------------------------------------------------------------------


def _headline_summary(headline: str | None, signals: HeadlineSignals) -> str:
    """Build a short role description from headline for use in reason text."""
    if not headline:
        return ""
    # Use first segment of the headline (before | or •)
    first_seg = _SEGMENT_SPLIT.split(headline)[0].strip()
    # Remove "at Company" / "@ Company" suffix
    cleaned = _AT_COMPANY.sub("", first_seg).strip().rstrip(",;| ")
    return cleaned if len(cleaned) > 2 else ""


def generate_warm_path_reason(
    display_name: str,
    headline: str | None,
    signals: HeadlineSignals,
    company_name: str | None,
    job_context: JobContext | None,
    *,
    is_direct: bool,
) -> str:
    """Generate a context-aware warm-path explanation."""
    role_desc = _headline_summary(headline, signals)

    if is_direct:
        prefix = f"You know {display_name}"
        if not job_context:
            return f"You are already connected to {display_name} on LinkedIn."

        if signals.role_type == "recruiter":
            return f"{prefix}, a Recruiter who may hire for this area."
        if role_desc:
            dept_match = signals.department and job_context and signals.department == job_context.department
            team_overlap = bool(set(signals.team_keywords) & set(job_context.team_keywords))
            if team_overlap:
                return f"{prefix}, a {role_desc} on the same team."
            if dept_match:
                return f"{prefix}, a {role_desc} in the same department."
            return f"{prefix}, a {role_desc} at {company_name}."
        return f"You are already connected to {display_name} on LinkedIn."

    # Bridge path
    prefix = f"Your connection {display_name}"
    if not job_context:
        comp = f" at {company_name}" if company_name else ""
        return f"{prefix} works{comp}."

    if signals.role_type == "recruiter":
        comp = f" at {company_name}" if company_name else ""
        return f"{prefix} is a Recruiter{comp}."
    if role_desc:
        dept_match = signals.department and job_context and signals.department == job_context.department
        team_overlap = bool(set(signals.team_keywords) & set(job_context.team_keywords))
        if team_overlap:
            return f"{prefix} is a {role_desc} on the same team."
        if dept_match:
            return f"{prefix} is a {role_desc} in the same department."
        comp = f" at {company_name}" if company_name else ""
        return f"{prefix} is a {role_desc}{comp}."
    comp = f" at {company_name}" if company_name else ""
    return f"{prefix} works{comp}."
