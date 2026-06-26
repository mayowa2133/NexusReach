"""Tests for the auto-discovered ATS board pipeline (script + loader)."""

import importlib.util
from pathlib import Path

from app.services.jobs import constants, discovered_boards

# Load the discovery script as a module (it's a CLI script, not a package).
_spec = importlib.util.spec_from_file_location(
    "discover_ats_boards",
    Path(__file__).resolve().parents[1] / "scripts" / "discover_ats_boards.py",
)
discover = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(discover)  # type: ignore[union-attr]


# --- slug heuristics ---------------------------------------------------------


def test_slug_candidates_covers_common_forms():
    cands = discover._slug_candidates("Clover Health")
    assert "cloverhealth" in cands
    assert "clover-health" in cands
    assert "clover" in cands


def test_slug_candidates_drops_suffix_words_for_core():
    cands = discover._slug_candidates("Acme Technologies Inc")
    # "technologies"/"inc" are suffix words → core collapses to "acme"
    assert "acme" in cands


# --- name-match guard (prevents slug-collision false positives) --------------


def test_name_matches_accepts_real_company():
    assert discover._name_matches("Form Energy", "Form Energy", "formenergy")
    # token overlap on the first significant word
    assert discover._name_matches("Clover Health", "Clover", "clover")


def test_name_matches_rejects_collision():
    # A slug that resolves to an unrelated company must be rejected.
    assert not discover._name_matches("Acme Bank", "Zebra Robotics", "acmebank")


def test_name_matches_lever_requires_exact_slug():
    # Lever returns no org name → only an exact slug==normalized-name is trusted.
    assert discover._name_matches("Included Health", None, "includedhealth")
    assert not discover._name_matches("Included Health", None, "included")


# --- loader ------------------------------------------------------------------


def test_loader_structure_dedup_and_no_curated_overlap():
    discovered_boards.load_discovered_boards.cache_clear()
    boards = discovered_boards.load_discovered_boards()
    assert isinstance(boards, tuple) and len(boards) > 0

    for b in boards:
        assert set(b) == {"slug", "ats", "company"}
        assert b["ats"] in {"greenhouse", "lever", "ashby"}
        assert b["slug"] and b["company"]

    # never re-list a hand-curated board
    curated = {(x["ats"], x["slug"]) for x in constants.ATS_DISCOVER_BOARDS}
    curated |= {("lever", s) for s in constants.LEVER_DISCOVER_SLUGS}
    assert not [b for b in boards if (b["ats"], b["slug"]) in curated]

    # no internal duplicates
    keys = [(b["ats"], b["slug"]) for b in boards]
    assert len(keys) == len(set(keys))
    discovered_boards.load_discovered_boards.cache_clear()


def test_loader_fails_soft_on_missing_file(monkeypatch, tmp_path):
    discovered_boards.load_discovered_boards.cache_clear()
    monkeypatch.setattr(discovered_boards, "_DATA_PATH", tmp_path / "nope.json")
    assert discovered_boards.load_discovered_boards() == ()
    discovered_boards.load_discovered_boards.cache_clear()
