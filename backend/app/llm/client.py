"""Thin Anthropic client wrapper. Absent SDK or key = feature simply off."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import get_settings

log = logging.getLogger(__name__)


class LLMDisabled(RuntimeError):
    """Raised when the LLM layer is switched off."""


class LLMUnavailable(RuntimeError):
    """Raised when the SDK or API key is missing."""


def is_enabled() -> bool:
    settings = get_settings()
    return bool(settings.llm_enabled and settings.llm_api_key)


def get_client() -> Any:
    settings = get_settings()
    if not settings.llm_enabled:
        raise LLMDisabled("LLM layer disabled (set IFCSCHED_LLM_ENABLED=true)")
    if not settings.llm_api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
    try:
        import anthropic
    except ImportError as exc:
        raise LLMUnavailable("anthropic SDK not installed (pip install anthropic)") from exc
    return anthropic.Anthropic(api_key=settings.llm_api_key)


def complete_json(prompt: str, max_tokens: int = 2000) -> Any:
    """Ask for JSON and return it parsed, or raise. Callers must handle failure."""
    client = get_client()
    settings = get_settings()
    response = client.messages.create(
        model=settings.llm_model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    start = text.find("[")
    brace = text.find("{")
    if brace != -1 and (start == -1 or brace < start):
        start = brace
    if start == -1:
        raise ValueError("model returned no JSON")
    end = max(text.rfind("]"), text.rfind("}"))
    return json.loads(text[start : end + 1])
