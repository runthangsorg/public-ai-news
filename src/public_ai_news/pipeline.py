"""Sanitize generic news facts and rank technically relevant items."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit


SIGNALS = {
    "artificial intelligence": 8,
    "machine learning": 7,
    "language model": 7,
    "llm": 6,
    "inference": 6,
    "agentic": 5,
    "ai agent": 6,
    "neural network": 6,
    "transformer": 5,
    "gpu": 4,
    "model": 2,
    "ai": 3,
}
_HANDLE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{1,30}")
_SPACE = re.compile(r"\s+")


def _public_url(value: Any) -> str:
    raw = str(value or "").strip()[:2048]
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _source(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if "private" in raw or "follow" in raw or raw.startswith("x_"):
        return "private-bridge"
    if raw == "hacker-news":
        return raw
    return "public-feed"


def sanitize_item(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return the narrow schema allowed across the private/public boundary."""
    title = _HANDLE.sub("[account]", str(raw.get("title") or ""))
    title = _SPACE.sub(" ", "".join(c for c in title if c.isprintable())).strip()[:240]
    try:
        score = max(0, min(int(raw.get("score") or 0), 1_000_000))
    except (TypeError, ValueError):
        score = 0
    return {
        "title": title,
        "url": _public_url(raw.get("url")),
        "source": _source(raw.get("source")),
        "score": score,
    }


def _relevance(title: str) -> int:
    text = title.lower()
    return sum(
        weight
        for term, weight in SIGNALS.items()
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text)
    )


def rank_items(
    raw_items: Iterable[Mapping[str, Any]], *, limit: int = 20
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    ranked = []
    seen = set()
    for raw in raw_items:
        item = sanitize_item(raw)
        relevance = _relevance(item["title"])
        fingerprint = (item["title"].casefold(), item["url"])
        if not item["title"] or relevance == 0 or fingerprint in seen:
            continue
        seen.add(fingerprint)
        item["relevance"] = relevance
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["relevance"], -item["score"], item["title"]))
    return ranked[:limit]
