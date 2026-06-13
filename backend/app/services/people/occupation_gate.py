"""Occupation gate: reject off-function candidates from hiring-manager / peer buckets.

Public-web x-ray for a low-web-footprint function (sales, finance, ...) tends to
return the company's most-indexed profiles - usually engineers - regardless of
the title searched. Without a gate the pipeline will confidently surface an
"Engineering Manager" as the hiring manager for a sales req. This module maps a
title to a coarse function group and rejects a candidate only when its group is
known and clearly different from the job's group, so the result becomes an
honest empty rather than a wrong answer. The grouping is deliberately coarse:
adjacent functions (engineering / data / security / product) share a group so a
security req can still surface an engineering manager.
"""

from __future__ import annotations

import re

# Coarse function groups. Order matters: the first group with a keyword hit in
# the title wins, so more specific phrases are listed before generic ones.
_GROUP_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("gtm", (
        "account executive", "account manager", "sales", "business development",
        "sales development", "sdr", "bdr", "go-to-market", "go to market",
        "revenue", "quota", "strategic account", "customer success",
        "marketing", "brand", "growth marketer", "demand gen", "demand generation",
        "seo", "content marketer", "partnerships",
    )),
    ("technical", (
        "software engineer", "engineer", "engineering", "developer", "swe",
        "sre", "devops", "devsecops", "programmer", "site reliability",
        "platform engineer", "backend", "frontend", "full stack", "fullstack",
        "data engineer", "data scientist", "data analyst", "machine learning",
        "ml engineer", "infrastructure", "security engineer", "architect",
        "product manager", "product owner", "technical program",
    )),
    ("creative", (
        "designer", "ux ", "ui ", "user experience", "creative director",
        "illustrator", "graphic", "art director", "motion design",
    )),
    ("corporate", (
        "finance", "accounting", "accountant", "controller", "fp&a", "treasury",
        "legal", "counsel", "paralegal", "compliance",
        "human resources", "people operations", "people ops",
        "supply chain", "procurement", "logistics",
        "program manager", "project manager", "consultant",
    )),
    ("domain", (
        "nurse", "clinical", "physician", "medical", "rn ",
        "teacher", "professor", "instructor", "educator",
    )),
]

# Occupation department_bucket -> function group. Buckets not listed (or those
# spanning groups) yield no gate, on the safe side.
_BUCKET_TO_GROUP: dict[str, str] = {
    "engineering": "technical",
    "data": "technical",
    "ml_ai": "technical",
    "security": "technical",
    "hardware_engineering": "technical",
    "product": "technical",
    "information_technology": "technical",
    "sales": "gtm",
    "marketing": "gtm",
    "customer_success": "gtm",
    "design": "creative",
    "arts": "creative",
    "finance": "corporate",
    "business": "corporate",
    "consulting": "corporate",
    "legal": "corporate",
    "people": "corporate",
    "supply_chain": "corporate",
    "program_management": "corporate",
    "healthcare": "domain",
    "education": "domain",
}


def title_function_group(title: str | None) -> str | None:
    """Coarse function group of a person's title, or None if unrecognized.

    Recruiting/talent titles intentionally return None: a recruiter is
    cross-functional and is handled in its own (ungated) bucket.
    """
    if not title:
        return None
    text = f" {title.lower()} "
    if any(kw in text for kw in ("recruit", "talent acquisition", "sourcer")):
        return None
    for group, keywords in _GROUP_KEYWORDS:
        for kw in keywords:
            # word-ish containment; keep simple but avoid matching inside words
            if kw in text:
                return group
    return None


def job_function_group(occupation_keys: list[str] | None, department: str | None) -> str | None:
    """Coarse function group the job belongs to, or None when ambiguous."""
    from app.services.occupation_taxonomy import occupation_by_key

    groups = set()
    for key in occupation_keys or []:
        occ = occupation_by_key(key)
        if occ:
            grp = _BUCKET_TO_GROUP.get(occ.department_bucket)
            if grp:
                groups.add(grp)
    if len(groups) == 1:
        return next(iter(groups))
    if groups:
        return None  # multi-group job: do not gate
    # fall back to the raw department label if it maps cleanly
    if department:
        dept = re.sub(r"[^a-z]", "_", department.lower())
        return _BUCKET_TO_GROUP.get(dept)
    return None


def occupation_conflict(
    occupation_keys: list[str] | None,
    department: str | None,
    candidate_title: str | None,
) -> bool:
    """True when the candidate's function clearly differs from the job's.

    Conservative: returns False unless BOTH the job group and the candidate
    group are confidently known and different. Ambiguous titles (generic
    "Manager", recruiters) never conflict.
    """
    job_group = job_function_group(occupation_keys, department)
    if job_group is None:
        return False
    cand_group = title_function_group(candidate_title)
    if cand_group is None:
        return False
    return cand_group != job_group
