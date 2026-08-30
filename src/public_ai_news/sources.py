"""Fetch news from external sources."""
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable, List, Mapping, Optional
from urllib.parse import urlsplit


DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


class SourceConfigError(ValueError):
    """Raised when private runtime source configuration is absent or invalid."""


def fetch_hn_algolia(
    query: str = "AI OR LLM OR DeepSeek OR Anthropic OR OpenAI",
    limit: int = 25,
    opener: Callable = urllib.request.urlopen,
) -> list[Mapping[str, Any]]:
    """Fetch recent AI stories from the Hacker News Algolia search API."""
    import urllib.parse
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://hn.algolia.com/api/v1/search_by_date?tags=story&query={encoded_query}&hitsPerPage={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    items = []
    try:
        with opener(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            for hit in data.get("hits", []):
                title = hit.get("title") or ""
                item_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
                points = hit.get("points") or 1
                if title and item_url:
                    items.append({
                        "title": title,
                        "url": item_url,
                        "score": points,
                        "source": "hacker-news",
                    })
    except Exception:
        pass
    return items


def fetch_hacker_news(*, limit: int = 50, opener: Callable = urllib.request.urlopen) -> list[Mapping[str, Any]]:
    req = urllib.request.Request(
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        headers={"User-Agent": DEFAULT_USER_AGENT}
    )
    try:
        with opener(req, timeout=10) as response:
            top_ids = json.loads(response.read())[:limit]
    except Exception:
        return []
        
    items = []
    for item_id in top_ids:
        item_req = urllib.request.Request(
            f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
            headers={"User-Agent": DEFAULT_USER_AGENT}
        )
        try:
            with opener(item_req, timeout=5) as item_res:
                item = json.loads(item_res.read())
                if item and not item.get("deleted"):
                    items.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "score": item.get("score", 0),
                        "source": "hacker-news",
                    })
        except Exception:
            continue
    return items


def fetch_rss(
    url: str, limit: int = 15, source_name: str = "rss", opener: Callable = urllib.request.urlopen
) -> list[Mapping[str, Any]]:
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    items = []
    try:
        with opener(req, timeout=12) as response:
            tree = ET.parse(response)
            root = tree.getroot()
            count = 0
            
            # Handle RSS 2.0 / 1.0 items
            for item in root.findall(".//item"):
                if count >= limit:
                    break
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if title and link:
                    items.append({
                        "title": title,
                        "url": link,
                        "score": 5,
                        "source": source_name,
                    })
                    count += 1
                    
            # Handle Atom entries
            if count == 0:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                for entry in root.findall(".//atom:entry", ns):
                    if count >= limit:
                        break
                    title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
                    link_elem = entry.find("atom:link", namespaces=ns)
                    link = link_elem.attrib.get("href", "").strip() if link_elem is not None else ""
                    if not link:
                        link = (entry.findtext("atom:id", namespaces=ns) or "").strip()
                    if title and link:
                        items.append({
                            "title": title,
                            "url": link,
                            "score": 5,
                            "source": source_name,
                        })
                        count += 1
    except Exception:
        pass
    return items


DEFAULT_SOURCES = [
    {"type": "hn_algolia", "limit": 25},
    {"type": "rss", "url": "https://huggingface.co/blog/feed.xml", "source": "huggingface", "limit": 10},
    {"type": "rss", "url": "https://simonwillison.net/tags/ai.atom", "source": "simonwillison", "limit": 10},
    {"type": "rss", "url": "https://venturebeat.com/category/ai/feed/", "source": "venturebeat", "limit": 10},
    {"type": "hackernews", "limit": 30},
]


def _bounded_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise SourceConfigError("source limit must be an integer") from exc
    if not 1 <= limit <= 100:
        raise SourceConfigError("source limit must be between 1 and 100")
    return limit


def _validated_sources(config_json: str) -> list[dict[str, Any]]:
    if not config_json or len(config_json.encode("utf-8")) > 64_000:
        raise SourceConfigError("news source configuration is empty or oversized")
    try:
        parsed = json.loads(config_json)
    except json.JSONDecodeError as exc:
        raise SourceConfigError("news source configuration is not valid JSON") from exc
    if isinstance(parsed, dict):
        if set(parsed) != {"sources"}:
            raise SourceConfigError("news source configuration contains unknown fields")
        sources = parsed["sources"]
    elif isinstance(parsed, list):
        sources = parsed
    else:
        raise SourceConfigError("news source configuration must contain a source list")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 20:
        raise SourceConfigError("news source configuration must contain 1-20 sources")

    validated: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            raise SourceConfigError("every news source must be an object")
        stype = str(source.get("type") or "")
        if stype == "hn_algolia":
            allowed = {"type", "limit", "query"}
            if set(source) - allowed:
                raise SourceConfigError("Algolia source contains unknown fields")
            query = " ".join(str(source.get("query") or "AI LLM").split())
            if not 1 <= len(query) <= 200:
                raise SourceConfigError("Algolia query is out of bounds")
            validated.append(
                {"type": stype, "limit": _bounded_limit(source.get("limit", 25)), "query": query}
            )
        elif stype == "hackernews":
            if set(source) - {"type", "limit"}:
                raise SourceConfigError("Hacker News source contains unknown fields")
            validated.append(
                {"type": stype, "limit": _bounded_limit(source.get("limit", 30))}
            )
        elif stype == "rss":
            if set(source) - {"type", "url", "source", "limit"}:
                raise SourceConfigError("RSS source contains unknown fields")
            url = str(source.get("url") or "").strip()
            parts = urlsplit(url)
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                raise SourceConfigError("RSS source URL must be public HTTP(S)")
            label = " ".join(str(source.get("source") or "rss").split())
            if not 1 <= len(label) <= 80:
                raise SourceConfigError("RSS source label is out of bounds")
            validated.append(
                {
                    "type": stype,
                    "url": url,
                    "source": label,
                    "limit": _bounded_limit(source.get("limit", 15)),
                }
            )
        else:
            raise SourceConfigError("unsupported news source type")
    return validated


def fetch_from_config(config_json: Optional[str] = None) -> list[Mapping[str, Any]]:
    if config_json is None:
        config_json = os.environ.get("NEWS_SOURCE_CONFIG_JSON")
    sources = _validated_sources(config_json or "")
            
    all_items = []
    for source in sources:
        limit = source.get("limit", 15)
        stype = source.get("type")
        if stype == "hn_algolia":
            all_items.extend(fetch_hn_algolia(query=source["query"], limit=limit))
        elif stype == "hackernews":
            all_items.extend(fetch_hacker_news(limit=limit))
        elif stype == "rss" and "url" in source:
            all_items.extend(fetch_rss(source["url"], limit=limit, source_name=source.get("source", "rss")))
            
    return all_items
