"""Optional LLM layer.

Nothing in the core pipeline imports this package at module scope. It is loaded
lazily and only when ``llm_enabled`` is true, so the deterministic pipeline runs
identically with the layer absent, disabled, or failing.
"""

from .client import LLMDisabled, LLMUnavailable, get_client, is_enabled

__all__ = ["LLMDisabled", "LLMUnavailable", "get_client", "is_enabled"]
