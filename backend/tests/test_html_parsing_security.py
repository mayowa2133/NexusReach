"""SEC-01: malicious page syntax must not monopolize the API event loop."""

import asyncio

import pytest

from app.clients.ats import html
from app.utils import html_parsing
from app.utils.sandboxed_process import run_in_sandbox


@pytest.mark.parametrize("fragment", ["<title>", "<h1 ", "<script>", "<style>", "<"])
def test_repeated_unclosed_tags_have_a_hard_processing_deadline(fragment):
    result = run_in_sandbox(
        "app.utils.html_parsing", "page", fragment * 20_000,
        timeout_seconds=3, memory_bytes=256 * 1024 * 1024,
        cpu_seconds=1, output_bytes=4 * 1024 * 1024,
    )
    assert set(result) == {"title", "content"}


def test_metadata_and_visible_text_preserve_legitimate_content():
    source = """<html><head><title>R&amp;D role</title>
    <link href='https://example.test/job/?tracking=1' rel='canonical'>
    <meta content='2026-10-10' itemprop='datePosted'>
    <script type='application/ld+json'>{"@type":"JobPosting","title":"Engineer"}</script>
    <style>hidden css</style></head><body><h1>Engineer</h1><p>Hello <b>world</b>.</p></body></html>"""
    assert html._extract_title(source) == "R&D role"
    assert html._extract_heading(source) == "Engineer"
    assert html._extract_posted_at(source) == "2026-10-10"
    assert html._extract_json_ld_job(source)["title"] == "Engineer"
    assert html._extract_canonical_link(source) == "https://example.test/job"
    assert "hidden css" not in html_parsing.text(source)
    assert "Hello world" in html_parsing.text(source)


@pytest.mark.asyncio
async def test_page_extraction_yields_to_other_api_work():
    task = asyncio.create_task(html_parsing.page_async("<title>" * 16_000))
    beats = 0
    while not task.done():
        await asyncio.sleep(0.01)
        beats += 1
    assert beats > 0
    assert isinstance((await task)["content"], str)
