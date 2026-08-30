"""Bounded collectors for deliberately public, unauthenticated sources."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.request import Request, urlopen


HN_BASE = "https://hacker-news.firebaseio.com/v0"


def _json(
    url: str,
    *,
    opener: Callable[..., Any],
    timeout: int,
    max_bytes: int = 256_000,
) -> Any:
    request = Request(url, headers={"User-Agent": "public-ai-news/1"})
    with opener(request, timeout=timeout) as response:
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("public response exceeded the byte limit")
    return json.loads(payload)


def fetch_hacker_news(
    *, limit: int = 20, timeout: int = 10, opener: Callable[..., Any] = urlopen
) -> list[dict[str, Any]]:
    """Fetch a bounded set of generic story facts; author identity is omitted."""
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    identifiers = _json(
        f"{HN_BASE}/topstories.json", opener=opener, timeout=timeout
    )
    if not isinstance(identifiers, list):
        raise ValueError("unexpected top-stories response")

    items = []
    for identifier in identifiers[:limit]:
        raw = _json(
            f"{HN_BASE}/item/{int(identifier)}.json",
            opener=opener,
            timeout=timeout,
        )
        if not isinstance(raw, dict):
            continue
        items.append(
            {
                "title": raw.get("title", ""),
                "url": raw.get("url", ""),
                "source": "hacker-news",
                "score": raw.get("score", 0),
            }
        )
    return items
