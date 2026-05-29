"""Normalize job metadata before persistence and scoring.

This module centralizes the lossy source-specific fields that arrive from job
boards into a stable internal shape. The original fields remain available for
backwards compatibility; normalized fields carry confidence and provenance so
the product can distinguish strong source data from heuristics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.utils.experience_level import classify_experience_level_metadata


SOURCE_QUALITY_MATRIX: dict[str, dict[str, str]] = {
    "newgrad_jobs": {
        "location": "detail_page",
        "salary": "detail_page",
        "level": "source_label",
        "description": "detail_page",
    },
    "yc_jobs": {
        "location": "structured",
        "salary": "structured",
        "level": "min_experience",
        "description": "structured_summary",
    },
    "jsearch": {
        "location": "provider_structured_partial",
        "salary": "provider_structured",
        "level": "heuristic",
        "description": "provider_description",
    },
    "adzuna": {
        "location": "provider_structured",
        "salary": "provider_structured",
        "level": "heuristic",
        "description": "provider_description",
    },
    "greenhouse": {
        "location": "ats_structured",
        "salary": "description_or_json_ld",
        "level": "heuristic",
        "description": "ats_content",
    },
    "lever": {
        "location": "ats_structured",
        "salary": "description_or_json_ld",
        "level": "heuristic",
        "description": "variable",
    },
    "ashby": {
        "location": "ats_structured",
        "salary": "description_or_json_ld",
        "level": "heuristic",
        "description": "ats_content",
    },
    "workday": {
        "location": "ats_structured_when_exact",
        "salary": "json_ld_or_description",
        "level": "heuristic",
        "description": "exact_job_only",
    },
    "workable": {
        "location": "ats_structured",
        "salary": "description",
        "level": "heuristic",
        "description": "ats_content",
    },
    "apple_jobs": {
        "location": "structured",
        "salary": "description_or_json_ld",
        "level": "heuristic",
        "description": "exact_job_only",
    },
    "google_careers": {
        "location": "structured",
        "salary": "description",
        "level": "heuristic",
        "description": "careers_feed",
    },
    "microsoft": {
        "location": "structured",
        "salary": "description",
        "level": "heuristic",
        "description": "careers_api",
    },
    "amazon": {
        "location": "structured",
        "salary": "description",
        "level": "heuristic",
        "description": "careers_api",
    },
    "meta": {
        "location": "structured",
        "salary": "description",
        "level": "heuristic",
        "description": "careers_api",
    },
    "tesla": {
        "location": "structured",
        "salary": "description",
        "level": "heuristic",
        "description": "careers_api",
    },
    "remotive": {
        "location": "remote_region_text",
        "salary": "raw_text",
        "level": "heuristic",
        "description": "provider_description",
    },
    "jobicy": {
        "location": "remote_region_text",
        "salary": "provider_structured",
        "level": "heuristic",
        "description": "provider_description",
    },
    "dice": {
        "location": "provider_structured",
        "salary": "raw_text",
        "level": "heuristic",
        "description": "summary",
    },
}


@dataclass(frozen=True)
class LocationGeocode:
    latitude: float
    longitude: float
    label: str
    radius_km: float
    country_code: str | None = None
    country: str | None = None
    source: str = "gazetteer"
    confidence: float = 0.85


REGION_LABELS = {
    "apac",
    "asia",
    "emea",
    "europe",
    "global",
    "latin america",
    "middle east",
    "north america",
    "remote",
    "south america",
    "worldwide",
}

LOCATION_GAZETTEER: dict[str, LocationGeocode] = {
    # Canadian metros and common job-market aliases.
    "toronto": LocationGeocode(43.6532, -79.3832, "Toronto, ON, Canada", 25, "CA", "Canada", confidence=0.95),
    "toronto on": LocationGeocode(43.6532, -79.3832, "Toronto, ON, Canada", 25, "CA", "Canada", confidence=0.95),
    "toronto ontario": LocationGeocode(43.6532, -79.3832, "Toronto, ON, Canada", 25, "CA", "Canada", confidence=0.95),
    "gta": LocationGeocode(43.6532, -79.3832, "Greater Toronto Area, ON, Canada", 60, "CA", "Canada", confidence=0.9),
    "greater toronto area": LocationGeocode(43.6532, -79.3832, "Greater Toronto Area, ON, Canada", 60, "CA", "Canada", confidence=0.9),
    "mississauga": LocationGeocode(43.5890, -79.6441, "Mississauga, ON, Canada", 20, "CA", "Canada"),
    "brampton": LocationGeocode(43.7315, -79.7624, "Brampton, ON, Canada", 20, "CA", "Canada"),
    "markham": LocationGeocode(43.8561, -79.3370, "Markham, ON, Canada", 20, "CA", "Canada"),
    "vaughan": LocationGeocode(43.8372, -79.5083, "Vaughan, ON, Canada", 20, "CA", "Canada"),
    "oakville": LocationGeocode(43.4675, -79.6877, "Oakville, ON, Canada", 20, "CA", "Canada"),
    "waterloo": LocationGeocode(43.4643, -80.5204, "Waterloo, ON, Canada", 20, "CA", "Canada"),
    "kitchener": LocationGeocode(43.4516, -80.4925, "Kitchener, ON, Canada", 20, "CA", "Canada"),
    "ottawa": LocationGeocode(45.4215, -75.6972, "Ottawa, ON, Canada", 25, "CA", "Canada"),
    "montreal": LocationGeocode(45.5019, -73.5674, "Montreal, QC, Canada", 25, "CA", "Canada"),
    "vancouver": LocationGeocode(49.2827, -123.1207, "Vancouver, BC, Canada", 25, "CA", "Canada"),
    "calgary": LocationGeocode(51.0447, -114.0719, "Calgary, AB, Canada", 25, "CA", "Canada"),
    # Major US markets and tech hubs.
    "new york": LocationGeocode(40.7128, -74.0060, "New York, NY, United States", 25, "US", "United States"),
    "nyc": LocationGeocode(40.7128, -74.0060, "New York, NY, United States", 25, "US", "United States"),
    "san francisco": LocationGeocode(37.7749, -122.4194, "San Francisco, CA, United States", 25, "US", "United States"),
    "sf bay area": LocationGeocode(37.7749, -122.4194, "San Francisco Bay Area, CA, United States", 70, "US", "United States"),
    "bay area": LocationGeocode(37.7749, -122.4194, "San Francisco Bay Area, CA, United States", 70, "US", "United States"),
    "palo alto": LocationGeocode(37.4419, -122.1430, "Palo Alto, CA, United States", 15, "US", "United States"),
    "mountain view": LocationGeocode(37.3861, -122.0839, "Mountain View, CA, United States", 15, "US", "United States"),
    "menlo park": LocationGeocode(37.4530, -122.1817, "Menlo Park, CA, United States", 15, "US", "United States"),
    "seattle": LocationGeocode(47.6062, -122.3321, "Seattle, WA, United States", 25, "US", "United States"),
    "bellevue": LocationGeocode(47.6101, -122.2015, "Bellevue, WA, United States", 15, "US", "United States"),
    "austin": LocationGeocode(30.2672, -97.7431, "Austin, TX, United States", 25, "US", "United States"),
    "boston": LocationGeocode(42.3601, -71.0589, "Boston, MA, United States", 25, "US", "United States"),
    "chicago": LocationGeocode(41.8781, -87.6298, "Chicago, IL, United States", 25, "US", "United States"),
    "los angeles": LocationGeocode(34.0522, -118.2437, "Los Angeles, CA, United States", 35, "US", "United States"),
    "washington dc": LocationGeocode(38.9072, -77.0369, "Washington, DC, United States", 25, "US", "United States"),
    "atlanta": LocationGeocode(33.7490, -84.3880, "Atlanta, GA, United States", 25, "US", "United States"),
    "miami": LocationGeocode(25.7617, -80.1918, "Miami, FL, United States", 25, "US", "United States"),
    # International hubs common in exact-job feeds.
    "london": LocationGeocode(51.5072, -0.1276, "London, United Kingdom", 25, "GB", "United Kingdom"),
    "dublin": LocationGeocode(53.3498, -6.2603, "Dublin, Ireland", 25, "IE", "Ireland"),
    "berlin": LocationGeocode(52.5200, 13.4050, "Berlin, Germany", 25, "DE", "Germany"),
    "amsterdam": LocationGeocode(52.3676, 4.9041, "Amsterdam, Netherlands", 25, "NL", "Netherlands"),
    "paris": LocationGeocode(48.8566, 2.3522, "Paris, France", 25, "FR", "France"),
    "singapore": LocationGeocode(1.3521, 103.8198, "Singapore", 25, "SG", "Singapore"),
    "tokyo": LocationGeocode(35.6764, 139.6500, "Tokyo, Japan", 30, "JP", "Japan"),
    "sydney": LocationGeocode(-33.8688, 151.2093, "Sydney, Australia", 30, "AU", "Australia"),
}

COUNTRY_ALIASES: dict[str, tuple[str, str]] = {
    "australia": ("AU", "Australia"),
    "austria": ("AT", "Austria"),
    "belgium": ("BE", "Belgium"),
    "brazil": ("BR", "Brazil"),
    "can": ("CA", "Canada"),
    "canada": ("CA", "Canada"),
    "chile": ("CL", "Chile"),
    "china": ("CN", "China"),
    "colombia": ("CO", "Colombia"),
    "czech republic": ("CZ", "Czech Republic"),
    "denmark": ("DK", "Denmark"),
    "england": ("GB", "United Kingdom"),
    "finland": ("FI", "Finland"),
    "france": ("FR", "France"),
    "germany": ("DE", "Germany"),
    "great britain": ("GB", "United Kingdom"),
    "greece": ("GR", "Greece"),
    "hong kong": ("HK", "Hong Kong"),
    "hungary": ("HU", "Hungary"),
    "india": ("IN", "India"),
    "ireland": ("IE", "Ireland"),
    "israel": ("IL", "Israel"),
    "italy": ("IT", "Italy"),
    "japan": ("JP", "Japan"),
    "kenya": ("KE", "Kenya"),
    "mexico": ("MX", "Mexico"),
    "netherlands": ("NL", "Netherlands"),
    "new zealand": ("NZ", "New Zealand"),
    "nigeria": ("NG", "Nigeria"),
    "northern ireland": ("GB", "United Kingdom"),
    "norway": ("NO", "Norway"),
    "poland": ("PL", "Poland"),
    "portugal": ("PT", "Portugal"),
    "romania": ("RO", "Romania"),
    "saudi arabia": ("SA", "Saudi Arabia"),
    "scotland": ("GB", "United Kingdom"),
    "singapore": ("SG", "Singapore"),
    "south africa": ("ZA", "South Africa"),
    "south korea": ("KR", "South Korea"),
    "spain": ("ES", "Spain"),
    "sweden": ("SE", "Sweden"),
    "switzerland": ("CH", "Switzerland"),
    "taiwan": ("TW", "Taiwan"),
    "turkey": ("TR", "Turkey"),
    "uae": ("AE", "United Arab Emirates"),
    "united arab emirates": ("AE", "United Arab Emirates"),
    "uk": ("GB", "United Kingdom"),
    "u.k.": ("GB", "United Kingdom"),
    "united kingdom": ("GB", "United Kingdom"),
    "gb": ("GB", "United Kingdom"),
    "united states": ("US", "United States"),
    "united states of america": ("US", "United States"),
    "us": ("US", "United States"),
    "u.s.": ("US", "United States"),
    "usa": ("US", "United States"),
    "wales": ("GB", "United Kingdom"),
}

COUNTRY_CODES_BY_NAME = {name.lower(): code for code, name in COUNTRY_ALIASES.values()}

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}
US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "district of columbia", "florida", "georgia",
    "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska",
    "nevada", "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming",
}
CANADIAN_PROVINCE_CODES = {
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
}
CANADIAN_PROVINCE_NAMES = {
    "alberta", "british columbia", "manitoba", "new brunswick",
    "newfoundland and labrador", "northwest territories", "nova scotia",
    "nunavut", "ontario", "prince edward island", "quebec", "saskatchewan",
    "yukon",
}

EMPLOYMENT_TYPE_MAP = {
    "full time": "full-time",
    "full-time": "full-time",
    "full_time": "full-time",
    "fulltime": "full-time",
    "part time": "part-time",
    "part-time": "part-time",
    "part_time": "part-time",
    "contract": "contract",
    "contractor": "contract",
    "temporary": "temporary",
    "temp": "temporary",
    "intern": "internship",
    "internship": "internship",
}

CURRENCY_SYMBOLS = {
    "$": "USD",
    "£": "GBP",
    "€": "EUR",
}
CURRENCY_CODES = {"USD", "CAD", "GBP", "EUR", "AUD", "NZD", "SGD"}

COMPENSATION_LINE_RE = re.compile(
    r".{0,80}(?:salary|compensation|pay range|base pay|base salary|annual).{0,180}",
    re.IGNORECASE,
)
AMOUNT_RE = re.compile(r"\b\d{2,3}(?:,\d{3})*(?:\.\d+)?\s*[kK]?\b|\b\d+(?:\.\d+)?\s*[kK]\b")


@dataclass(frozen=True)
class SalaryExtraction:
    minimum: float | None
    maximum: float | None
    currency: str | None
    period: str | None
    source: str
    confidence: float


def _normalize_token(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def _title_case_country(value: str) -> str:
    return " ".join(part.capitalize() for part in value.lower().split())


def _place_key(value: str | None) -> str:
    text = _normalize_token(value)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _location_keys_from_parts(
    *,
    city: str | None,
    region: str | None,
    country: str | None,
    raw: str,
) -> list[str]:
    values = [
        raw,
        city,
        f"{city} {region}" if city and region else None,
        f"{city} {country}" if city and country else None,
        f"{city} {region} {country}" if city and region and country else None,
    ]
    return list(dict.fromkeys(_place_key(value) for value in values if value))


def geocode_location_query(value: str | None) -> LocationGeocode | None:
    """Resolve a user/job location string to coordinates when known locally."""
    if not value:
        return None

    cleaned = re.sub(r"\([^)]*\)", " ", value)
    parts = [part.strip() for part in re.split(r"[,;/|]", cleaned) if part.strip()]
    candidates = [value, cleaned, *parts]
    if len(parts) >= 2:
        candidates.append(f"{parts[0]} {parts[1]}")
    if len(parts) >= 3:
        candidates.append(f"{parts[0]} {parts[1]} {parts[2]}")

    for candidate in candidates:
        geocode = LOCATION_GAZETTEER.get(_place_key(candidate))
        if geocode:
            return geocode
    return None


def _geocode_parsed_location(
    *,
    city: str | None,
    region: str | None,
    country: str | None,
    raw: str,
) -> LocationGeocode | None:
    for key in _location_keys_from_parts(city=city, region=region, country=country, raw=raw):
        geocode = LOCATION_GAZETTEER.get(key)
        if geocode:
            return geocode
    return None


def country_code_for_name(country: str | None) -> str | None:
    if not country:
        return None
    normalized = _normalize_token(country)
    alias = COUNTRY_ALIASES.get(normalized)
    if alias:
        return alias[0]
    return COUNTRY_CODES_BY_NAME.get(normalized)


def _country_alias_in_text(text: str) -> tuple[str, str] | None:
    normalized = _normalize_token(text)
    for alias, country in COUNTRY_ALIASES.items():
        pattern = rf"(^|[^a-z]){re.escape(alias)}([^a-z]|$)"
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return country
    return None


def _split_locations(raw_location: object) -> list[str]:
    if not raw_location:
        return []
    if isinstance(raw_location, list):
        raw_location = " | ".join(str(item) for item in raw_location if item)
    raw_location = str(raw_location)
    parts = [
        re.sub(r"\s+", " ", part.strip(" ,"))
        for part in re.split(r"\s*(?:;|\|)\s*", raw_location)
    ]
    return [part for part in dict.fromkeys(parts) if part]


def _parse_location_piece(raw_piece: str) -> dict[str, Any]:
    clean = re.sub(r"\s+", " ", raw_piece.strip(" ,"))
    if not clean:
        return {}

    country_code: str | None = None
    country: str | None = None
    city: str | None = None
    region: str | None = None
    confidence = 0.55

    paren_match = re.search(r"\(([^)]+)\)", clean)
    parenthetical = paren_match.group(1).strip() if paren_match else ""
    country_candidate = _country_alias_in_text(parenthetical) if parenthetical else None
    if not country_candidate:
        country_candidate = _country_alias_in_text(clean)
    if country_candidate:
        country_code, country = country_candidate
        confidence = 0.85

    parts = [part.strip() for part in clean.replace("(", ", ").replace(")", "").split(",") if part.strip()]
    last = parts[-1] if parts else clean
    second_last = parts[-2] if len(parts) >= 2 else ""
    last_norm = _normalize_token(last)
    second_last_norm = _normalize_token(second_last)
    last_upper = last.upper().strip(".")
    second_last_upper = second_last.upper().strip(".")

    if (
        last_upper in CANADIAN_PROVINCE_CODES
        or last_norm in CANADIAN_PROVINCE_NAMES
        or (
            last_upper == "CA"
            and (
                second_last_upper in CANADIAN_PROVINCE_CODES
                or second_last_norm in CANADIAN_PROVINCE_NAMES
            )
        )
    ):
        country_code, country = "CA", "Canada"
        region = second_last if last_upper == "CA" and second_last else last
        confidence = max(confidence, 0.9)
    elif last_upper in US_STATE_CODES or last_norm in US_STATE_NAMES:
        country_code, country = "US", "United States"
        region = last
        confidence = max(confidence, 0.9)

    if not country and last_norm in COUNTRY_ALIASES:
        country_code, country = COUNTRY_ALIASES[last_norm]
        confidence = max(confidence, 0.95)
    elif not country and last_norm not in REGION_LABELS and re.fullmatch(r"[A-Za-z .'-]{3,}", last):
        # Avoid inventing countries for city-only strings like "Toronto".
        if len(parts) >= 2:
            country = _title_case_country(last)
            country_code = country_code_for_name(country)
            confidence = max(confidence, 0.7 if country_code else 0.45)

    if parts:
        first = parts[0]
        if _normalize_token(first) not in REGION_LABELS and not first.lower().startswith("remote"):
            city = first
        if len(parts) >= 2 and not region and second_last_norm not in COUNTRY_ALIASES:
            region = second_last

    geocode = _geocode_parsed_location(city=city, region=region, country=country, raw=clean)
    if geocode:
        country_code = country_code or geocode.country_code
        country = country or geocode.country
        confidence = max(confidence, geocode.confidence)

    parsed = {
        "raw": clean,
        "city": city,
        "region": region,
        "country": country,
        "country_code": country_code,
        "source": "location_text",
        "confidence": round(confidence, 2),
    }
    if geocode:
        parsed.update({
            "latitude": geocode.latitude,
            "longitude": geocode.longitude,
            "geocoded_label": geocode.label,
            "geocode_source": geocode.source,
            "radius_km": geocode.radius_km,
        })
    return parsed


def normalize_locations(raw_location: object) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    pieces = _split_locations(raw_location)
    locations = [_parse_location_piece(piece) for piece in pieces]
    locations = [location for location in locations if location]
    country_codes = [
        str(location["country_code"])
        for location in locations
        if location.get("country_code")
    ]
    countries = [
        str(location["country"])
        for location in locations
        if location.get("country")
    ]
    return (
        locations,
        list(dict.fromkeys(country_codes)),
        list(dict.fromkeys(countries)),
    )


def normalize_employment_type(raw_value: object, *, experience_level: str | None = None) -> str | None:
    if isinstance(raw_value, list):
        raw_value = " ".join(str(item) for item in raw_value if item)
    normalized = _normalize_token(str(raw_value or "").replace("_", " ").replace("-", " "))
    if not normalized and experience_level == "intern":
        return "internship"
    if not normalized:
        return None
    mapped = EMPLOYMENT_TYPE_MAP.get(normalized)
    if mapped:
        return mapped
    if "intern" in normalized:
        return "internship"
    if "full" in normalized and "time" in normalized:
        return "full-time"
    if "part" in normalized and "time" in normalized:
        return "part-time"
    if "contract" in normalized:
        return "contract"
    return normalized.replace(" ", "-")


def normalize_work_mode(job_data: dict[str, Any]) -> tuple[str | None, bool, dict[str, Any]]:
    explicit = _normalize_token(str(job_data.get("work_mode") or job_data.get("workplace") or ""))
    text = " ".join(
        str(value or "")
        for value in (
            job_data.get("title"),
            job_data.get("location"),
            job_data.get("description"),
        )
    ).lower()
    remote_input = bool(job_data.get("remote"))

    source = "heuristic"
    confidence = 0.55
    work_mode: str | None = None
    if explicit:
        source = "source"
        confidence = 0.9
        if "hybrid" in explicit:
            work_mode = "hybrid"
        elif "remote" in explicit or "telecommute" in explicit:
            work_mode = "remote"
        elif "onsite" in explicit or "on site" in explicit or "on-site" in explicit:
            work_mode = "onsite"

    if not work_mode:
        if re.search(r"\bhybrid\b", text):
            work_mode = "hybrid"
            confidence = 0.75
        elif remote_input or re.search(r"\b(remote|telecommute|work from home|wfh)\b", text):
            work_mode = "remote"
            confidence = 0.75 if remote_input else 0.65
        elif re.search(r"\b(on[- ]?site|in office)\b", text):
            work_mode = "onsite"
            confidence = 0.65

    remote = work_mode == "remote" or (remote_input and work_mode != "hybrid")
    return work_mode, remote, {
        "source": source,
        "confidence": confidence,
        "input_remote": remote_input,
    }


def _salary_period_from_text(text: str | None) -> str | None:
    lowered = (text or "").lower()
    if any(token in lowered for token in ("/hr", "/hour", "per hour", "hourly")):
        return "hour"
    if any(token in lowered for token in ("/mo", "per month", "monthly")):
        return "month"
    if any(token in lowered for token in ("/yr", "/year", "per year", "annually", "annual")):
        return "year"
    return "year" if "$" in lowered or any(code.lower() in lowered for code in CURRENCY_CODES) else None


def _currency_from_text(text: str | None, fallback: str | None = None) -> str | None:
    raw = text or ""
    for code in CURRENCY_CODES:
        if re.search(rf"\b{code}\b", raw, flags=re.IGNORECASE):
            return code
    if re.search(r"\b(CA\$|C\$)\b", raw, flags=re.IGNORECASE):
        return "CAD"
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in raw:
            return code
    return fallback


def _amount_to_float(raw_amount: str) -> float | None:
    text = raw_amount.strip()
    if not text:
        return None
    multiplier = 1000.0 if text.lower().endswith("k") else 1.0
    cleaned = text.rstrip("kK").replace(",", "").strip()
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def parse_salary_from_text(
    text: str | None,
    *,
    source: str = "text",
    fallback_currency: str | None = None,
) -> SalaryExtraction | None:
    raw = text or ""
    if not raw:
        return None
    currency = _currency_from_text(raw, fallback=fallback_currency)
    if not currency:
        return None

    candidates = COMPENSATION_LINE_RE.findall(raw)
    search_text = "\n".join(candidates) if candidates else raw[:1500]
    values = [
        value
        for value in (_amount_to_float(match.group(0)) for match in AMOUNT_RE.finditer(search_text))
        if value is not None and value > 0
    ]
    if not values:
        return None

    minimum = values[0]
    maximum = values[1] if len(values) >= 2 else None
    if maximum is not None and maximum < minimum:
        minimum, maximum = maximum, minimum

    return SalaryExtraction(
        minimum=minimum,
        maximum=maximum,
        currency=currency,
        period=_salary_period_from_text(search_text),
        source=source,
        confidence=0.75 if candidates else 0.55,
    )


def _coerce_salary_value(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_json_ld_base_salary(base_salary: object) -> SalaryExtraction | None:
    if isinstance(base_salary, list):
        for item in base_salary:
            parsed = parse_json_ld_base_salary(item)
            if parsed:
                return parsed
        return None
    if not isinstance(base_salary, dict):
        return None

    currency = str(base_salary.get("currency") or "").upper() or None
    value = base_salary.get("value")
    period: str | None = None
    minimum: float | None = None
    maximum: float | None = None

    if isinstance(value, dict):
        currency = str(value.get("currency") or currency or "").upper() or None
        unit = str(value.get("unitText") or base_salary.get("unitText") or "").lower()
        if "hour" in unit:
            period = "hour"
        elif "month" in unit:
            period = "month"
        elif "year" in unit or "annual" in unit:
            period = "year"
        minimum = _coerce_salary_value(value.get("minValue") or value.get("value"))
        maximum = _coerce_salary_value(value.get("maxValue"))
    else:
        minimum = _coerce_salary_value(value)

    if not currency:
        currency = _currency_from_text(str(base_salary))
    if minimum is None and maximum is None:
        return None

    return SalaryExtraction(
        minimum=minimum,
        maximum=maximum,
        currency=currency,
        period=period or "year",
        source="json_ld_base_salary",
        confidence=0.95,
    )


def _salary_from_job_data(job_data: dict[str, Any]) -> SalaryExtraction | None:
    minimum = _coerce_salary_value(job_data.get("salary_min"))
    maximum = _coerce_salary_value(job_data.get("salary_max"))
    currency = str(job_data.get("salary_currency") or "").upper() or None
    period = job_data.get("salary_period")

    if minimum is not None or maximum is not None:
        return SalaryExtraction(
            minimum=minimum,
            maximum=maximum,
            currency=currency or _currency_from_text(str(job_data.get("salary") or "")),
            period=str(period) if period else "year",
            source="source_structured",
            confidence=0.9,
        )

    raw_salary = job_data.get("salary") or job_data.get("salary_range")
    parsed = parse_salary_from_text(
        str(raw_salary or ""),
        source="source_text",
        fallback_currency=currency,
    )
    if parsed:
        return parsed

    return parse_salary_from_text(
        str(job_data.get("description") or ""),
        source="description",
        fallback_currency=currency,
    )


def normalize_job_metadata(job_data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *job_data* with normalized metadata fields attached."""
    normalized = dict(job_data)
    provenance: dict[str, Any] = dict(normalized.get("metadata_provenance") or {})

    locations, country_codes, countries = normalize_locations(normalized.get("location"))
    primary_geocoded_location = next(
        (
            location
            for location in locations
            if location.get("latitude") is not None and location.get("longitude") is not None
        ),
        None,
    )
    normalized["locations"] = locations or None
    normalized["country_codes"] = country_codes or None
    normalized["countries"] = countries or None
    normalized["location_lat"] = (
        float(primary_geocoded_location["latitude"]) if primary_geocoded_location else None
    )
    normalized["location_lng"] = (
        float(primary_geocoded_location["longitude"]) if primary_geocoded_location else None
    )
    normalized["location_radius_km"] = (
        float(primary_geocoded_location.get("radius_km") or 0) if primary_geocoded_location else None
    )
    normalized["location_geocode_label"] = (
        str(primary_geocoded_location.get("geocoded_label")) if primary_geocoded_location else None
    )
    provenance["location"] = {
        "source": "location_text" if locations else "missing",
        "confidence": max((loc.get("confidence", 0) for loc in locations), default=0),
        "geocode_source": primary_geocoded_location.get("geocode_source") if primary_geocoded_location else None,
    }

    work_mode, remote, work_provenance = normalize_work_mode(normalized)
    normalized["work_mode"] = work_mode
    normalized["remote"] = remote
    provenance["work_mode"] = work_provenance

    level_result = classify_experience_level_metadata(
        title=str(normalized.get("title") or ""),
        description=str(normalized.get("description") or ""),
        source=normalized.get("source"),
        level_label=normalized.get("level_label"),
        employment_type=normalized.get("employment_type"),
        min_experience=normalized.get("min_experience") or normalized.get("minExperience"),
    )
    normalized["experience_level"] = level_result.level
    normalized["experience_level_confidence"] = level_result.confidence
    provenance["experience_level"] = {
        "source": level_result.source,
        "confidence": level_result.confidence,
        "reasons": level_result.reasons,
    }

    normalized["employment_type"] = normalize_employment_type(
        normalized.get("employment_type"),
        experience_level=level_result.level,
    )

    salary = _salary_from_job_data(normalized)
    if salary:
        normalized["salary_min"] = salary.minimum
        normalized["salary_max"] = salary.maximum
        normalized["salary_currency"] = salary.currency
        normalized["salary_period"] = salary.period
        provenance["salary"] = {
            "source": salary.source,
            "confidence": salary.confidence,
        }
    else:
        normalized["salary_min"] = None
        normalized["salary_max"] = None
        normalized["salary_period"] = normalized.get("salary_period")
        provenance["salary"] = {"source": "missing", "confidence": 0}

    source = str(normalized.get("source") or normalized.get("ats") or "unknown")
    provenance["source_quality"] = SOURCE_QUALITY_MATRIX.get(source, {})
    normalized["metadata_provenance"] = provenance
    return normalized
