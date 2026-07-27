

"""Country resolution for job locations (functionality audit 2026-07-26, #6).

A job with no country is invisible to the country filter in BOTH directions —
it can be neither shown nor hidden. That was 20% of a real feed, in a product
that targets the US and Canada.
"""

from app.utils.job_metadata import normalize_locations


def test_bare_country_names_resolve():
    """These are country names that simply weren't in the alias table."""
    for name, expected in (
        ("Luxembourg", "Luxembourg"),
        ("Uruguay", "Uruguay"),
        ("Philippines", "Philippines"),
    ):
        _, _, countries = normalize_locations(name)
        assert countries == [expected], name


def test_unambiguous_city_resolves_to_its_country():
    """41 of 116 country-less jobs in a real feed were 'Bengaluru'."""
    for city, expected in (
        ("Bengaluru", "India"),
        ("Bangalore", "India"),
        ("CDMX", "Mexico"),
        ("Stockholm", "Sweden"),
        ("Tel Aviv", "Israel"),
    ):
        _, _, countries = normalize_locations(city)
        assert countries == [expected], city


def test_well_known_cities_resolve_via_the_geocoder():
    """The geocoder already places these; the city map is only a fallback.

    Documented here because the parser's own comment says it avoids guessing a
    country from a bare city — that caution applies to the *text* rules, not to
    the geocode step, which has real coordinates behind it.
    """
    for city, expected in (
        ("London", "United Kingdom"),
        ("Dublin", "Ireland"),
        ("Toronto", "Canada"),
        ("Sydney", "Australia"),
    ):
        _, _, countries = normalize_locations(city)
        assert countries == [expected], city


def test_the_city_map_only_fires_when_nothing_else_resolved():
    """Bengaluru was country-less because the geocoder didn't place it."""
    _, _, countries = normalize_locations("Bengaluru")
    assert countries == ["India"]


def test_placeholder_locations_stay_country_less():
    for junk in ("N/A", "Remote", "Worldwide", "Anywhere", ""):
        _, _, countries = normalize_locations(junk)
        assert countries == [], junk


def test_explicit_country_still_wins_over_the_city_map():
    _, _, countries = normalize_locations("Bengaluru, India")
    assert countries == ["India"]
