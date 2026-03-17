"""Unit tests for LLM-based relevance scoring."""

import json

import pytest
from unittest.mock import patch, AsyncMock

from app.utils.relevance_scorer import score_candidate_relevance

pytestmark = pytest.mark.asyncio


def _make_candidates(count: int = 3) -> list[dict]:
    """Create test candidate dicts."""
    return [
        {
            "full_name": f"Person {i}",
            "title": f"Engineer {i}",
            "company": "TestCo",
            "snippet": f"Works on team {i} at TestCo",
            "linkedin_url": f"https://linkedin.com/in/person{i}",
            "source": "brave_search",
        }
        for i in range(count)
    ]


def _mock_llm_response(scores: list[dict]) -> dict:
    """Create a mock LLM response with scores JSON."""
    return {
        "draft": json.dumps({"scores": scores}),
        "reasoning": "",
        "model": "gpt-4o",
        "provider": "openai",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


class TestScoreCandidateRelevance:
    """Tests for score_candidate_relevance()."""

    async def test_scores_all_candidates_by_default(self):
        """Default min_score=1 returns all candidates with scores attached."""
        candidates = _make_candidates(3)
        scores = [
            {"index": 0, "score": 5},
            {"index": 1, "score": 1},
            {"index": 2, "score": 4},
        ]

        with patch(
            "app.clients.llm_client.generate_message",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(scores),
        ):
            result = await score_candidate_relevance(
                candidates, "Engineer", "TestCo", ["backend"], "engineering",
            )

        # Default min_score=1 → all 3 returned with scores
        assert len(result) == 3
        assert result[0]["relevance_score"] == 5
        assert result[1]["relevance_score"] == 1
        assert result[2]["relevance_score"] == 4

    async def test_filters_with_min_score(self):
        """Passing min_score filters out low-scoring candidates."""
        candidates = _make_candidates(3)
        scores = [
            {"index": 0, "score": 5},
            {"index": 1, "score": 1},
            {"index": 2, "score": 4},
        ]

        with patch(
            "app.clients.llm_client.generate_message",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(scores),
        ):
            result = await score_candidate_relevance(
                candidates, "Engineer", "TestCo", ["backend"], "engineering",
                min_score=4,
            )

        assert len(result) == 2
        assert result[0]["full_name"] == "Person 0"
        assert result[0]["relevance_score"] == 5
        assert result[1]["full_name"] == "Person 2"
        assert result[1]["relevance_score"] == 4

    async def test_filters_with_min_score_3(self):
        """min_score=3 reproduces the old default behavior."""
        candidates = _make_candidates(3)
        scores = [
            {"index": 0, "score": 5},
            {"index": 1, "score": 1},
            {"index": 2, "score": 4},
        ]

        with patch(
            "app.clients.llm_client.generate_message",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(scores),
        ):
            result = await score_candidate_relevance(
                candidates, "Engineer", "TestCo", ["backend"], "engineering",
                min_score=3,
            )

        assert len(result) == 2
        assert result[0]["relevance_score"] == 5
        assert result[1]["relevance_score"] == 4

    async def test_returns_all_when_llm_not_configured(self):
        candidates = _make_candidates(2)

        with patch(
            "app.clients.llm_client.generate_message",
            new_callable=AsyncMock,
            side_effect=ValueError("No LLM provider configured"),
        ):
            result = await score_candidate_relevance(
                candidates, "Engineer", "TestCo", ["backend"], "engineering",
            )

        assert len(result) == 2

    async def test_returns_all_on_llm_error(self):
        candidates = _make_candidates(2)

        with patch(
            "app.clients.llm_client.generate_message",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API error"),
        ):
            result = await score_candidate_relevance(
                candidates, "Engineer", "TestCo", ["backend"], "engineering",
            )

        assert len(result) == 2

    async def test_returns_empty_for_empty_input(self):
        result = await score_candidate_relevance(
            [], "Engineer", "TestCo", ["backend"], "engineering",
        )
        assert result == []

    async def test_handles_malformed_json(self):
        candidates = _make_candidates(2)

        with patch(
            "app.clients.llm_client.generate_message",
            new_callable=AsyncMock,
            return_value={"draft": "not valid json at all", "reasoning": "", "model": "", "provider": "", "usage": {}},
        ):
            result = await score_candidate_relevance(
                candidates, "Engineer", "TestCo", ["backend"], "engineering",
            )

        assert len(result) == 2  # all returned unfiltered

    async def test_handles_json_in_code_fences(self):
        candidates = _make_candidates(2)
        scores = [{"index": 0, "score": 5}, {"index": 1, "score": 4}]
        fenced = f"```json\n{json.dumps({'scores': scores})}\n```"

        with patch(
            "app.clients.llm_client.generate_message",
            new_callable=AsyncMock,
            return_value={"draft": fenced, "reasoning": "", "model": "", "provider": "", "usage": {}},
        ):
            result = await score_candidate_relevance(
                candidates, "Engineer", "TestCo", ["backend"], "engineering",
            )

        assert len(result) == 2
        assert result[0]["relevance_score"] == 5

    async def test_prompt_includes_job_context(self):
        candidates = _make_candidates(1)
        candidates[0]["snippet"] = "Works on payments"

        mock_generate = AsyncMock(
            return_value=_mock_llm_response([{"index": 0, "score": 5}]),
        )

        with patch("app.clients.llm_client.generate_message", mock_generate):
            await score_candidate_relevance(
                candidates, "Senior Backend Engineer", "Stripe",
                ["payments", "infrastructure"], "engineering",
            )

        user_prompt = mock_generate.call_args[1]["user_prompt"]
        assert "Senior Backend Engineer" in user_prompt
        assert "Stripe" in user_prompt
        assert "payments" in user_prompt
        assert "Person 0" in user_prompt

    async def test_fallback_when_all_filtered(self):
        """If min_score filtering removes everyone, return top 2 by score."""
        candidates = _make_candidates(3)
        scores = [
            {"index": 0, "score": 1},
            {"index": 1, "score": 2},
            {"index": 2, "score": 2},
        ]

        with patch(
            "app.clients.llm_client.generate_message",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(scores),
        ):
            result = await score_candidate_relevance(
                candidates, "Engineer", "TestCo", ["backend"], "engineering",
                min_score=3,
            )

        # All scored < 3, fallback returns top 2
        assert len(result) == 2

    async def test_no_fallback_when_min_score_is_1(self):
        """With default min_score=1, all candidates returned (no fallback needed)."""
        candidates = _make_candidates(3)
        scores = [
            {"index": 0, "score": 1},
            {"index": 1, "score": 2},
            {"index": 2, "score": 2},
        ]

        with patch(
            "app.clients.llm_client.generate_message",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(scores),
        ):
            result = await score_candidate_relevance(
                candidates, "Engineer", "TestCo", ["backend"], "engineering",
            )

        # min_score=1 → all returned, no fallback logic
        assert len(result) == 3
