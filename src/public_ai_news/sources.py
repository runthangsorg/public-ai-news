"""Fetch news from external sources."""
import json
import ipaddress
import os
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, List, Mapping, Optional
from urllib.parse import urlencode, urlsplit


DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def _safe_public_url(value: Any) -> bool:
    parts = urlsplit(str(value or "").strip())
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


class SourceConfigError(ValueError):
    """Raised when private runtime source configuration is absent or invalid."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class _ArticleMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.descriptions: dict[str, str] = {}
        self.in_paragraph = False
        self.paragraph_parts: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "meta":
            values = {str(key).lower(): str(value or "") for key, value in attrs}
            name = (values.get("property") or values.get("name") or "").lower()
            content = values.get("content", "").strip()
            if name in {"og:description", "description", "twitter:description"} and content:
                self.descriptions.setdefault(name, content)
        elif tag.lower() == "p" and not self.paragraphs:
            self.in_paragraph = True
            self.paragraph_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "p" and self.in_paragraph:
            paragraph = " ".join(" ".join(self.paragraph_parts).split())
            if len(paragraph) >= 80:
                self.paragraphs.append(paragraph)
            self.in_paragraph = False

    def handle_data(self, data: str) -> None:
        if self.in_paragraph:
            self.paragraph_parts.append(data)

    def extract(self) -> str:
        for name in ("og:description", "description", "twitter:description"):
            if self.descriptions.get(name):
                return _clean_markup(self.descriptions[name], limit=800)
        return _clean_markup(self.paragraphs[0], limit=800) if self.paragraphs else ""


def _clean_markup(value: Any, *, limit: int = 800) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(unescape(str(value or "")))
    except Exception:
        return ""
    return " ".join(" ".join(parser.parts).split())[:limit].strip()


def _published_at(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _epoch(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node: ET.Element, names: set[str]) -> str:
    for child in node:
        if _local_name(child.tag) in names and child.text:
            return child.text
    return ""


def fetch_article_extract(
    url: str,
    *,
    timeout: int = 7,
    max_bytes: int = 750_000,
    opener: Callable = urllib.request.urlopen,
) -> str:
    """Fetch only bounded public article metadata for a truthful source extract."""
    parts = urlsplit(str(url or ""))
    if not _safe_public_url(url):
        return ""
    request = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with opener(request, timeout=timeout) as response:
            payload = response.read(max_bytes + 1)
    except Exception:
        return ""
    if len(payload) > max_bytes:
        return ""
    parser = _ArticleMetadataParser()
    try:
        parser.feed(payload.decode("utf-8", errors="replace"))
    except Exception:
        return ""
    return parser.extract()


def enrich_missing_summaries(
    items: list[Mapping[str, Any]],
    *,
    fetcher: Callable[[str], str] = fetch_article_extract,
    max_fetches: int = 15,
) -> list[dict[str, Any]]:
    """Fill missing extracts from bounded article metadata without changing order."""
    enriched = [dict(item) for item in items]
    indexes = [
        index
        for index, item in enumerate(enriched)
        if not item.get("summary") and item.get("url")
    ][: max(0, min(max_fetches, 20))]
    if not indexes:
        return enriched
    workers = min(4, len(indexes))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        extracts = executor.map(lambda index: fetcher(str(enriched[index]["url"])), indexes)
        for index, extract in zip(indexes, extracts):
            if extract:
                enriched[index]["summary"] = _clean_markup(extract, limit=800)
    return enriched


def fetch_hn_algolia(
    query: str = "AI OR LLM OR DeepSeek OR Anthropic OR OpenAI",
    limit: int = 25,
    opener: Callable = urllib.request.urlopen,
) -> list[Mapping[str, Any]]:
    """Fetch recent AI stories from the Hacker News Algolia search API."""
    import urllib.parse
    since = int((datetime.now(timezone.utc) - timedelta(days=14)).timestamp())
    params = {
        "tags": "story",
        "query": query,
        "hitsPerPage": limit,
        "numericFilters": f"created_at_i>={since}",
    }
    url = "https://hn.algolia.com/api/v1/search_by_date?" + urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    items = []
    try:
        with opener(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            for hit in data.get("hits", []):
                title = hit.get("title") or ""
                item_id = str(hit.get("objectID") or "").strip()
                item_url = hit.get("url") or _hn_item_url(item_id)
                points = hit.get("points") or 1
                if title and item_url:
                    items.append({
                        "title": title,
                        "url": item_url,
                        "score": points,
                        "source": "hacker-news",
                        "summary": _clean_markup(hit.get("story_text")),
                        "published_at": _published_at(hit.get("created_at")),
                        "comment_count": hit.get("num_comments") or 0,
                        "comments_url": _hn_item_url(item_id),
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
                        "url": item.get("url") or _hn_item_url(str(item_id)),
                        "score": item.get("score", 0),
                        "source": "hacker-news",
                        "summary": _clean_markup(item.get("text")),
                        "published_at": _epoch(item.get("time")),
                        "comment_count": item.get("descendants") or 0,
                        "comments_url": _hn_item_url(str(item_id)),
                    })
        except Exception:
            continue
    return items


def _hn_item_url(item_id: str) -> str:
    return (
        f"https://news.ycombinator.com/item?id={item_id}"
        if item_id.isdigit()
        else ""
    )


def fetch_rss(
    url: str, limit: int = 15, source_name: str = "rss", opener: Callable = urllib.request.urlopen
) -> list[Mapping[str, Any]]:
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    items = []
    try:
        with opener(req, timeout=12) as response:
            payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                return []
            root = ET.fromstring(payload)
            count = 0
            
            # Handle RSS 2.0 / 1.0 items
            for item in root.findall(".//item"):
                if count >= limit:
                    break
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if not link:
                    link = _child_text(item, {"guid"}).strip()
                if title and link:
                    items.append({
                        "title": title,
                        "url": link,
                        "score": 5,
                        "source": source_name,
                        "summary": _clean_markup(
                            _child_text(item, {"description", "summary", "content", "encoded"})
                        ),
                        "published_at": _published_at(
                            _child_text(item, {"pubdate", "published", "updated", "date"})
                        ),
                        "comment_count": 0,
                        "comments_url": "",
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
                            "summary": _clean_markup(
                                _child_text(entry, {"summary", "content", "description"})
                            ),
                            "published_at": _published_at(
                                _child_text(entry, {"published", "updated"})
                            ),
                            "comment_count": 0,
                            "comments_url": "",
                        })
                        count += 1
    except Exception:
        pass
    return items


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
            if not _safe_public_url(url):
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
