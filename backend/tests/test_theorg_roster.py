"""Tests for The Org HTML roster + reporting-line extraction.

These parse synthetic HTML in the same shape as live TheOrg pages
(JSON-LD Organization.employee[] + inline LightPosition objects), so they
lock the parser without a network call.
"""

from __future__ import annotations

from app.clients import theorg_client

# Minimal HTML mimicking a TheOrg org page: an employee[] JSON-LD roster and
# a few inline LightPosition objects (one role + its parent manager).
_HTML = (
    '<html><head>'
    '<script type="application/ld+json">{"@type":"Organization","name":"Acme",'
    '"employee":['
    '{"@context":"https://schema.org","@type":"Person","name":"Rhea Vega","jobTitle":"Chief Revenue Officer",'
    '"sameAs":["https://theorg.com/org/acme/org-chart/rhea-vega"]},'
    '{"@context":"https://schema.org","@type":"Person","name":"Tom Webb","jobTitle":"Chief Technology Officer",'
    '"sameAs":["https://theorg.com/org/acme/org-chart/tom-webb"]}'
    ']}</script></head><body>'
    # positions graph
    '{"__typename":"LightPosition","id":100,"slug":"dana-fox","fullName":"Dana Fox",'
    '"profileImage":{"uri":"x"},"role":"Commercial Sales Manager","parentPositionId":50,"isAdviser":false}'
    ',{"__typename":"LightPosition","id":50,"slug":"rhea-vega","fullName":"Rhea Vega",'
    '"profileImage":{"uri":"y"},"role":"Chief Revenue Officer","parentPositionId":null,"isAdviser":false}'
    ',{"__typename":"LightPosition","id":200,"slug":"sam-ae","fullName":"Sam Close",'
    '"profileImage":{"uri":"z"},"role":"Strategic Account Executive","parentPositionId":100,"isAdviser":false}'
    '</body></html>'
)


def test_extract_org_roster():
    roster = theorg_client.extract_org_roster(_HTML)
    by_name = {p["fullName"]: p for p in roster}
    assert "Rhea Vega" in by_name
    assert by_name["Rhea Vega"]["role"] == "Chief Revenue Officer"
    assert by_name["Rhea Vega"]["slug"] == "rhea-vega"
    assert len(roster) == 2


def test_extract_positions():
    positions = theorg_client.extract_positions(_HTML)
    assert len(positions) == 3
    ae = next(p for p in positions.values() if p["role"] == "Strategic Account Executive")
    assert ae["fullName"] == "Sam Close"
    assert ae["parent"] == 100  # reports to the Commercial Sales Manager


def test_resolve_reporting_managers_parent_first():
    mgrs = theorg_client.resolve_reporting_managers(
        _HTML, "Strategic Account Executive",
        company_name="Acme", org_slug="acme", origin_url="https://theorg.com/org/acme",
    )
    names = [m["full_name"] for m in mgrs]
    # Dana Fox is the literal parent of the AE position -> reporting-line manager
    assert "Dana Fox" in names
    dana = next(m for m in mgrs if m["full_name"] == "Dana Fox")
    assert dana["_theorg_reporting_manager"] is True
    assert dana["title"] == "Commercial Sales Manager"


def test_parse_org_page_html_fallback():
    page = {"url": "https://theorg.com/org/acme", "next_data": {}, "html": _HTML}
    parsed = theorg_client.parse_org_page(page)
    assert parsed is not None
    leader_names = {p["full_name"] for p in parsed["leaders"]}
    # roster recovered from HTML even though next_data is empty
    assert "Rhea Vega" in leader_names
    assert parsed["org_slug"] == "acme"
