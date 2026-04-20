"""Resume parsing service.

Extracts structured data (skills, experience, education, projects) from
PDF and DOCX files using text extraction plus resume-specific heuristics.
"""

import io
import re


MONTH_PATTERN = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t)?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{MONTH_PATTERN}\s+\d{{4}}|\d{{4}})\s*[–—-]\s*"
    rf"(?P<end>{MONTH_PATTERN}\s+\d{{4}}|\d{{4}}|Present|Current)",
    re.IGNORECASE,
)
BULLET_PREFIX_RE = re.compile(r"^[•·▪►\-]\s*")
LOCATION_SUFFIX_RE = re.compile(
    r"(?P<prefix>.+?)\s+(?P<location>[A-Za-z .&'/()-]+,\s*(?:[A-Z]{2}|[A-Za-z][A-Za-z .'-]+))$"
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[\s\-.(]*)?\d{3}[\s\-.)]*\d{3}[\s\-]*\d{4}")
URL_RE = re.compile(r"https?://\S+")
LOCATION_BOUNDARY_STOPWORDS = {
    "engineer", "developer", "manager", "scientist", "analyst", "designer", "intern",
    "application/software", "software", "cloud", "honours", "computer", "science",
    "b.s.", "m.s.", "bachelor", "master", "ph.d.", "associate",
}


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF file using PyPDF2."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from a DOCX file using python-docx."""
    import docx

    doc = docx.Document(io.BytesIO(file_bytes))
    return "\n".join(paragraph.text for paragraph in doc.paragraphs)


def extract_text(file_bytes: bytes, content_type: str) -> str:
    """Extract text from a resume file based on content type."""
    if content_type == "application/pdf":
        return extract_text_from_pdf(file_bytes)
    elif content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return extract_text_from_docx(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: {content_type}")


# Common section headers for resume parsing
SECTION_PATTERNS = {
    "experience": re.compile(
        r"(?i)^(?:work\s+)?experience|employment|professional\s+experience|work\s+history",
        re.MULTILINE,
    ),
    "education": re.compile(
        r"(?i)^education|academic|qualifications|degrees",
        re.MULTILINE,
    ),
    "skills": re.compile(
        r"(?i)^(?:technical\s+)?skills|technologies|competencies|proficiencies|tools",
        re.MULTILINE,
    ),
    "projects": re.compile(
        r"(?i)^projects|personal\s+projects|portfolio|side\s+projects",
        re.MULTILINE,
    ),
    "certificates": re.compile(
        r"(?i)^certificates?|certifications?|licenses",
        re.MULTILINE,
    ),
}


def _normalize_resume_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_sections(text: str) -> dict[str, str]:
    """Split resume text into sections based on common headers."""
    text = _normalize_resume_text(text)
    # Find all section positions
    positions: list[tuple[int, str]] = []
    for section_name, pattern in SECTION_PATTERNS.items():
        match = pattern.search(text)
        if match:
            positions.append((match.start(), section_name))

    positions.sort(key=lambda x: x[0])

    sections: dict[str, str] = {}
    for i, (pos, name) in enumerate(positions):
        # Find the end of the header line
        header_end = text.find("\n", pos)
        if header_end == -1:
            header_end = pos

        # Section content extends to the next section or end of text
        if i + 1 < len(positions):
            end = positions[i + 1][0]
        else:
            end = len(text)

        sections[name] = text[header_end:end].strip()

    return sections


def _extract_header_text(text: str) -> str:
    text = _normalize_resume_text(text)
    positions: list[int] = []
    for pattern in SECTION_PATTERNS.values():
        match = pattern.search(text)
        if match:
            positions.append(match.start())
    if not positions:
        return text
    return text[: min(positions)].strip()


def _parse_contact_header(text: str) -> dict:
    header = _extract_header_text(text)
    if not header:
        return {}

    lines = [line.strip() for line in header.split("\n") if line.strip()]
    if not lines:
        return {}

    name = lines[0]
    details_text = " | ".join(lines[1:])
    parts = [part.strip() for part in details_text.split("|") if part.strip()]

    phone = None
    email = None
    urls: list[str] = []
    address_parts: list[str] = []

    for part in parts:
        email_match = EMAIL_RE.search(part)
        url_match = URL_RE.search(part)
        phone_match = PHONE_RE.search(part)
        if email_match and not email:
            email = email_match.group(0)
            continue
        if phone_match and not phone:
            phone = phone_match.group(0)
            continue
        if url_match:
            urls.append(url_match.group(0))
            continue
        address_parts.append(part)

    return {
        "name": name,
        "address": " | ".join(address_parts) if address_parts else None,
        "phone": phone,
        "email": email,
        "urls": urls,
    }


_KNOWN_SKILL_CATEGORIES = [
    "Programming Languages",
    "Languages",
    "Technologies",
    "Frameworks",
    "Frontend",
    "Backend",
    "Databases",
    "Libraries",
    "Methodologies",
    "Tools",
    "Platforms",
    "Cloud",
    "DevOps",
    "Concepts",
    "Skills",
    "Other",
]

_SKILL_CATEGORY_SPLIT_RE = re.compile(
    r"(?<!\n)\s+(?=(?:" + "|".join(re.escape(c) for c in _KNOWN_SKILL_CATEGORIES) + r")\s*:)"
)


def _normalize_skills_text(text: str) -> str:
    """Repair PDF-flattened skills lines.

    PDF extraction often joins multiple `Category: values` blocks onto one
    line and inserts space before colons. Collapse `word : value` to
    `word: value`, then break the line whenever a known category label
    appears mid-stream so each category lives on its own line.
    """
    if not text:
        return text
    text = re.sub(r"[ \t]+:", ":", text)
    text = _SKILL_CATEGORY_SPLIT_RE.sub("\n", text)
    return text


def scrub_skill_value(skill: str | None) -> str | None:
    """Sanitize one previously-parsed skill string.

    Strips bullet/colon noise and drops embedded category-label leaks like
    ``"Languages : C"``. Returns None if nothing usable remains.
    """
    if not skill:
        return None
    cleaned = skill.strip().strip("-•·▪►:").strip()
    if ":" in cleaned:
        cleaned = cleaned.rsplit(":", 1)[-1].strip()
    if not cleaned:
        return None
    if not (1 < len(cleaned) < 50 or cleaned.lower() in {"c", "r"}):
        return None
    return cleaned


def scrub_skill_list(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        cleaned = scrub_skill_value(v)
        if cleaned:
            out.append(cleaned)
    return out


def _split_skill_values(text: str) -> list[str]:
    values: list[str] = []
    for part in re.split(r"[,|;/]", text):
        skill = part.strip().strip("-•·▪►:").strip()
        if not skill:
            continue
        # Defense in depth: if a stray category label snuck through ("Foo: bar"),
        # keep only the value side.
        if ":" in skill:
            skill = skill.rsplit(":", 1)[-1].strip()
        if skill and (1 < len(skill) < 50 or skill.lower() in {"c", "r"}):
            values.append(skill)
    return values


def _parse_skills(text: str) -> list[str]:
    """Extract skills from skills section text."""
    skills: list[str] = []
    seen: set[str] = set()
    for line in _normalize_skills_text(text).split("\n"):
        line = line.strip().strip("-•·▪►")
        if not line:
            continue
        if ":" in line:
            _, line = line.split(":", 1)
        for skill in _split_skill_values(line):
            normalized = skill.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            skills.append(skill)
    return skills


def _parse_skill_categories(text: str) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {}
    for line in _normalize_skills_text(text).split("\n"):
        clean_line = line.strip().strip("-•·▪►")
        if not clean_line or ":" not in clean_line:
            continue
        label, values = clean_line.split(":", 1)
        items = _split_skill_values(values)
        if items:
            categories[label.strip()] = items
    return categories


def _parse_title_location(line: str) -> tuple[str, str | None]:
    clean_line = " ".join(line.split()).strip()
    if "," not in clean_line:
        return clean_line, None

    before_comma, after_comma = clean_line.rsplit(",", 1)
    region = after_comma.strip()
    tokens = before_comma.split()
    if not tokens or not region:
        return clean_line, None

    city_tokens = [tokens[-1]]
    idx = len(tokens) - 2
    while idx >= 0 and len(city_tokens) < 3:
        token = tokens[idx].strip()
        normalized = token.lower().strip(".")
        if "/" in token or normalized in LOCATION_BOUNDARY_STOPWORDS:
            break
        if not token[:1].isupper():
            break
        city_tokens.insert(0, token)
        idx -= 1

    title = " ".join(tokens[: len(tokens) - len(city_tokens)]).strip()
    if not title:
        return clean_line, None
    return title, f"{' '.join(city_tokens)}, {region}"


def _parse_experience(text: str) -> list[dict]:
    """Extract experience entries from experience section text."""
    entries: list[dict] = []
    lines = [line.strip() for line in _normalize_resume_text(text).split("\n") if line.strip()]

    current: dict | None = None
    for line in lines:
        date_match = DATE_RANGE_RE.search(line)
        if date_match:
            if current:
                current["description"] = "\n".join(current["bullets"]).strip()
                entries.append(current)
            company = line[: date_match.start()].strip().rstrip("|-–—").strip()
            current = {
                "company": company,
                "title": "",
                "location": "",
                "start_date": date_match.group("start").strip(),
                "end_date": date_match.group("end").strip(),
                "description": "",
                "bullets": [],
            }
            if current["end_date"].lower() in {"present", "current"}:
                current["end_date"] = None
            continue

        if not current:
            continue

        if BULLET_PREFIX_RE.match(line):
            bullet = BULLET_PREFIX_RE.sub("", line).strip()
            if bullet:
                current["bullets"].append(bullet)
            continue

        if not current["title"]:
            title, location = _parse_title_location(line)
            current["title"] = title
            current["location"] = location or ""
            continue

        if current["bullets"]:
            current["bullets"][-1] = f"{current['bullets'][-1]} {line}".strip()
        else:
            current["title"] = f"{current['title']} {line}".strip()

    if current:
        current["description"] = "\n".join(current["bullets"]).strip()
        entries.append(current)

    return entries


def _looks_like_education_header(line: str) -> bool:
    lowered = line.lower()
    return any(token in lowered for token in ("university", "college", "institute", "school"))


def _looks_like_degree_line(line: str) -> bool:
    return bool(re.search(
        r"(?i)\b(bachelor|master|b\.?s\.?|m\.?s\.?|b\.?a\.?|m\.?a\.?|ph\.?d|diploma|certificate|associate)\b",
        line,
    ))


def _parse_education(text: str) -> list[dict]:
    """Extract education entries from education section text."""
    lines = [line.strip() for line in _normalize_resume_text(text).split("\n") if line.strip()]
    if not lines:
        return []

    entries: list[dict] = []
    i = 0
    while i < len(lines):
        first_line = lines[i]
        degree_first = _looks_like_degree_line(first_line)
        if degree_first:
            degree_line = first_line
            institution = lines[i + 1] if i + 1 < len(lines) else ""
            i += 2
        else:
            institution = first_line
            degree_line = lines[i + 1] if i + 1 < len(lines) else ""
            i += 2

        degree, location = _parse_title_location(degree_line)
        entry = {
            "institution": institution,
            "degree": degree,
            "field": degree,
            "graduation_date": "",
            "location": location or "",
            "details": [],
        }
        year_match = re.search(r"\b(20\d{2}|19\d{2})\b", degree_line)
        if year_match:
            entry["graduation_date"] = year_match.group(1)

        while i < len(lines) and not _looks_like_education_header(lines[i]) and not _looks_like_degree_line(lines[i]):
            entry["details"].append(lines[i])
            year_match = re.search(r"\b(20\d{2}|19\d{2})\b", lines[i])
            if year_match and not entry["graduation_date"]:
                entry["graduation_date"] = year_match.group(1)
            i += 1

        entries.append(entry)

    return entries


def _start_new_project(line: str) -> bool:
    if BULLET_PREFIX_RE.match(line):
        return False
    if len(line) > 130:
        return False
    normalized = line.strip()
    if "GitHub:" in normalized or URL_RE.search(normalized):
        return True
    if normalized.endswith((".", "!", "?")):
        return False
    if normalized[:1].islower():
        return False
    return len(normalized.split()) <= 10


def _parse_project_header(line: str) -> tuple[str, str | None, str | None]:
    clean_line = " ".join(line.split()).strip()
    url_match = URL_RE.search(clean_line)
    url = url_match.group(0) if url_match else None
    header_without_url = clean_line.replace(url, "").strip() if url else clean_line
    link_label = None
    label_match = re.search(r"\(([^()]*GitHub[^()]*)\)", header_without_url, flags=re.IGNORECASE)
    if label_match:
        link_label = label_match.group(1).strip()
        header_without_url = re.sub(r"\([^()]*GitHub[^()]*\)", "", header_without_url).strip()
    return header_without_url, url, link_label


def _parse_projects(text: str) -> list[dict]:
    """Extract project entries from projects section text."""
    entries: list[dict] = []
    lines = [line.strip() for line in _normalize_resume_text(text).split("\n") if line.strip()]

    current: dict | None = None
    for line in lines:
        if _start_new_project(line):
            if current:
                current["description"] = "\n".join(current["bullets"]).strip()
                entries.append(current)
            name, url, link_label = _parse_project_header(line)
            current = {
                "name": name,
                "description": "",
                "bullets": [],
                "technologies": [],
                "url": url,
                "link_label": link_label,
            }
            continue

        if not current:
            continue

        if BULLET_PREFIX_RE.match(line):
            bullet = BULLET_PREFIX_RE.sub("", line).strip()
            if bullet:
                current["bullets"].append(bullet)
            tech_match = re.search(r"(?i)(?:technologies|tech stack|built with|using)\s*:\s*(.*)", bullet)
            if tech_match:
                current["technologies"] = _split_skill_values(tech_match.group(1))
            else:
                for token in re.findall(r"\b(?:[A-Z][A-Za-z0-9.+#/-]*|[A-Za-z]+\.js)\b", bullet):
                    if token.lower() in {"built", "designed", "engineered", "developed"}:
                        continue
                    if token not in current["technologies"] and len(token) > 1:
                        current["technologies"].append(token)
            continue

        if current["bullets"]:
            current["bullets"][-1] = f"{current['bullets'][-1]} {line}".strip()
        else:
            current["description"] = f"{current['description']}\n{line}".strip()

    if current:
        current["description"] = "\n".join(current["bullets"]).strip() or current["description"]
        entries.append(current)

    return entries


def _parse_certificates(text: str) -> list[str]:
    certificates: list[str] = []
    for line in _normalize_resume_text(text).split("\n"):
        clean_line = BULLET_PREFIX_RE.sub("", line.strip())
        if clean_line and not re.fullmatch(r"\d+", clean_line):
            certificates.append(clean_line)
    return certificates


def parse_resume_text(text: str) -> dict:
    """Parse structured resume content from extracted plain text."""
    normalized_text = _normalize_resume_text(text)
    sections = _split_sections(normalized_text)
    skill_categories = _parse_skill_categories(sections.get("skills", ""))

    return {
        "contact": _parse_contact_header(normalized_text),
        "skills": _parse_skills(sections.get("skills", "")),
        "skills_by_category": skill_categories,
        "experience": _parse_experience(sections.get("experience", "")),
        "education": _parse_education(sections.get("education", "")),
        "projects": _parse_projects(sections.get("projects", "")),
        "certificates": _parse_certificates(sections.get("certificates", "")),
    }


def parse_resume(file_bytes: bytes, content_type: str) -> dict:
    """Parse a resume file and return structured data."""
    text = extract_text(file_bytes, content_type)
    return parse_resume_text(text)
