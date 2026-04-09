"""Anthropic client wrapper with web search tool support and retry logic."""

from __future__ import annotations

import json
import os
import random
import time
from typing import Any

import anthropic
from rich.console import Console

console = Console()

_client: anthropic.Anthropic | None = None

# Errors that are safe to retry
_RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.InternalServerError,
)

_MAX_RETRIES = 5
_BASE_DELAY = 1.0   # seconds
_MAX_DELAY = 60.0


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
}


def _with_retry(fn, label: str = "LLM call") -> Any:
    """Call fn() with exponential backoff on retryable errors."""
    delay = _BASE_DELAY
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn()
        except _RETRYABLE as e:
            if attempt == _MAX_RETRIES:
                raise
            # Honour Retry-After header if present (rate limit responses)
            retry_after = getattr(e, "response", None) and e.response.headers.get("retry-after")
            if retry_after:
                wait = float(retry_after)
            else:
                jitter = random.uniform(0, delay * 0.1)
                wait = min(delay + jitter, _MAX_DELAY)
            console.print(
                f"  [yellow]{label} failed ({type(e).__name__}), "
                f"retry {attempt}/{_MAX_RETRIES - 1} in {wait:.1f}s...[/yellow]"
            )
            time.sleep(wait)
            delay = min(delay * 2, _MAX_DELAY)
        except anthropic.APIStatusError as e:
            # 529 Overloaded — retryable; other 4xx are not
            if e.status_code == 529:
                if attempt == _MAX_RETRIES:
                    raise
                wait = min(delay + random.uniform(0, delay * 0.1), _MAX_DELAY)
                console.print(
                    f"  [yellow]{label} overloaded (529), "
                    f"retry {attempt}/{_MAX_RETRIES - 1} in {wait:.1f}s...[/yellow]"
                )
                time.sleep(wait)
                delay = min(delay * 2, _MAX_DELAY)
            else:
                raise


def _collect_text(response) -> str:
    parts: list[str] = []
    for block in response.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)


def call_with_search(
    model: str,
    system: str,
    prompt: str,
    max_tokens: int = 8192,
    temperature: float = 1.0,
) -> str:
    """Call Claude with web_search tool enabled. Returns assistant text response."""
    client = get_client()

    def _call():
        return client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            tools=[WEB_SEARCH_TOOL],
            messages=[{"role": "user", "content": prompt}],
        )

    return _collect_text(_with_retry(_call, label=f"call_with_search({model})"))


def call(
    model: str,
    system: str,
    prompt: str,
    max_tokens: int = 8192,
    temperature: float = 1.0,
) -> str:
    """Plain Claude call without tools."""
    client = get_client()

    def _call():
        return client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )

    return _collect_text(_with_retry(_call, label=f"call({model})"))


def extract_json(text: str) -> Any:
    """Extract the first JSON object or array from a text response."""
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
