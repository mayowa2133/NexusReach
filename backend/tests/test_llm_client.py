"""Unit tests for multi-provider LLM client — Phase 13."""

import sys
import types

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.clients.llm_client import (
    _parse_reasoning,
    _resolve_provider,
    generate_message,
    _generate_anthropic,
    _generate_openai,
    _GENERATORS,
)

pytestmark = pytest.mark.asyncio


# ── _parse_reasoning ────────────────────────────────────────────────

class TestParseReasoning:
    def test_with_tags(self):
        text = "<reasoning>Think step by step</reasoning>Hello, I'd love to connect."
        reasoning, draft = _parse_reasoning(text)
        assert reasoning == "Think step by step"
        assert draft == "Hello, I'd love to connect."

    def test_without_tags(self):
        text = "Just a plain message."
        reasoning, draft = _parse_reasoning(text)
        assert reasoning == ""
        assert draft == "Just a plain message."

    def test_empty_reasoning(self):
        text = "<reasoning></reasoning>Draft only."
        reasoning, draft = _parse_reasoning(text)
        assert reasoning == ""
        assert draft == "Draft only."

    def test_multiline_reasoning(self):
        text = "<reasoning>\nLine 1\nLine 2\n</reasoning>\nFinal draft."
        reasoning, draft = _parse_reasoning(text)
        assert "Line 1" in reasoning
        assert "Line 2" in reasoning
        assert draft == "Final draft."


# ── _resolve_provider ───────────────────────────────────────────────

class TestResolveProvider:
    def test_configured_provider_with_key(self):
        with patch("app.clients.llm_client.settings") as mock_settings:
            mock_settings.llm_provider = "openai"
            mock_settings.openai_api_key = "sk-test"
            assert _resolve_provider() == "openai"

    def test_fallback_when_configured_key_missing(self):
        with patch("app.clients.llm_client.settings") as mock_settings:
            mock_settings.llm_provider = "anthropic"
            mock_settings.anthropic_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.google_api_key = "goog-key"
            mock_settings.groq_api_key = ""
            assert _resolve_provider() == "gemini"

    def test_no_keys_raises(self):
        with patch("app.clients.llm_client.settings") as mock_settings:
            mock_settings.llm_provider = "anthropic"
            mock_settings.anthropic_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.google_api_key = ""
            mock_settings.groq_api_key = ""
            with pytest.raises(ValueError, match="No LLM API key configured"):
                _resolve_provider()


# ── generate_message dispatching ────────────────────────────────────

class TestGenerateMessage:
    async def test_dispatches_to_correct_provider(self):
        mock_result = {
            "draft": "Hi",
            "reasoning": "",
            "model": "test-model",
            "provider": "anthropic",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_gen = AsyncMock(return_value=mock_result)

        with (
            patch("app.clients.llm_client._resolve_provider", return_value="anthropic"),
            patch.dict(_GENERATORS, {"anthropic": mock_gen}),
        ):
            result = await generate_message("sys", "user")
            mock_gen.assert_awaited_once_with("sys", "user", 1024)
            assert result["provider"] == "anthropic"

    async def test_passes_custom_max_tokens(self):
        mock_result = {
            "draft": "Hi",
            "reasoning": "",
            "model": "gpt-4o",
            "provider": "openai",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_gen = AsyncMock(return_value=mock_result)

        with (
            patch("app.clients.llm_client._resolve_provider", return_value="openai"),
            patch.dict(_GENERATORS, {"openai": mock_gen}),
        ):
            result = await generate_message("sys", "user", max_tokens=512)
            mock_gen.assert_awaited_once_with("sys", "user", 512)
            assert result["provider"] == "openai"


# ── Provider-specific generators ────────────────────────────────────

class TestGenerateAnthropic:
    async def test_calls_anthropic_sdk(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="<reasoning>R</reasoning>Draft text")]
        mock_response.model = "claude-sonnet-4-20250514"
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            result = await _generate_anthropic("system", "user", 1024)

        assert result["draft"] == "Draft text"
        assert result["reasoning"] == "R"
        assert result["provider"] == "anthropic"
        assert result["usage"]["input_tokens"] == 100
        assert result["usage"]["output_tokens"] == 50
        mock_client.messages.create.assert_awaited_once()


class TestGenerateOpenAI:
    async def test_calls_openai_sdk(self):
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 80
        mock_usage.completion_tokens = 40

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Plain draft"
        mock_response.model = "gpt-4o"
        mock_response.usage = mock_usage

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            result = await _generate_openai("system", "user", 1024)

        assert result["draft"] == "Plain draft"
        assert result["reasoning"] == ""
        assert result["provider"] == "openai"
        assert result["usage"]["input_tokens"] == 80
        assert result["usage"]["output_tokens"] == 40


class TestGenerateGemini:
    async def test_calls_gemini_sdk(self):
        mock_meta = MagicMock()
        mock_meta.prompt_token_count = 60
        mock_meta.candidates_token_count = 30

        mock_response = MagicMock()
        mock_response.text = "<reasoning>Thought</reasoning>Gemini draft"
        mock_response.usage_metadata = mock_meta

        mock_aio = AsyncMock()
        mock_aio.models.generate_content = AsyncMock(return_value=mock_response)

        mock_client_instance = MagicMock()
        mock_client_instance.aio = mock_aio

        # Mock the google.genai module since it uses lazy import
        mock_genai = MagicMock()
        mock_genai.Client = MagicMock(return_value=mock_client_instance)
        mock_types = MagicMock()
        mock_genai.types = mock_types

        mock_google = types.ModuleType("google")
        mock_google.genai = mock_genai

        with patch.dict(sys.modules, {
            "google": mock_google,
            "google.genai": mock_genai,
            "google.genai.types": mock_types,
        }):
            from app.clients.llm_client import _generate_gemini
            result = await _generate_gemini("system", "user", 1024)

        assert result["draft"] == "Gemini draft"
        assert result["reasoning"] == "Thought"
        assert result["provider"] == "gemini"
        assert result["usage"]["input_tokens"] == 60
        assert result["usage"]["output_tokens"] == 30


class TestGenerateGroq:
    async def test_calls_groq_sdk(self):
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 70
        mock_usage.completion_tokens = 35

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Groq draft"
        mock_response.usage = mock_usage

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        # Mock the groq module since it uses lazy import and may not be installed
        mock_groq_mod = MagicMock()
        mock_groq_mod.AsyncGroq = MagicMock(return_value=mock_client)

        with patch.dict(sys.modules, {"groq": mock_groq_mod}):
            from app.clients.llm_client import _generate_groq
            result = await _generate_groq("system", "user", 1024)

        assert result["draft"] == "Groq draft"
        assert result["reasoning"] == ""
        assert result["provider"] == "groq"
        assert result["usage"]["input_tokens"] == 70
        assert result["usage"]["output_tokens"] == 35
