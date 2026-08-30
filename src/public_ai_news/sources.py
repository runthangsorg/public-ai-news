"""Fetch news from external sources."""
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable, List, Mapping


DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


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


def fetch_from_config(config_json: str = None) -> list[Mapping[str, Any]]:
    if config_json is None:
        config_json = os.environ.get("NEWS_SOURCE_CONFIG_JSON")
        
    sources = DEFAULT_SOURCES
    if config_json:
        try:
            parsed = json.loads(config_json)
            if isinstance(parsed, dict) and parsed.get("sources"):
                sources = parsed["sources"]
            elif isinstance(parsed, list) and parsed:
                sources = parsed
        except json.JSONDecodeError:
            pass
            
    all_items = []
    for source in sources:
        limit = source.get("limit", 15)
        stype = source.get("type")
        if stype == "hn_algolia":
            all_items.extend(fetch_hn_algolia(limit=limit))
        elif stype == "hackernews":
            all_items.extend(fetch_hacker_news(limit=limit))
        elif stype == "rss" and "url" in source:
            all_items.extend(fetch_rss(source["url"], limit=limit, source_name=source.get("source", "rss")))
            
    return all_items
