"""Resume parsing service.

Extracts structured data (skills, experience, education, projects) from
PDF and DOCX files. Uses basic text extraction with heuristic section
detection. Can be upgraded to use an external parsing API (Affinda, etc.)
or Claude for better accuracy later.
"""

import io
import re


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
}


def _split_sections(text: str) -> dict[str, str]:
    """Split resume text into sections based on common headers."""
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


def _parse_skills(text: str) -> list[str]:
    """Extract skills from skills section text."""
    # Split by common delimiters
    skills: list[str] = []
    for line in text.split("\n"):
        line = line.strip().strip("-•·▪►")
        if not line:
            continue
        # Split by commas, pipes, semicolons
        parts = re.split(r"[,|;/]", line)
        for part in parts:
            skill = part.strip().strip("-•·▪►:").strip()
            if skill and len(skill) < 50 and len(skill) > 1:
                skills.append(skill)
    return skills


def _parse_experience(text: str) -> list[dict]:
    """Extract experience entries from experience section text."""
    entries: list[dict] = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    current: dict | None = None
    for line in lines:
        # Heuristic: lines with dates are likely job headers
        date_match = re.search(
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|June|July|August|September|October|November|December)\s*\d{0,4})"
            r"|(\d{4}\s*[-–—]\s*(?:\d{4}|[Pp]resent|[Cc]urrent))"
            r"|(\d{1,2}/\d{4})",
            line,
        )
        if date_match:
            if current:
                entries.append(current)
            current = {
                "company": "",
                "title": line,
                "start_date": "",
                "end_date": None,
                "description": "",
            }
            # Try to extract dates
            full_date = re.search(
                r"(\w+\s*\d{4})\s*[-–—]\s*(\w+\s*\d{4}|[Pp]resent|[Cc]urrent)", line
            )
            if full_date:
                current["start_date"] = full_date.group(1).strip()
                end = full_date.group(2).strip()
                current["end_date"] = None if end.lower() in ("present", "current") else end
                # Remove dates from title
                current["title"] = line[: full_date.start()].strip().rstrip("-–—|").strip()
        elif current:
            if not current["company"] and not current["description"]:
                current["company"] = line
            else:
                desc = current["description"]
                current["description"] = f"{desc}\n{line}".strip() if desc else line

    if current:
        entries.append(current)

    return entries


def _parse_education(text: str) -> list[dict]:
    """Extract education entries from education section text."""
    entries: list[dict] = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    current: dict | None = None
    for line in lines:
        # Heuristic: lines mentioning degree keywords start new entries
        degree_match = re.search(
            r"(?i)(bachelor|master|b\.?s\.?|m\.?s\.?|b\.?a\.?|m\.?a\.?|ph\.?d|diploma|certificate|associate)",
            line,
        )
        if degree_match or (not current and line):
            if current:
                entries.append(current)
            current = {
                "institution": "",
                "degree": line,
                "field": "",
                "graduation_date": "",
            }
            # Try to extract year
            year = re.search(r"(\d{4})", line)
            if year:
                current["graduation_date"] = year.group(1)
        elif current:
            if not current["institution"]:
                current["institution"] = line
            elif not current["field"]:
                current["field"] = line

    if current:
        entries.append(current)

    return entries


def _parse_projects(text: str) -> list[dict]:
    """Extract project entries from projects section text."""
    entries: list[dict] = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    current: dict | None = None
    for line in lines:
        # Heuristic: short lines without common description words are likely project names
        is_name = len(line) < 80 and not line.startswith(("-", "•", "·", "▪"))
        if is_name and (not current or (current and current.get("description"))):
            if current:
                entries.append(current)
            current = {
                "name": line,
                "description": "",
                "technologies": [],
                "url": None,
            }
            # Check for URL
            url_match = re.search(r"(https?://\S+)", line)
            if url_match:
                current["url"] = url_match.group(1)
                current["name"] = line[: url_match.start()].strip().rstrip("-–—|:").strip()
        elif current:
            # Check for tech stack line
            tech_keywords = re.search(r"(?i)(?:tech|stack|built with|using|technologies):\s*(.*)", line)
            if tech_keywords:
                techs = re.split(r"[,|;]", tech_keywords.group(1))
                current["technologies"] = [t.strip() for t in techs if t.strip()]
            else:
                desc = current["description"]
                current["description"] = f"{desc}\n{line}".strip() if desc else line.lstrip("-•·▪ ")

    if current:
        entries.append(current)

    return entries


def parse_resume(file_bytes: bytes, content_type: str) -> dict:
    """Parse a resume file and return structured data.

    Returns:
        {
            "skills": [...],
            "experience": [...],
            "education": [...],
            "projects": [...]
        }
    """
    text = extract_text(file_bytes, content_type)
    sections = _split_sections(text)

    return {
        "skills": _parse_skills(sections.get("skills", "")),
        "experience": _parse_experience(sections.get("experience", "")),
        "education": _parse_education(sections.get("education", "")),
        "projects": _parse_projects(sections.get("projects", "")),
    }
