"""Helpers for scraping LinkedIn connection cards in the local browser sync."""

from __future__ import annotations

import re
from typing import Any

from app.utils.linkedin import normalize_linkedin_url

LINKEDIN_CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
READY_SELECTOR = 'a[href*="/in/"]'

SCRAPE_CONNECTION_CARDS_SCRIPT = r"""
() => {
  const normalizeText = (value) => (value || "").replace(/\s+/g, " ").trim();

  // LinkedIn uses hashed class names that rotate frequently. We use multiple
  // strategies to extract name and headline from connection cards.

  const profileLinks = Array.from(document.querySelectorAll('a[href*="/in/"]'));
  const seen = new Set();

  return profileLinks
    .map((anchor) => {
      const href = anchor.href || "";
      if (!href.includes("/in/")) return null;

      // Skip avatar-only links (no visible text, just SVG/img)
      const linkText = normalizeText(anchor.textContent);
      if (!linkText) return null;

      // Dedupe by href within this scrape pass
      const canonical = href.split("?")[0].replace(/\/+$/, "").toLowerCase();
      if (seen.has(canonical)) return null;
      seen.add(canonical);

      let fullName = "";
      let headline = "";

      // Strategy 1: <p> tags inside the link (most common variant).
      const paragraphs = anchor.querySelectorAll("p");
      if (paragraphs.length > 0) {
        fullName = normalizeText(paragraphs[0].textContent);
        headline = paragraphs.length > 1 ? normalizeText(paragraphs[1].textContent) : "";
      }

      // Strategy 2: <span> tags (LinkedIn sometimes uses spans instead of p)
      if (!fullName) {
        const spans = anchor.querySelectorAll("span");
        for (const span of spans) {
          const text = normalizeText(span.textContent);
          if (!text) continue;
          // Skip spans that are only whitespace, icons, or single chars
          if (text.length < 2) continue;
          if (!fullName) {
            fullName = text;
          } else if (!headline) {
            headline = text;
            break;
          }
        }
      }

      // Strategy 3: aria-label on the link itself (fallback)
      if (!fullName) {
        const ariaLabel = anchor.getAttribute("aria-label") || "";
        if (ariaLabel) {
          fullName = normalizeText(ariaLabel);
        }
      }

      // Strategy 4: Look in a parent card container for name/headline
      if (!fullName) {
        const card = anchor.closest("[data-view-name], .mn-connection-card, li");
        if (card) {
          const nameEl = card.querySelector("[data-view-name] p, .mn-connection-card__name, [aria-label]");
          if (nameEl) fullName = normalizeText(nameEl.textContent);
          const headlineEl = card.querySelector(".mn-connection-card__occupation, [data-view-name] p:nth-child(2)");
          if (headlineEl) headline = normalizeText(headlineEl.textContent);
        }
      }

      if (!fullName) return null;

      return {
        full_name: fullName,
        linkedin_url: href,
        headline,
      };
    })
    .filter(Boolean);
}
"""

SCROLL_CONNECTIONS_SCRIPT = r"""
() => {
  const count = document.querySelectorAll('a[href*="/in/"]').length;

  // Try multiple scrollable container candidates.
  // LinkedIn's layout varies: sometimes <main> is the scroll target,
  // sometimes a nested div, sometimes the window itself.
  const candidates = [
    document.querySelector("main"),
    document.querySelector('[role="main"]'),
    document.querySelector(".scaffold-layout__main"),
  ].filter(Boolean);

  let container = null;
  for (const c of candidates) {
    if (c && c.scrollHeight > c.clientHeight + 10) {
      container = c;
      break;
    }
  }

  if (!container) {
    container = document.scrollingElement || document.documentElement;
  }

  if (container === document.body || container === document.documentElement || container === document.scrollingElement) {
    window.scrollTo(0, document.body.scrollHeight);
  } else {
    container.scrollTop = container.scrollHeight;
  }

  return {
    count,
    scrollHeight: container?.scrollHeight || 0,
  };
}
"""

CLICK_SHOW_MORE_SCRIPT = r"""
() => {
  const button = Array.from(document.querySelectorAll("button")).find((candidate) => {
    const text = (candidate?.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
    return text.startsWith("show more");
  });
  if (!button) {
    return false;
  }
  button.click();
  return true;
}
"""

_COMPANY_PATTERNS = (
    # "Software Engineer at Google"
    re.compile(r"\bat\s+([^|,•()\[\]]+)", re.IGNORECASE),
    # "SWE @Google"
    re.compile(r"@\s*([^|,•()\[\]]+)", re.IGNORECASE),
    # "Google | Software Engineer" — company first then pipe
    re.compile(r"^([^|•,]+?)\s*[|•]", re.IGNORECASE),
    # "Software Engineer - Google" — dash separator (less precise, only if short)
    re.compile(r"\s[-–—]\s+([^|,•()\[\]]{2,40})$", re.IGNORECASE),
)

# Words that should NOT be extracted as a company name
_COMPANY_STOPWORDS = frozenset({
    "seeking", "looking", "open", "available", "hiring",
    "student", "graduate", "freelance", "retired", "self-employed",
    "actively", "currently", "formerly",
})


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def infer_company_name_from_headline(headline: str | None) -> str | None:
    clean = _clean_text(headline)
    if not clean:
        return None

    for pattern in _COMPANY_PATTERNS:
        match = pattern.search(clean)
        if match is None:
            continue
        company = re.sub(r"\s+", " ", match.group(1)).strip(" -:|,.;")
        if not company:
            continue
        # Reject stopwords that are clearly not company names
        first_word = company.split()[0].lower() if company else ""
        if first_word in _COMPANY_STOPWORDS:
            continue
        # Reject very short results that are likely noise
        if len(company) < 2:
            continue
        return company
    return None


def normalize_scraped_connection(row: dict[str, Any]) -> dict[str, str | None] | None:
    full_name = _clean_text(row.get("full_name") or row.get("display_name"))
    linkedin_url = normalize_linkedin_url(row.get("linkedin_url") or row.get("url"))
    if not full_name or not linkedin_url:
        return None

    headline = _clean_text(row.get("headline") or row.get("position")) or None
    current_company_name = (
        _clean_text(row.get("current_company_name") or row.get("company")) or None
    )
    if current_company_name is None:
        current_company_name = infer_company_name_from_headline(headline)

    company_linkedin_url = _clean_text(
        row.get("company_linkedin_url") or row.get("company_url")
    ) or None

    return {
        "full_name": full_name,
        "linkedin_url": linkedin_url,
        "headline": headline,
        "current_company_name": current_company_name,
        "company_linkedin_url": company_linkedin_url,
    }


def dedupe_scraped_connections(rows: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    deduped: list[dict[str, str | None]] = []
    by_url: dict[str, dict[str, str | None]] = {}
    by_name_company: dict[tuple[str, str], dict[str, str | None]] = {}

    for row in rows:
        normalized = normalize_scraped_connection(row)
        if normalized is None:
            continue

        url_key = normalized["linkedin_url"]
        company_key = (normalized.get("current_company_name") or "").strip().lower()
        name_key = normalized["full_name"].strip().lower()
        compound_key = (name_key, company_key)

        target = by_url.get(url_key) if url_key else None
        if target is None and company_key:
            target = by_name_company.get(compound_key)

        if target is None:
            deduped.append(normalized)
            if url_key:
                by_url[url_key] = normalized
            if company_key:
                by_name_company[compound_key] = normalized
            continue

        for key, value in normalized.items():
            if value and not target.get(key):
                target[key] = value

    return deduped
