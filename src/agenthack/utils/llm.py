"""Anthropic client wrapper with web search tool support."""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic


_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
}


def call_with_search(
    model: str,
    system: str,
    prompt: str,
    max_tokens: int = 8192,
    temperature: float = 1.0,
) -> str:
    """Call Claude with web_search tool enabled. Returns assistant text response."""
    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": prompt}],
    )
    # Collect all text blocks (may interleave with tool use)
    parts: list[str] = []
    for block in response.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)


def call(
    model: str,
    system: str,
    prompt: str,
    max_tokens: int = 8192,
    temperature: float = 1.0,
) -> str:
    """Plain Claude call without tools."""
    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    parts: list[str] = []
    for block in response.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)


def extract_json(text: str) -> Any:
    """Extract the first JSON object or array from a text response."""
    # Try to find a JSON code block first
    import re
    json_block = re.search(r"```(?:json)?\s*([\[{].*?)\s*```", text, re.DOTALL)
    if json_block:
        try:
            return json.loads(json_block.group(1))
        except json.JSONDecodeError:
            pass
    # Fall back to finding raw JSON
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        # Find matching closing bracket
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(text[start:], start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"No valid JSON found in response:\n{text[:500]}")
