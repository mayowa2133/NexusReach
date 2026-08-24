"""Every raw job is prepared the same way, whichever door it came in through.

There are three ways a job enters this database and they had grown three
different ideas of what "prepare a raw job" means:

    path                    decode description   startup tags   occupation tags
    _store_raw_jobs (crawl)        yes               yes              yes
    search_jobs                    no                yes              yes
    search_ats_jobs                no                no               no

The last row is the one that showed. One `figma` career-page search stored 162
rows with `tags = NULL` -- including "Data Engineer" and "Manager, Software
Engineering" -- so not one of them answered an occupation chip, which is the main
control on the Jobs page. A job the user asked for by name was the one kind of
job the product could not find again. The same 162 also kept Greenhouse's
HTML-escaped description, because that fix had been applied to the crawl alone.
"""

import inspect
from pathlib import Path

from app.services.jobs import search, storage

ESCAPED = "&lt;p&gt;Build distributed systems in Python.&lt;/p&gt;"


def _raw(**over):
    data = {
        "title": "Senior Software Engineer",
        "company_name": "Figma",
        "location": "San Francisco, CA",
        "description": ESCAPED,
    }
    data.update(over)
    return data


def test_preparation_decodes_the_description():
    out = storage.prepare_raw_job(_raw(), known_startup_companies=set())
    assert out["description"] == "<p>Build distributed systems in Python.</p>"


def test_preparation_stamps_an_occupation_tag():
    """The defect in one line: this is what the ATS search path never did."""
    out = storage.prepare_raw_job(_raw(), known_startup_companies=set())
    assert "occupation:software_engineering" in (out.get("tags") or [])


def test_preparation_keeps_extra_tags_from_the_caller():
    out = storage.prepare_raw_job(
        _raw(), known_startup_companies=set(), extra_tags=["startup", "startup_source:conviction"]
    )
    tags = out.get("tags") or []
    assert "startup" in tags and "startup_source:conviction" in tags
    assert "occupation:software_engineering" in tags


def test_the_description_is_decoded_before_the_tags_are_inferred():
    """Ordering, not just presence.

    The occupation tag is classified from the title *and the description*, so
    inferring before decoding would classify against angle brackets and entity
    names rather than the words of the posting.
    """
    body = inspect.getsource(storage.prepare_raw_job)
    decode_at = body.index("decode_source_html")
    for later in ("_infer_startup_tags_for_job", "_infer_occupation_tags_for_job"):
        assert decode_at < body.index(later), f"{later} runs before the description is decoded"


def test_no_storage_path_prepares_a_job_by_hand():
    """The guard that matters: a fourth path must not grow its own preparation.

    Each of these three primitives is a thing a path can silently forget, and
    forgetting one is invisible until a user filters a feed and finds nothing.
    They belong to `prepare_raw_job` and nowhere else.
    """
    primitives = (
        "_infer_occupation_tags_for_job(",
        "_infer_startup_tags_for_job(",
        "decode_source_html(",
    )
    package = Path(inspect.getfile(storage)).parent
    offenders = []
    for module in sorted(package.glob("*.py")):
        source = module.read_text()
        for line_no, line in enumerate(source.splitlines(), 1):
            text = line.strip()
            if text.startswith(("#", "def ", "async def ")) or "import" in text:
                continue
            if any(p in text for p in primitives):
                offenders.append(f"{module.name}:{line_no}: {text}")

    # The three calls inside prepare_raw_job itself are the whole allowance.
    assert len(offenders) == 3, (
        "raw-job preparation must happen only in prepare_raw_job; found:\n  "
        + "\n  ".join(offenders)
    )
    assert all(o.startswith("storage.py:") for o in offenders), offenders


def test_both_search_entry_points_route_through_it():
    for fn in (search.search_ats_jobs, search.search_jobs):
        assert "prepare_raw_job" in inspect.getsource(fn), fn.__name__
