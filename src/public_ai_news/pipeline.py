"""Sanitize, cluster and rank public AI-engineering story metadata."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
import math
import re
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


SIGNALS = {
    "artificial intelligence": 8,
    "machine learning": 7,
    "language model": 8,
    "large language model": 9,
    "llm": 8,
    "inference": 7,
    "agentic": 7,
    "ai agent": 8,
    "deepseek": 10,
    "openai": 9,
    "anthropic": 9,
    "claude": 9,
    "gemini": 9,
    "chatgpt": 8,
    "qwen": 9,
    "llama": 8,
    "mistral": 8,
    "neural network": 7,
    "transformer": 7,
    "multimodal": 8,
    "vision-language": 8,
    "reasoning model": 9,
    "reasoning": 6,
    "diffusion": 6,
    "fine-tuning": 6,
    "training": 4,
    "rag": 6,
    "gpu": 5,
    "benchmark": 5,
    "model release": 7,
    "compiler": 5,
    "serving": 5,
    "quantization": 6,
    "token": 3,
    "ai": 1,
    "github": 6,
    "repository": 5,
    "open source": 7,
    "model card": 6,
    "dataset": 5,
    "benchmark": 5,
    "paper": 6,
    "code": 4,
    "copilot": 8,
    "rust": 6,
    "reinforcement learning": 8,
    "rl": 7,
    "non-autoregressive": 7,
    "decision model": 6,
    "pareto": 5,
    "model weights": 7,
    "weights": 5,
    "exfiltrate": 6,
    "security": 5,
    "agent": 6,
    "autoregressive": 6,
    "optimization": 5,
    "frontier": 5,
    "preview": 4,
    "release": 4,
    "port": 4,
    "runtime": 5,
    "microsoft": 5,
    "google": 5,
    "mcp": 8,
    "model context protocol": 8,
    "coding agent": 7,
    "agent framework": 7,
    "function calling": 6,
    "tool use": 6,
    "vllm": 7,
    "ollama": 7,
    "sglang": 6,
    "inference server": 6,
    "langchain": 6,
    "claude code": 7,
    "agents.md": 7,
    "open weights": 6,
    "cursor": 5,
    "aider": 5,
}
_VERSION_BUMP = re.compile(r"\b\d+\.\d+(?:\.\d+|[a-z]+\d*)\b")
_FLUFF_RE = re.compile(
    r"my prediction|next decade|jobs automated|career advice|for teachers|"
    r"school districts|what students gain|talk like claude|claude code addiction|"
    r"\bforecast\b.*\b2030\b",
    re.IGNORECASE,
)
_CJK_RE = re.compile(
    "[\u2e80-\u2eff\u3000-\u303f\u3040-\u30ff\u3100-\u312f\u3200-\u32ff"
    "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)
_HANDLE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{1,30}")
_SPACE = re.compile(r"\s+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:token|password|secret|api[_ -]?key)\s*[:=]\s*\S+"
)
_SOURCE_CHARS = re.compile(r"[^a-z0-9._-]+")
_TITLE_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "new",
    "of",
    "on",
    "the",
    "to",
    "today",
    "with",
}
_SOURCE_BONUS = {
    "openai": 25,
    "google-deepmind": 25,
    "nvidia-technical-blog": 25,
    "hugging-face": 20,
    "simon-willison": 8,
    "venturebeat-ai": 10,
    "github-trending": 15,
    "reddit-machinelearning": 12,
    "reddit-artificial": 12,
    "reddit-localllama": 12,
    "reddit-singularity": 10,
    "reddit-deeplearning": 12,
}
_NOISE_PHRASES = (
    "no ai fridays",
    "talk like claude",
    "claude code addiction",
    "my dad taught me",
    "for teachers",
    "school districts",
    "what students gain",
    "ai legal advice",
    "check out my",
    "follow me",
    "subscribe to",
    "drop a like",
    "leave a comment",
    "my prediction",
    "next decade",
    "jobs automated",
)
_TECHNICAL_TERMS = {
    "language model": 7,
    "large language model": 8,
    "llm": 7,
    "inference": 7,
    "agentic": 6,
    "ai agent": 7,
    "claude": 6,
    "gemini": 6,
    "deepseek": 7,
    "qwen": 7,
    "llama": 6,
    "mistral": 6,
    "neural network": 6,
    "transformer": 6,
    "multimodal": 7,
    "vision-language": 7,
    "reasoning": 5,
    "diffusion": 5,
    "fine-tuning": 5,
    "quantization": 6,
    "rag": 5,
    "gpu": 5,
    "benchmark": 4,
    "compiler": 5,
    "serving": 5,
    "robotics": 5,
    "transcription": 4,
    "checkpoint": 4,
    "copilot": 7,
    "rust": 6,
    "reinforcement learning": 7,
    "rl": 6,
    "non-autoregressive": 6,
    "decision model": 6,
    "pareto": 5,
    "model weights": 6,
    "weights": 4,
    "exfiltrate": 6,
    "security": 5,
    "agent": 5,
    "autoregressive": 5,
    "optimization": 5,
    "frontier": 4,
    "preview": 3,
    "release": 3,
    "port": 4,
    "runtime": 5,
    "microsoft": 5,
    "google": 5,
    "mcp": 7,
    "model context protocol": 7,
    "coding agent": 6,
    "agent framework": 6,
    "function calling": 5,
    "tool use": 5,
    "vllm": 6,
    "ollama": 6,
    "sglang": 5,
    "inference server": 5,
    "langchain": 5,
    "claude code": 6,
    "agents.md": 6,
    "open weights": 5,
    "cursor": 4,
    "aider": 4,
}


def _public_url(value: Any) -> str:
    raw = str(value or "").strip()[:2048]
    parts = urlsplit(raw)
    if not _safe_public_url(parts):
        return ""
    if parts.netloc.lower() == "news.ycombinator.com" and parts.path == "/item":
        item_ids = parse_qs(parts.query).get("id", [])
        if len(item_ids) == 1 and item_ids[0].isdigit():
            return urlunsplit(
                (parts.scheme, parts.netloc.lower(), parts.path, urlencode({"id": item_ids[0]}), "")
            )
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _safe_public_url(parts) -> bool:
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return False
    if parts.username or parts.password or not parts.hostname:
        return False
    hostname = parts.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return address.is_global


def _source(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if "private" in raw or "follow" in raw or raw.startswith("x_"):
        return "private-bridge"
    clean = _SOURCE_CHARS.sub("-", raw).strip("-._")[:48]
    return clean or "public-feed"


def _text(value: Any, *, limit: int) -> str:
    clean = _HANDLE.sub("[account]", str(value or ""))
    clean = _SECRET_ASSIGNMENT.sub("[redacted]", clean)
    clean = "".join(character for character in clean if character.isprintable())
    return _SPACE.sub(" ", clean).strip()[:limit]


def _source_extract(value: Any) -> str:
    clean = _text(value, limit=1200)
    if not clean:
        return ""
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", clean)
        if sentence.strip()
    ]
    extract = " ".join(sentences[:2]) if sentences else clean
    if len(extract) <= 600:
        return extract
    bounded = extract[:597].rsplit(" ", 1)[0].rstrip(" ,;:")
    return (bounded or extract[:597]).rstrip() + "..."


def _best_extract(title: str, summary: Any, *, limit: int = 170) -> str:
    """Select the most technical, non-redundant sentence(s) for the digest row."""
    clean = _text(summary, limit=1200)
    if not clean:
        return ""
    # Strip a leading title repeat ("Title Title rest...") common in feed metadata.
    folded_title = " ".join(str(title or "").split()).casefold()
    folded_clean = clean.casefold()
    if folded_title and len(folded_title) >= 12 and folded_clean.startswith(folded_title):
        clean = clean[len(folded_title):].lstrip(" :;,.–—-").strip()
        if not clean:
            return ""
    # Non-English gate: don't ship unreadable extracts.
    if len(clean) > 20 and len(_CJK_RE.findall(clean)) / len(clean) > 0.3:
        return ""
    title_tokens = {
        token
        for token in _TITLE_TOKEN.findall(title.casefold())
        if token not in _STOPWORDS and len(token) > 3
    }
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", clean)
        if sentence.strip() and len(sentence.strip()) >= 25
    ]
    if not sentences:
        return clean[:limit].strip()
    scored = []
    for sentence in sentences:
        tokens = set(_TITLE_TOKEN.findall(sentence.casefold()))
        long_tokens = {token for token in tokens if len(token) > 3}
        overlap = (
            len(long_tokens & title_tokens) / max(1, len(long_tokens))
            if long_tokens
            else 0.0
        )
        if overlap > 0.6 and len(long_tokens) >= 4:
            continue  # restates the title; adds no information
        tech = _technical_relevance(sentence)
        scored.append((tech, len(sentence), sentence))
    if not scored:
        scored = [(0, len(sentence), sentence) for sentence in sentences]
    scored.sort(key=lambda entry: (-entry[0], -min(entry[1], 170)))
    picked = [scored[0][2]]
    total = len(scored[0][2])
    for _, _, sentence in scored[1:]:
        if total + 1 + len(sentence) <= limit + 40:
            picked.append(sentence)
            total += 1 + len(sentence)
        if total >= limit:
            break
    extract = " ".join(picked)
    if len(extract) <= limit:
        return extract
    bounded = extract[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return (bounded or extract[: limit - 1]).rstrip() + "…"


def _published_at(value: Any) -> str:
    raw = str(value or "").strip()[:80]
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _bounded_integer(value: Any, maximum: int = 1_000_000) -> int:
    try:
        return max(0, min(int(value or 0), maximum))
    except (TypeError, ValueError):
        return 0


def sanitize_item(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return the narrow schema allowed across the private/public boundary."""
    title = _text(raw.get("title"), limit=240)
    return {
        "title": title,
        "url": _public_url(raw.get("url")),
        "comments_url": _public_url(raw.get("comments_url")),
        "source": _source(raw.get("source")),
        "summary": _best_extract(title, raw.get("summary")),
        "published_at": _published_at(raw.get("published_at")),
        "score": _bounded_integer(raw.get("score")),
        "comment_count": _bounded_integer(raw.get("comment_count")),
    }


def _relevance(text: str) -> int:
    lowered = text.lower()
    return sum(
        weight
        for term, weight in SIGNALS.items()
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lowered)
    )


def _technical_relevance(text: str) -> int:
    lowered = text.lower()
    score = sum(
        weight
        for term, weight in _TECHNICAL_TERMS.items()
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lowered)
    )
    if re.search(r"\b(?:introduc(?:e|ing)|releas(?:e|ed)|launch(?:es|ed)?)\b.{0,45}\bmodel\b", lowered):
        score += 6
    return score


def _category(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    if any(
        term in text
        for term in (
            "inference",
            "gpu",
            "compiler",
            "serving",
            "quantization",
            "chip",
            "latency",
        )
    ):
        return "Inference & Infrastructure"
    if any(term in text for term in ("agent", "tool use", "developer", "coding", "api", "framework")):
        return "Agents & Developer Tools"
    if any(
        term in text
        for term in (
            "model release",
            "new model",
            "claude",
            "gemini",
            "qwen",
            "llama",
            "mistral",
            "deepseek",
            "openai",
            "anthropic",
        )
    ):
        return "Models & Releases"
    if any(
        term in text
        for term in ("research", "paper", "benchmark", "training", "fine-tuning", "dataset")
    ):
        return "Research & Training"
    if any(
        term in text
        for term in ("safety", "security", "policy", "regulation", "governance", "legal")
    ):
        return "Safety & Policy"
    return "AI Engineering"


def _title_tokens(title: str) -> set[str]:
    return {
        token
        for token in _TITLE_TOKEN.findall(title.casefold())
        if token not in _STOPWORDS and len(token) > 1
    }


def _near_duplicate(tokens: set[str], accepted: list[set[str]]) -> bool:
    if len(tokens) < 4:
        return False
    for previous in accepted:
        union = tokens | previous
        if union and len(tokens & previous) / len(union) >= 0.70:
            return True
    return False


def _freshness(value: str) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def _is_stale(value: str, *, max_age_days: int = 45) -> bool:
    if not value:
        return False
    try:
        published = datetime.fromisoformat(value)
    except ValueError:
        return False
    now = datetime.now(timezone.utc)
    return published < now - timedelta(days=max_age_days)


def _fresh_bonus(value: Any) -> int:
    """Reward recency so evergreen giants can't top the digest every day."""
    try:
        published = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return 0
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - published
    if age <= timedelta(days=3):
        return 8
    if age <= timedelta(days=7):
        return 4
    return 0


def _rank_score(item: Mapping[str, Any]) -> int:
    title = str(item.get("title") or "").casefold()
    combined = f"{item.get('title', '')} {item.get('summary', '')}".casefold()
    prefix_penalty = 12 if title.startswith(("show hn:", "ask hn:")) else 0
    # Demote micro version bumps (e.g. "datasette 1.0a40") unless strongly relevant.
    version_penalty = (
        14
        if _VERSION_BUMP.search(title) and int(item.get("relevance", 0)) < 30
        else 0
    )
    fluff_penalty = 18 if _FLUFF_RE.search(combined) else 0
    base = (
        int(item["relevance"])
        + _SOURCE_BONUS.get(str(item["source"]), 0)
        - prefix_penalty
        - version_penalty
        - fluff_penalty
    )
    # Log-scaled social: 200k-star evergreens must not dwarf a 500-pt HN thread.
    try:
        likes = int(math.log10(int(item.get("score", 0)) + 1) * 12)
    except (TypeError, ValueError):
        likes = 0
    try:
        discussion = int(math.log10(int(item.get("comment_count", 0)) + 1) * 8)
    except (TypeError, ValueError):
        discussion = 0
    social = min(likes, 30) + min(discussion, 15)
    return base + social + _fresh_bonus(item.get("published_at"))


def rank_items(
    raw_items: Iterable[Mapping[str, Any]], *, limit: int = 20
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    candidates = []
    exact_seen: set[tuple[str, str]] = set()
    for raw in raw_items:
        item = sanitize_item(raw)
        combined = f"{item['title']} {item['summary']}".casefold()
        title_relevance = _relevance(item["title"])
        summary_relevance = _relevance(item["summary"])
        relevance = title_relevance * 2 + summary_relevance
        technical_relevance = _technical_relevance(combined)
        fingerprint = (item["title"].casefold(), item["url"])
        if (
            not item["title"]
            or not item["url"]
            or relevance < 8
            or technical_relevance < 4
            or fingerprint in exact_seen
            or any(phrase in combined for phrase in _NOISE_PHRASES)
            or _is_stale(item["published_at"])
        ):
            continue
        exact_seen.add(fingerprint)
        item["relevance"] = relevance
        item["category"] = _category(item["title"], item["summary"])
        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            -_rank_score(item),
            -_freshness(item["published_at"]),
            -item["score"],
            -item["comment_count"],
            item["title"],
        )
    )
    ranked: list[dict[str, Any]] = []
    accepted_tokens: list[set[str]] = []
    per_source: dict[str, int] = {}
    deferred: list[dict[str, Any]] = []
    for item in candidates:
        tokens = _title_tokens(item["title"])
        if _near_duplicate(tokens, accepted_tokens):
            continue
        # Top-5 stays diverse (max 2/source); the rest allows up to 3/source.
        cap = 2 if len(ranked) < 5 else 3
        if per_source.get(item["source"], 0) >= cap:
            deferred.append(item)
            continue
        accepted_tokens.append(tokens)
        ranked.append(item)
        per_source[item["source"]] = per_source.get(item["source"], 0) + 1
        if len(ranked) >= limit:
            break
    if len(ranked) < limit:
        for item in deferred:
            tokens = _title_tokens(item["title"])
            if _near_duplicate(tokens, accepted_tokens):
                continue
            if per_source.get(item["source"], 0) >= 3:
                continue
            accepted_tokens.append(tokens)
            ranked.append(item)
            per_source[item["source"]] = per_source.get(item["source"], 0) + 1
            if len(ranked) >= limit:
                break
    return ranked
