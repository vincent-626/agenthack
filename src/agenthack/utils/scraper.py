"""Firecrawl wrapper for web scraping."""

from __future__ import annotations

import os
from typing import Any


def _get_client():
    try:
        from firecrawl import FirecrawlApp
        api_key = os.environ.get("FIRECRAWL_API_KEY", "")
        return FirecrawlApp(api_key=api_key)
    except ImportError:
        return None


def scrape_url(url: str, max_chars: int = 10000) -> str:
    """Scrape a URL and return clean markdown. Returns empty string on failure."""
    client = _get_client()
    if not client:
        return ""
    try:
        result = client.scrape_url(url, formats=["markdown"])
        text = result.get("markdown", "") if isinstance(result, dict) else getattr(result, "markdown", "")
        return (text or "")[:max_chars]
    except Exception as e:
        return f"[Scrape failed: {e}]"


def search_and_scrape(query: str, num_results: int = 5) -> list[dict[str, str]]:
    """Search the web via Firecrawl and return scraped results."""
    client = _get_client()
    if not client:
        return []
    try:
        results = client.search(query, limit=num_results)
        if isinstance(results, dict):
            data = results.get("data", [])
        else:
            data = results if isinstance(results, list) else []
        out = []
        for item in data:
            if isinstance(item, dict):
                out.append({
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "markdown": (item.get("markdown") or item.get("description") or "")[:5000],
                })
        return out
    except Exception as e:
        return [{"url": "", "title": "Error", "markdown": f"[Search failed: {e}]"}]
