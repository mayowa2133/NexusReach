"""Claude API client for generating personalized outreach messages."""

import anthropic

from app.config import settings


def _get_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def generate_message(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 1024,
) -> dict:
    """Call Claude to generate a message draft with reasoning.

    Returns:
        {"draft": str, "reasoning": str}
    """
    client = _get_client()

    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text

    # Parse structured output — expect <reasoning>...</reasoning> then the draft
    reasoning = ""
    draft = text
    if "<reasoning>" in text and "</reasoning>" in text:
        start = text.index("<reasoning>") + len("<reasoning>")
        end = text.index("</reasoning>")
        reasoning = text[start:end].strip()
        draft = text[end + len("</reasoning>"):].strip()

    return {
        "draft": draft,
        "reasoning": reasoning,
        "model": response.model,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }
