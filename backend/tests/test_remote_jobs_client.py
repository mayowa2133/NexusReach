import base64
import json

import httpx
import pytest

from app.clients.remote_jobs_client import (
    _extract_dice_apply_url_from_html,
    _extract_dice_configured_url,
    _parse_simplify_html_jobs,
    _search_dice_with_client,
)


def _dice_apply_redirect(configured_url: str) -> str:
    payload = base64.b64encode(
        json.dumps({"configuredUrl": configured_url}).encode("utf-8")
    ).decode("utf-8")
    return f"https://www.dice.com/apply-redirect?applyData={payload}"


def test_extract_dice_configured_url_decodes_apply_redirect():
    apply_url = "https://careers.example.com/jobs/123?source=dice"

    assert _extract_dice_configured_url(_dice_apply_redirect(apply_url)) == apply_url


def test_extract_dice_apply_url_from_detail_html():
    page_html = (
        r'<script>self.__next_f.push([1,"'
        r'\"applicationDetail\":{\"type\":\"APPLY_TO_URL\",'
        r'\"url\":\"https://careers.example.com/jobs/42?in_iframe=1\u0026src=dice\",'
        r'\"email\":null}'
        r'"])</script>'
    )

    assert (
        _extract_dice_apply_url_from_html(page_html)
        == "https://careers.example.com/jobs/42?in_iframe=1&src=dice"
    )


@pytest.mark.asyncio
async def test_search_dice_sets_apply_url_from_redirect_and_detail_page():
    redirect_apply_url = "https://external.example.com/apply/abc"
    redirect_url = _dice_apply_redirect(redirect_apply_url)
    detail_url = "https://www.dice.com/job-detail/ec674898-da56-4b27-b76a-c2bdafe01fd9"
    detail_apply_url = "https://careers.example.com/jobs/42?in_iframe=1&src=dice"
    detail_html = (
        r'<script>self.__next_f.push([1,"'
        r'\"applicationDetail\":{\"type\":\"APPLY_TO_URL\",'
        r'\"url\":\"https://careers.example.com/jobs/42?in_iframe=1\u0026src=dice\",'
        r'\"email\":null}'
        r'"])</script>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "job-search-api.svc.dhigroupinc.com":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "dice-1",
                            "title": "Software Engineer",
                            "companyName": "External Corp",
                            "jobLocation": {"displayName": "New York, NY"},
                            "isRemote": False,
                            "detailsPageUrl": redirect_url,
                            "redirectUrl": redirect_url,
                            "summary": "Build software.",
                            "postedDate": "2026-05-20T00:00:00Z",
                        },
                        {
                            "id": "dice-2",
                            "title": "Backend Engineer",
                            "companyName": "Careers Corp",
                            "companyLogoUrl": "https://cdn.example.com/logo.png",
                            "jobLocation": {"displayName": "Remote"},
                            "isRemote": True,
                            "detailsPageUrl": detail_url,
                            "summary": "Build services.",
                            "postedDate": "2026-05-21T00:00:00Z",
                        },
                    ]
                },
            )
        if str(request.url) == detail_url:
            return httpx.Response(200, text=detail_html)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, timeout=15) as client:
        jobs = await _search_dice_with_client(client, "software engineer", limit=2)

    assert jobs[0]["url"] == redirect_url
    assert jobs[0]["apply_url"] == redirect_apply_url
    assert jobs[1]["url"] == detail_url
    assert jobs[1]["apply_url"] == detail_apply_url
    assert jobs[1]["company_logo"] == "https://cdn.example.com/logo.png"


def test_parse_simplify_html_jobs_uses_direct_apply_link():
    html = """
    <table>
      <tbody>
        <tr>
          <td><strong><a href="https://simplify.jobs/c/Captivation">Captivation</a></strong></td>
          <td>Software Engineer 1</td>
          <td>Annapolis Junction, MD</td>
          <td>
            <div align="center">
              <a href="https://job-boards.greenhouse.io/captivation/jobs/5230024008">
                <img src="apply.png" alt="Apply">
              </a>
              <a href="https://simplify.jobs/p/example">
                <img src="simplify.png" alt="Simplify">
              </a>
            </div>
          </td>
          <td>1d</td>
        </tr>
      </tbody>
    </table>
    """

    jobs = _parse_simplify_html_jobs(html, limit=10)

    assert len(jobs) == 1
    assert jobs[0]["company_name"] == "Captivation"
    assert jobs[0]["title"] == "Software Engineer 1"
    assert jobs[0]["url"] == "https://job-boards.greenhouse.io/captivation/jobs/5230024008"
    assert jobs[0]["apply_url"] == "https://job-boards.greenhouse.io/captivation/jobs/5230024008"
