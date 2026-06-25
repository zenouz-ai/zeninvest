"""Anthropic prompt caching helpers for strategy synthesis batches."""

from __future__ import annotations

from typing import Any


def cached_text_block(text: str, *, enabled: bool = True) -> dict[str, Any] | str:
    """Return a text block with ephemeral cache_control when enabled."""
    if not enabled or not text:
        return text
    return {
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"},
    }


def build_cached_system_message(
    system_prompt: str,
    cached_prefix: str,
    *,
    caching_enabled: bool = True,
) -> list[dict[str, Any]] | str:
    """Build system message with cacheable prefix block for multi-batch cycles."""
    if not caching_enabled or not cached_prefix.strip():
        return system_prompt
    return [
        cached_text_block(system_prompt, enabled=caching_enabled),
        cached_text_block(cached_prefix, enabled=caching_enabled),
    ]
