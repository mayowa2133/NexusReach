"""Descriptions that arrive HTML-escaped are decoded before anything reads them.

Greenhouse returns its ``content`` field escaped, so the body arrives as
``&lt;div class=&quot;content-intro&quot;&gt;`` rather than as markup. The Job
detail page sanitizes the description and inserts it as HTML, which means
escaped input passes through sanitizing untouched and reaches the reader as
angle brackets and tag names. Every Greenhouse description in the table was
affected -- 1290 of them -- against 2414 jobs carrying a description at all.
"""

from app.utils.job_metadata import decode_source_html

# The real shape, trimmed: this is what a Greenhouse row actually held.
GREENHOUSE = (
    "&lt;div class=&quot;content-intro&quot;&gt;&lt;h2&gt;&lt;strong&gt;"
    "About Anthropic&lt;/strong&gt;&lt;/h2&gt;\n&lt;p&gt;Anthropic's mission is to "
    "create reliable, interpretable, and steerable AI systems.&lt;/p&gt;&lt;/div&gt;"
)


def test_escaped_markup_is_decoded():
    decoded = decode_source_html(GREENHOUSE)
    assert decoded.startswith('<div class="content-intro">')
    assert "&lt;" not in decoded
    # The reader should get a heading, not the word "h2".
    assert "<h2><strong>About Anthropic</strong></h2>" in decoded


def test_real_markup_containing_entities_is_left_alone():
    """The half of the rule that keeps it safe.

    A posting that already contains markup and *also* contains ``&lt;`` is a
    document with escaped entities in its content -- a code sample, say. Decoding
    that would turn the sample the reader is meant to see into tags the browser
    lays out. Five rows in the table look like this (Ashby and Jobicy) and all
    five are genuine.
    """
    original = "<p>Wrap it in <code>&lt;div&gt;</code> like so.</p>"
    assert decode_source_html(original) == original


def test_plain_text_is_left_alone():
    assert decode_source_html("Senior Engineer, no markup here") == (
        "Senior Engineer, no markup here"
    )


def test_decoding_is_idempotent():
    """Decoded text holds a real ``<``, so a second pass is a no-op."""
    once = decode_source_html(GREENHOUSE)
    assert decode_source_html(once) == once


def test_empty_and_missing_values_survive():
    assert decode_source_html(None) is None
    assert decode_source_html("") == ""


def test_description_is_decoded_before_it_is_fingerprinted():
    """Ordering, not just the transform.

    The description feeds the fingerprint, the startup tags and the occupation
    tags as well as the stored column. If it were decoded late, some of those
    would read escaped markup and the rest the real thing -- and because the
    fingerprint is built from the description, one posting would fingerprint as
    two different jobs either side of this change.
    """
    import inspect

    from app.services.jobs import storage

    body = inspect.getsource(storage._store_raw_jobs)
    decode_at = body.index("decode_source_html")
    for later in ("_infer_startup_tags_for_job", "_infer_occupation_tags_for_job", "_fingerprint"):
        assert decode_at < body.index(later), f"{later} reads the description before it is decoded"
