"""Fetch news from external sources."""
import json
import os
import urllib.request
from typing import Any, Iterator, Mapping, Callable

def fetch_hacker_news(*, limit: int = 50, opener: Callable = urllib.request.urlopen) -> list[Mapping[str, Any]]:
    req = urllib.request.Request(
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        headers={"User-Agent": "bounded-public-ai-news/1.0"}
    )
    with opener(req, timeout=10) as response:
        top_ids = json.loads(response.read())[:limit]
        
    items = []
    for item_id in top_ids:
        item_req = urllib.request.Request(
            f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
            headers={"User-Agent": "bounded-public-ai-news/1.0"}
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

def fetch_rss(url: str, limit: int = 10, opener: Callable = urllib.request.urlopen) -> list[Mapping[str, Any]]:
    # Simple XML parser using xml.etree.ElementTree for basic RSS
    import xml.etree.ElementTree as ET
    req = urllib.request.Request(url, headers={"User-Agent": "bounded-public-ai-news/1.0"})
    items = []
    try:
        with opener(req, timeout=10) as response:
            tree = ET.parse(response)
            root = tree.getroot()
            count = 0
            # Handle RSS 2.0
            for item in root.findall(".//item"):
                if count >= limit:
                    break
                title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                items.append({
                    "title": title,
                    "url": link,
                    "score": 1,
                    "source": "rss",
                })
                count += 1
            # Handle Atom
            if count == 0:
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                for entry in root.findall(".//atom:entry", ns):
                    if count >= limit:
                        break
                    title = entry.findtext("atom:title", namespaces=ns) or ""
                    link_elem = entry.find("atom:link", namespaces=ns)
                    link = link_elem.attrib.get("href", "") if link_elem is not None else ""
                    items.append({
                        "title": title,
                        "url": link,
                        "score": 1,
                        "source": "rss",
                    })
                    count += 1
    except Exception:
        pass
    return items

def fetch_from_config(config_json: str = None) -> list[Mapping[str, Any]]:
    if config_json is None:
        config_json = os.environ.get("NEWS_SOURCE_CONFIG_JSON")
        
    if not config_json:
        return fetch_hacker_news(limit=50)
        
    try:
        config = json.loads(config_json)
        sources = config.get("sources", [])
        if not sources:
            return fetch_hacker_news(limit=50)
            
        all_items = []
        for source in sources:
            limit = source.get("limit", 10)
            if source.get("type") == "hackernews":
                all_items.extend(fetch_hacker_news(limit=limit))
            elif source.get("type") == "rss" and "url" in source:
                all_items.extend(fetch_rss(source["url"], limit=limit))
        return all_items
    except json.JSONDecodeError:
        return fetch_hacker_news(limit=50)
