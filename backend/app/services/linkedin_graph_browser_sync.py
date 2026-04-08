"""Helpers for scraping LinkedIn connection cards in the local browser sync."""

from __future__ import annotations

import re
from typing import Any

from app.utils.linkedin import normalize_linkedin_url

LINKEDIN_CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
READY_SELECTOR = "li.mn-connection-card, .mn-connection-card"

SCRAPE_CONNECTION_CARDS_SCRIPT = r"""
() => {
  const normalizeText = (value) => (value || "").replace(/\s+/g, " ").trim();
  const pickText = (root, selectors) => {
    for (const selector of selectors) {
      const text = normalizeText(root.querySelector(selector)?.textContent || "");
      if (text) {
        return text;
      }
    }
    return "";
  };

  const cards = Array.from(document.querySelectorAll("li.mn-connection-card, .mn-connection-card"));
  return cards
    .map((card) => {
      const anchor = Array.from(card.querySelectorAll('a[href*="/in/"]')).find((link) => {
        const href = link?.href || "";
        return href.includes("/in/");
      });
      const fullName = pickText(card, [
        ".mn-connection-card__name",
        ".mn-person-info__name",
        ".artdeco-entity-lockup__title",
        ".artdeco-entity-lockup__title span[aria-hidden='true']",
      ]);
      const headline = pickText(card, [
        ".mn-connection-card__occupation",
        ".mn-person-info__occupation",
        ".artdeco-entity-lockup__subtitle",
        ".artdeco-entity-lockup__caption",
      ]);

      if (!fullName || !anchor?.href) {
        return null;
      }

      return {
        full_name: fullName,
        linkedin_url: anchor.href,
        headline,
      };
    })
    .filter(Boolean);
}
"""

SCROLL_CONNECTIONS_SCRIPT = r"""
() => {
  const selectors = [
    ".scaffold-finite-scroll__content",
    ".mn-connections",
    "main",
  ];
  const count = document.querySelectorAll("li.mn-connection-card, .mn-connection-card").length;
  const container = selectors
    .map((selector) => document.querySelector(selector))
    .find((element) => element && element.scrollHeight > element.clientHeight)
    || document.scrollingElement
    || document.documentElement;

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
    re.compile(r"\bat\s+([^|,•()\[\]]+)", re.IGNORECASE),
    re.compile(r"@\s*([^|,•()\[\]]+)", re.IGNORECASE),
)


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
        if company:
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
