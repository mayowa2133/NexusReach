"""Multi-provider LLM client for generating outreach messages.

Supports Anthropic (Claude), OpenAI (GPT), Google (Gemini), and Groq (Llama).
Provider is selected globally via NEXUSREACH_LLM_PROVIDER env var.
"""

from app.config import settings

# Default model per provider
PROVIDER_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "gemini": "gemini-2.5-pro",
    "groq": "llama-3.3-70b-versatile",
}

# Map provider name to its API key getter
PROVIDER_KEYS: dict[str, callable] = {
    "anthropic": lambda: settings.anthropic_api_key,
    "openai": lambda: settings.openai_api_key,
    "gemini": lambda: settings.google_api_key,
    "groq": lambda: settings.groq_api_key,
}


def _parse_reasoning(text: str) -> tuple[str, str]:
    """Extract <reasoning>...</reasoning> from LLM output.

    Returns:
        (reasoning, draft) — reasoning may be empty if no tags found.
    """
    if "<reasoning>" in text and "</reasoning>" in text:
        start = text.index("<reasoning>") + len("<reasoning>")
        end = text.index("</reasoning>")
        reasoning = text[start:end].strip()
        draft = text[end + len("</reasoning>"):].strip()
        return reasoning, draft
    return "", text.strip()


def _resolve_provider() -> str:
    """Determine which LLM provider to use.

    Uses the configured provider if its API key is set,
    otherwise falls back to the first provider with a key.

    Raises:
        ValueError: If no provider has an API key configured.
    """
    configured = settings.llm_provider.lower()
    if configured in PROVIDER_KEYS and PROVIDER_KEYS[configured]():
        return configured

    # Fallback: try each provider
    for name, key_fn in PROVIDER_KEYS.items():
        if key_fn():
            return name

    raise ValueError(
        "No LLM API key configured. Set at least one of: "
        "NEXUSREACH_ANTHROPIC_API_KEY, NEXUSREACH_OPENAI_API_KEY, "
        "NEXUSREACH_GOOGLE_API_KEY, NEXUSREACH_GROQ_API_KEY"
    )


async def _generate_anthropic(
    system_prompt: str, user_prompt: str, max_tokens: int
) -> dict:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=PROVIDER_MODELS["anthropic"],
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text
    reasoning, draft = _parse_reasoning(text)

    return {
        "draft": draft,
        "reasoning": reasoning,
        "model": response.model,
        "provider": "anthropic",
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }


async def _generate_openai(
    system_prompt: str, user_prompt: str, max_tokens: int
) -> dict:
    import openai

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=PROVIDER_MODELS["openai"],
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    text = response.choices[0].message.content or ""
    reasoning, draft = _parse_reasoning(text)

    usage = response.usage
    return {
        "draft": draft,
        "reasoning": reasoning,
        "model": response.model,
        "provider": "openai",
        "usage": {
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
        },
    }


async def _generate_gemini(
    system_prompt: str, user_prompt: str, max_tokens: int
) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.google_api_key)
    response = await client.aio.models.generate_content(
        model=PROVIDER_MODELS["gemini"],
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
        ),
    )

    text = response.text or ""
    reasoning, draft = _parse_reasoning(text)

    meta = response.usage_metadata
    return {
        "draft": draft,
        "reasoning": reasoning,
        "model": PROVIDER_MODELS["gemini"],
        "provider": "gemini",
        "usage": {
            "input_tokens": meta.prompt_token_count if meta else 0,
            "output_tokens": meta.candidates_token_count if meta else 0,
        },
    }


async def _generate_groq(
    system_prompt: str, user_prompt: str, max_tokens: int
) -> dict:
    import groq

    client = groq.AsyncGroq(api_key=settings.groq_api_key)
    response = await client.chat.completions.create(
        model=PROVIDER_MODELS["groq"],
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    text = response.choices[0].message.content or ""
    reasoning, draft = _parse_reasoning(text)

    usage = response.usage
    return {
        "draft": draft,
        "reasoning": reasoning,
        "model": PROVIDER_MODELS["groq"],
        "provider": "groq",
        "usage": {
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
        },
    }


_GENERATORS = {
    "anthropic": _generate_anthropic,
    "openai": _generate_openai,
    "gemini": _generate_gemini,
    "groq": _generate_groq,
}


async def generate_message(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 1024,
) -> dict:
    """Generate a message draft using the configured LLM provider.

    Returns:
        {
            "draft": str,
            "reasoning": str,
            "model": str,
            "provider": str,
            "usage": {"input_tokens": int, "output_tokens": int}
        }
    """
    provider = _resolve_provider()
    return await _GENERATORS[provider](system_prompt, user_prompt, max_tokens)
