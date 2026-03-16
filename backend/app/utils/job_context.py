"""Job context extraction — derives department, team, seniority, and targeted
search titles from a job posting's title and description.

Pure function, no external calls, no DB — fully unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Keyword → department mapping (covers ~15 departments)
# ---------------------------------------------------------------------------
DEPARTMENT_MAP: dict[str, str] = {
    # Data (must come before generic "engineer"/"developer" to match "ml engineer", etc.)
    "data scientist": "data_science",
    "data engineer": "data_science",
    "data analyst": "data_science",
    "machine learning": "data_science",
    "ml engineer": "data_science",
    "ml ": "data_science",
    "ai engineer": "data_science",
    "analytics": "data_science",
    # Product (must come before generic matches)
    "product manager": "product_management",
    "product owner": "product_management",
    # Engineering (generic — must come after more specific patterns above)
    "engineer": "engineering",
    "developer": "engineering",
    "swe": "engineering",
    "sde": "engineering",
    "devops": "engineering",
    "sre": "engineering",
    "platform": "engineering",
    "infrastructure": "engineering",
    "architect": "engineering",
    "firmware": "engineering",
    "embedded": "engineering",
    "full stack": "engineering",
    "fullstack": "engineering",
    "program manager": "product_management",
    "tpm": "product_management",
    # Design
    "designer": "design",
    "ux": "design",
    "ui": "design",
    "user experience": "design",
    "user interface": "design",
    "visual design": "design",
    # Marketing
    "marketing": "marketing",
    "growth": "marketing",
    "content": "marketing",
    "seo": "marketing",
    "brand": "marketing",
    # Sales
    "sales": "sales",
    "account executive": "sales",
    "business development": "sales",
    "bdr": "sales",
    "sdr": "sales",
    # Customer Success
    "customer success": "customer_success",
    "customer support": "customer_success",
    "support engineer": "customer_success",
    "solutions engineer": "customer_success",
    "solutions architect": "customer_success",
    # Finance
    "finance": "finance",
    "accounting": "finance",
    "controller": "finance",
    "financial analyst": "finance",
    # HR / People
    "recruiter": "human_resources",
    "talent acquisition": "human_resources",
    "people operations": "human_resources",
    "human resources": "human_resources",
    "hr ": "human_resources",
    # Legal
    "legal": "legal",
    "counsel": "legal",
    "compliance": "legal",
    # Operations
    "operations": "operations",
    "supply chain": "operations",
    "logistics": "operations",
    # Security
    "security engineer": "information_technology",
    "cybersecurity": "information_technology",
    "infosec": "information_technology",
    # IT
    "it ": "information_technology",
    "system admin": "information_technology",
    "network engineer": "information_technology",
    # QA
    "qa": "engineering",
    "quality assurance": "engineering",
    "test engineer": "engineering",
    "sdet": "engineering",
}

# Apollo-accepted department slugs
APOLLO_DEPARTMENT_SLUGS: dict[str, list[str]] = {
    "engineering": ["engineering_technical"],
    "data_science": ["engineering_technical", "data"],
    "product_management": ["product_management"],
    "design": ["design"],
    "marketing": ["marketing"],
    "sales": ["sales"],
    "customer_success": ["support"],
    "finance": ["finance"],
    "human_resources": ["human_resources"],
    "legal": ["legal"],
    "operations": ["operations"],
    "information_technology": ["information_technology"],
}

# ---------------------------------------------------------------------------
# Team keyword extraction patterns
# ---------------------------------------------------------------------------
TEAM_KEYWORDS_MAP: dict[str, list[str]] = {
    "backend": ["backend", "back-end", "server-side", "api"],
    "frontend": ["frontend", "front-end", "ui", "client-side", "react", "angular", "vue"],
    "fullstack": ["full stack", "fullstack", "full-stack"],
    "mobile": ["mobile", "ios", "android", "react native", "flutter"],
    "devops": ["devops", "dev ops", "site reliability", "sre", "infrastructure", "platform"],
    "ml": ["machine learning", "ml", "deep learning", "ai", "artificial intelligence", "nlp", "computer vision"],
    "data": ["data engineering", "data pipeline", "etl", "analytics", "data warehouse", "big data"],
    "security": ["security", "cybersecurity", "infosec", "appsec", "devsecops"],
    "cloud": ["cloud", "aws", "gcp", "azure", "kubernetes", "k8s"],
    "embedded": ["embedded", "firmware", "iot", "hardware"],
    "qa": ["qa", "quality assurance", "test", "testing", "sdet"],
    "payments": ["payments", "billing", "fintech", "financial"],
    "growth": ["growth", "experimentation", "a/b test"],
    "platform": ["platform", "internal tools", "developer experience", "developer tools"],
}

# ---------------------------------------------------------------------------
# Seniority detection
# ---------------------------------------------------------------------------
SENIORITY_PATTERNS: list[tuple[str, str]] = [
    (r"\bintern\b", "intern"),
    (r"\bjunior\b|\bjr\.?\b|\bentry[- ]level\b", "junior"),
    (r"\bmid[- ]?level\b|\bmid\b", "mid"),
    (r"\bsenior\b|\bsr\.?\b", "senior"),
    (r"\bstaff\b", "staff"),
    (r"\bprincipal\b", "principal"),
    (r"\blead\b|\btech lead\b|\bteam lead\b", "lead"),
    (r"\bmanager\b|\bengineering manager\b|\bem\b", "manager"),
    (r"\bdirector\b", "director"),
    (r"\bvp\b|\bvice president\b", "vp"),
    (r"\bc-level\b|\bcto\b|\bcio\b|\bciso\b", "executive"),
]

# HTML tag strip pattern
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class JobContext:
    """Extracted context from a job posting for targeted people search."""

    department: str
    team_keywords: list[str] = field(default_factory=list)
    seniority: str = "mid"
    manager_titles: list[str] = field(default_factory=list)
    peer_titles: list[str] = field(default_factory=list)
    recruiter_titles: list[str] = field(default_factory=list)
    apollo_departments: list[str] = field(default_factory=list)


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    return _HTML_TAG_RE.sub(" ", text)


def _detect_department(title_lower: str, desc_lower: str) -> str:
    """Detect department from title and description keywords."""
    # Check title first (higher signal)
    for keyword, dept in DEPARTMENT_MAP.items():
        if keyword in title_lower:
            return dept

    # Fallback to description
    for keyword, dept in DEPARTMENT_MAP.items():
        if keyword in desc_lower:
            return dept

    return "engineering"  # safe default for tech job seekers


def _detect_team_keywords(title_lower: str, desc_lower: str) -> list[str]:
    """Extract team/specialty keywords from title and description."""
    combined = f"{title_lower} {desc_lower}"
    found: list[str] = []

    for team, keywords in TEAM_KEYWORDS_MAP.items():
        for kw in keywords:
            if kw in combined:
                found.append(team)
                break

    return found


def _detect_seniority(title_lower: str) -> str:
    """Extract seniority from title using pattern matching."""
    for pattern, level in SENIORITY_PATTERNS:
        if re.search(pattern, title_lower):
            return level
    return "mid"


def _build_manager_titles(department: str, team_keywords: list[str], base_title: str) -> list[str]:
    """Generate manager/lead title variants for the same team."""
    titles: list[str] = []

    # Extract the core role area from the base title
    core = _extract_core_role(base_title)

    if core:
        titles.append(f"{core} Manager")
        titles.append(f"{core} Engineering Manager")
        titles.append(f"Head of {core}")

    # Department-level managers
    dept_label = department.replace("_", " ").title()
    titles.append(f"{dept_label} Manager")
    titles.append("Engineering Manager")
    titles.append("Hiring Manager")

    # Team-specific managers
    for team in team_keywords[:2]:
        team_label = team.replace("_", " ").title()
        titles.append(f"{team_label} Engineering Manager")
        titles.append(f"{team_label} Lead")

    return list(dict.fromkeys(titles))  # dedupe, preserve order


def _build_peer_titles(base_title: str, team_keywords: list[str], seniority: str) -> list[str]:
    """Generate peer title variants (similar role, same team)."""
    titles: list[str] = []

    core = _extract_core_role(base_title)

    # Add the original title (stripped of seniority prefix)
    if core:
        titles.append(core)
        # Add common synonyms
        if "engineer" in core.lower():
            titles.append(core.replace("Engineer", "Developer"))
        elif "developer" in core.lower():
            titles.append(core.replace("Developer", "Engineer"))

    # Team-specific titles
    for team in team_keywords[:2]:
        team_label = team.replace("_", " ").title()
        titles.append(f"{team_label} Engineer")
        titles.append(f"{team_label} Developer")

    # Add seniority-adjacent peers
    if seniority in ("senior", "staff", "lead"):
        titles.extend([f"Senior {t}" for t in titles[:2] if "Senior" not in t])

    return list(dict.fromkeys(titles))  # dedupe, preserve order


def _build_recruiter_titles(department: str, team_keywords: list[str]) -> list[str]:
    """Generate recruiter title variants relevant to the department."""
    titles: list[str] = ["Technical Recruiter", "Talent Acquisition"]

    if department == "engineering" or department == "data_science":
        titles.insert(0, "Engineering Recruiter")
    elif department == "design":
        titles.append("Design Recruiter")
    elif department == "product_management":
        titles.append("Product Recruiter")
    elif department in ("sales", "marketing"):
        titles.append(f"{department.title()} Recruiter")
    else:
        dept_label = department.replace("_", " ").title()
        titles.append(f"{dept_label} Recruiter")

    titles.append("Recruiter")
    return list(dict.fromkeys(titles))


def _extract_core_role(title: str) -> str:
    """Strip seniority prefixes from a title to get the core role.

    e.g. "Senior Backend Engineer" → "Backend Engineer"
         "Staff ML Engineer" → "ML Engineer"
    """
    title_clean = title.strip()
    # Remove common seniority prefixes
    prefixes = [
        r"(?:senior|sr\.?|junior|jr\.?|staff|principal|lead|entry[- ]level|mid[- ]?level)\s+",
    ]
    result = title_clean
    for prefix in prefixes:
        result = re.sub(prefix, "", result, count=1, flags=re.IGNORECASE)
    return result.strip()


def extract_job_context(title: str, description: str | None = None) -> JobContext:
    """Extract structured context from a job title and description.

    Args:
        title: Job title, e.g. "Senior Backend Engineer"
        description: Job description (may contain HTML).

    Returns:
        JobContext with department, team, seniority, and targeted search titles.
    """
    title_lower = title.lower().strip()
    desc_clean = _strip_html(description or "")
    desc_lower = desc_clean.lower()

    department = _detect_department(title_lower, desc_lower)
    team_keywords = _detect_team_keywords(title_lower, desc_lower)
    seniority = _detect_seniority(title_lower)
    apollo_departments = APOLLO_DEPARTMENT_SLUGS.get(department, ["engineering_technical"])

    manager_titles = _build_manager_titles(department, team_keywords, title)
    peer_titles = _build_peer_titles(title, team_keywords, seniority)
    recruiter_titles = _build_recruiter_titles(department, team_keywords)

    return JobContext(
        department=department,
        team_keywords=team_keywords,
        seniority=seniority,
        manager_titles=manager_titles,
        peer_titles=peer_titles,
        recruiter_titles=recruiter_titles,
        apollo_departments=apollo_departments,
    )
