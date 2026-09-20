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
    subqueries = [part.strip() for part in query.split(" OR ") if part.strip()] or [query]
    per_query_limit = max(5, min(limit, 25))
    seen_ids: set[str] = set()
    items: list[Mapping[str, Any]] = []

    for subquery in subqueries:
        params = {
            "tags": "story",
            "query": subquery,
            "hitsPerPage": per_query_limit,
            "numericFilters": f"created_at_i>={since}",
        }
        url = "https://hn.algolia.com/api/v1/search_by_date?" + urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
        try:
            with opener(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                for hit in data.get("hits", []):
                    item_id = str(hit.get("objectID") or "").strip()
                    if not item_id or item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                    title = hit.get("title") or ""
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
        if len(items) >= limit:
            break
    return items[:limit]


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
        elif stype == "x_search":
            if set(source) - {"type", "query", "limit"}:
                raise SourceConfigError("X source contains unknown fields")
            query = " ".join(str(source.get("query") or "AI").split())
            if not 1 <= len(query) <= 200:
                raise SourceConfigError("X query is out of bounds")
            validated.append(
                {"type": stype, "limit": _bounded_limit(source.get("limit", 15)), "query": query}
            )
        elif stype == "x_timeline":
            if set(source) - {"type", "mode", "screen_name", "limit"}:
                raise SourceConfigError("X timeline source contains unknown fields")
            mode = str(source.get("mode") or "home").strip().lower()
            if mode not in {"home", "profile"}:
                raise SourceConfigError("X timeline mode must be home or profile")
            screen_name = " ".join(str(source.get("screen_name") or "").split())
            if mode == "profile":
                import re as _re2

                if not _re2.fullmatch(r"[A-Za-z0-9_]{1,15}", screen_name):
                    raise SourceConfigError("X profile screen_name is invalid")
            validated.append(
                {
                    "type": stype,
                    "mode": mode,
                    "screen_name": screen_name,
                    "limit": _bounded_limit(source.get("limit", 15)),
                }
            )
        elif stype == "reddit":
            if set(source) - {"type", "query", "limit"}:
                raise SourceConfigError("Reddit source contains unknown fields")
            query = " ".join(str(source.get("query") or "AI").split())
            if not 1 <= len(query) <= 200:
                raise SourceConfigError("Reddit query is out of bounds")
            validated.append(
                {"type": stype, "limit": _bounded_limit(source.get("limit", 15)), "query": query}
            )
        elif stype == "github_trending":
            if set(source) - {"type", "limit"}:
                raise SourceConfigError("GitHub trending source contains unknown fields")
            validated.append(
                {"type": stype, "limit": _bounded_limit(source.get("limit", 15))}
            )
        elif stype == "bluesky":
            if set(source) - {"type", "handles", "limit", "query", "search_limit"}:
                raise SourceConfigError("Bluesky source contains unknown fields")
            raw_handles = source.get("handles") or ["karpathy.bsky.social"]
            if not isinstance(raw_handles, list) or not 1 <= len(raw_handles) <= 20:
                raise SourceConfigError("Bluesky handles must be a list of 1-20 items")
            import re as _re

            handles = []
            for handle in raw_handles:
                cleaned = " ".join(str(handle or "").split()).lower()
                if not _re.fullmatch(r"[a-z0-9][a-z0-9.\-]{1,60}", cleaned):
                    raise SourceConfigError(f"invalid Bluesky handle: {handle!r}")
                handles.append(cleaned)
            query = " ".join(str(source.get("query") or "AI agents LLM").split())
            if not 1 <= len(query) <= 200:
                raise SourceConfigError("Bluesky query is out of bounds")
            try:
                search_limit = int(source.get("search_limit", 8))
            except (TypeError, ValueError) as exc:
                raise SourceConfigError("Bluesky search_limit must be an integer") from exc
            if not 0 <= search_limit <= 30:
                raise SourceConfigError("Bluesky search_limit must be between 0 and 30")
            validated.append(
                {
                    "type": stype,
                    "limit": _bounded_limit(source.get("limit", 15)),
                    "handles": handles,
                    "query": query,
                    "search_limit": search_limit,
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
        elif stype == "x_search":
            all_items.extend(_fetch_x_search(source["query"], limit=limit))
        elif stype == "x_timeline":
            all_items.extend(
                _fetch_x_timeline(
                    mode=source.get("mode", "home"),
                    screen_name=source.get("screen_name", ""),
                    limit=limit,
                )
            )
        elif stype == "reddit":
            all_items.extend(_fetch_reddit(source["query"], limit=limit))
        elif stype == "github_trending":
            all_items.extend(_fetch_github_trending(limit=limit))
        elif stype == "bluesky":
            all_items.extend(
                _fetch_bluesky(
                    source["handles"],
                    limit=limit,
                    query=source.get("query", "AI agents LLM"),
                    search_limit=source.get("search_limit", 8),
                )
            )

    return all_items


def _TEXT_SANITIZER(value: Any) -> str:
    """Sanitize text by replacing @handles with [account]."""
    import re
    handle_pattern = re.compile(r"(?<!\w)@[A-Za-z0-9_]{1,30}")
    return handle_pattern.sub("[account]", str(value or ""))


def _bluesky_session_token() -> str:
    """Create an in-memory Bluesky session; empty string when creds are absent."""
    handle = (os.environ.get("BLUESKY_HANDLE") or "").strip()
    password = (os.environ.get("BLUESKY_APP_PASSWORD") or "").strip()
    if not handle or not password:
        return ""
    try:
        payload = json.dumps({"identifier": handle, "password": password}).encode()
        req = urllib.request.Request(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": DEFAULT_USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            return str(json.loads(response.read().decode("utf-8")).get("accessJwt") or "")
    except Exception:
        return ""


def _bluesky_post_to_item(post: Mapping[str, Any], handle: str, source: str) -> Optional[Mapping[str, Any]]:
    record = post.get("record", {}) or {}
    text = _TEXT_SANITIZER(record.get("text", "")).strip()
    if not text:
        return None
    rkey = str(post.get("uri") or "").rsplit("/", 1)[-1]
    if not rkey:
        return None
    author_handle = str((post.get("author", {}) or {}).get("handle") or handle)
    link = f"https://bsky.app/profile/{author_handle}/post/{rkey}"
    if not _safe_public_url(link):
        return None
    try:
        likes = int(post.get("likeCount") or 0)
    except (TypeError, ValueError):
        likes = 0
    try:
        replies = int(post.get("replyCount") or 0)
    except (TypeError, ValueError):
        replies = 0
    first_line = text.split("\n", 1)[0].strip() or text[:140]
    return {
        "title": first_line[:240],
        "url": link,
        "score": likes,
        "source": source,
        "summary": _clean_markup(text, limit=800),
        "published_at": _published_at(post.get("indexedAt") or record.get("createdAt")),
        "comment_count": replies,
        "comments_url": link,
    }


def _fetch_bluesky_handle(handle: str, per_handle: int) -> list[Mapping[str, Any]]:
    """Recent posts from one followed account (public endpoint, no auth)."""
    import urllib.parse

    try:
        url = (
            "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
            f"?actor={urllib.parse.quote_plus(handle)}&limit={per_handle}"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    source = f"bluesky-{handle.split('.')[0].lower()}"
    items = []
    for entry in data.get("feed", []):
        item = _bluesky_post_to_item(entry.get("post", {}), handle, source)
        if item:
            items.append(item)
    return items


def _fetch_bluesky_search(query: str, search_limit: int, token: str) -> list[Mapping[str, Any]]:
    """Global like-sorted Bluesky search (needs app-password session)."""
    import urllib.parse

    if not token or search_limit <= 0:
        return []
    try:
        url = (
            "https://bsky.social/xrpc/app.bsky.feed.searchPosts"
            f"?q={urllib.parse.quote_plus(query)}&limit={min(search_limit, 25)}&sort=top"
        )
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    items = []
    for post in data.get("posts", []):
        author_handle = str((post.get("author", {}) or {}).get("handle") or "bluesky")
        item = _bluesky_post_to_item(post, author_handle, "bluesky-search")
        if item:
            items.append(item)
    return items


def _fetch_bluesky(
    handles: list[str], limit: int = 15, query: str = "AI agents LLM", search_limit: int = 8
) -> list[Mapping[str, Any]]:
    """
    Followed Bluesky AI accounts (parallel, public) plus like-sorted global
    search when BLUESKY_HANDLE/BLUESKY_APP_PASSWORD are configured.
    Likes map to score and replies to comment_count so community-validated
    posts rank.
    """
    from concurrent.futures import ThreadPoolExecutor

    items: list[Mapping[str, Any]] = []
    per_handle = max(2, min(4, limit // max(1, len(handles)) + 1))
    workers = min(6, max(1, len(handles)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for handle_items in executor.map(
            lambda handle: _fetch_bluesky_handle(handle, per_handle), handles
        ):
            items.extend(handle_items)
    token = _bluesky_session_token()
    items.extend(_fetch_bluesky_search(query, search_limit, token))

    items.sort(
        key=lambda item: (int(item.get("score", 0)), int(item.get("comment_count", 0))),
        reverse=True,
    )
    return items[:limit]


def _fetch_x_search(query: str, limit: int = 15) -> list[Mapping[str, Any]]:
    """
    Fetch AI-related posts from X (Twitter) search.
    Note: This implementation returns an empty list to maintain privacy boundary
    as it would require API authentication which violates the system's privacy principles.
    In a production system with proper credentials, this would connect to Twitter API v2.
    """
    # Return empty list to maintain privacy boundary - no social tokens/cookies
    return []


# Public x.com web-client bearer (ships in the web app; not a secret).
_X_Bearer = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs="
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
_X_QUERIES = {
    "home": "-X_hcgQzmHGl29-UXxz4sw/HomeTimeline",
    "profile": "QWF3SzpHmykQHsQMixG0cg/UserTweets",
}


def _x_session_cookies() -> tuple[str, str]:
    return (
        (os.environ.get("TWITTER_AUTH_TOKEN") or "").strip(),
        (os.environ.get("TWITTER_CT0") or "").strip(),
    )


def _x_graphql(path: str, variables: Mapping[str, Any], auth: str, ct0: str) -> Mapping[str, Any]:
    import urllib.parse

    url = (
        f"https://x.com/i/api/graphql/{path}?"
        + urllib.parse.urlencode(
            {
                "variables": json.dumps(dict(variables)),
                "features": json.dumps(
                    {"responsive_web_graphql_exclude_directive_enabled": True}
                ),
            }
        )
    )
    req = urllib.request.Request(
        url,
        headers={
            "authorization": f"Bearer {_X_Bearer}",
            "x-csrf-token": ct0,
            "x-twitter-auth-type": "OAuth2Session",
            "origin": "https://x.com",
            "referer": "https://x.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
            ),
            "Cookie": f"auth_token={auth}; ct0={ct0}",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _x_parse_tweet_entries(data: Mapping[str, Any], source: str) -> list[Mapping[str, Any]]:
    instructions: list[Mapping[str, Any]] = []
    try:
        home = data.get("data", {}).get("home", {})
        user = data.get("data", {}).get("user", {}).get("result", {})
        if home and home.get("home_timeline_urt"):
            instructions = home["home_timeline_urt"].get("instructions", [])
        else:
            instructions = (
                user.get("timeline_v2", {}).get("timeline", {}).get("instructions", [])
            )
    except (AttributeError, TypeError):
        return []
    items = []
    for instruction in instructions:
        for entry in instruction.get("entries", []) or []:
            content = (entry.get("content", {}) or {}).get("itemContent", {})
            result = ((content.get("tweet_results", {}) or {}).get("result", {})) or {}
            legacy = result.get("legacy", {}) or {}
            text = _TEXT_SANITIZER(legacy.get("full_text", "")).strip()
            if not text or "legacy" not in result:
                continue
            user_legacy = (
                ((result.get("core", {}) or {}).get("user_results", {}) or {})
                .get("result", {})
                .get("legacy", {})
            ) or {}
            screen_name = str(user_legacy.get("screen_name") or "").strip()
            rest_id = str(result.get("rest_id") or legacy.get("id_str") or "")
            if not screen_name or not rest_id.isdigit():
                continue
            link = f"https://x.com/{screen_name}/status/{rest_id}"
            if not _safe_public_url(link):
                continue
            try:
                likes = int(legacy.get("favorite_count") or 0)
            except (TypeError, ValueError):
                likes = 0
            try:
                replies = int(legacy.get("reply_count") or 0)
            except (TypeError, ValueError):
                replies = 0
            try:
                reposts = int(legacy.get("retweet_count") or 0)
            except (TypeError, ValueError):
                reposts = 0
            first_line = text.split("\n", 1)[0].strip() or text[:140]
            items.append(
                {
                    "title": first_line[:240],
                    "url": link,
                    "score": likes,
                    "source": source,
                    "summary": _clean_markup(text, limit=800),
                    "published_at": _published_at(legacy.get("created_at")),
                    "comment_count": replies + reposts,
                    "comments_url": link,
                }
            )
    return items


def _x_resolve_user_id(screen_name: str, auth: str, ct0: str) -> str:
    try:
        req = urllib.request.Request(
            f"https://api.fxtwitter.com/{screen_name}",
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            uid = str(
                json.loads(response.read().decode("utf-8")).get("user", {}).get("id")
                or ""
            )
        return uid if uid.isdigit() else ""
    except Exception:
        return ""


def _fetch_x_timeline(mode: str = "home", screen_name: str = "", limit: int = 15) -> list[Mapping[str, Any]]:
    """
    Read the user's X home timeline (followed accounts) or a public profile
    timeline via x.com web GraphQL using session cookies from the environment.
    Returns [] when cookies are absent or rejected — never raises.
    """
    auth, ct0 = _x_session_cookies()
    if not auth or not ct0:
        return []
    try:
        if mode == "profile":
            uid = _x_resolve_user_id(screen_name, auth, ct0)
            if not uid:
                return []
            data = _x_graphql(
                _X_QUERIES["profile"],
                {
                    "userId": uid,
                    "count": min(max(limit, 5), 40),
                    "includePromotedContent": False,
                    "withQuickPromoteEligibilityTweetFields": False,
                    "withVoice": False,
                    "withV2Timeline": True,
                },
                auth,
                ct0,
            )
            source = f"x-{screen_name.lower()}"
        else:
            data = _x_graphql(
                _X_QUERIES["home"],
                {"count": min(max(limit * 2, 20), 60), "includePromotedContent": False,
                 "latestControlAvailable": True},
                auth,
                ct0,
            )
            source = "x-home"
        items = _x_parse_tweet_entries(data, source)
    except Exception:
        return []
    items.sort(
        key=lambda item: (int(item.get("score", 0)), int(item.get("comment_count", 0))),
        reverse=True,
    )
    return items[:limit]


def _fetch_reddit(query: str, limit: int = 15) -> list[Mapping[str, Any]]:
    """
    Fetch AI-related posts from Reddit using public JSON endpoints.
    Uses old.reddit.com which permits unauthenticated JSON reads.
    """
    import urllib.parse

    items: list[Mapping[str, Any]] = []
    subreddits = ["LocalLLaMA", "MachineLearning", "artificial"]
    per_sub = max(2, min(8, limit // 3 + 1))
    search_query = urllib.parse.quote_plus(" ".join(str(query or "AI").split())[:200])

    def _append_post(post_data: Mapping[str, Any], subreddit: str) -> None:
        if post_data.get("stickied") or post_data.get("removed_by_category"):
            return
        title = _TEXT_SANITIZER(post_data.get("title", ""))
        link = str(post_data.get("url") or "")
        permalink = str(post_data.get("permalink") or "")
        if post_data.get("is_self") and permalink:
            link = f"https://old.reddit.com{permalink}"
        if not title or not link or not _safe_public_url(link):
            return
        try:
            score = int(post_data.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        try:
            comments = int(post_data.get("num_comments") or 0)
        except (TypeError, ValueError):
            comments = 0
        created = post_data.get("created_utc")
        published = _epoch(created) or _published_at(created)
        comments_url = f"https://old.reddit.com{permalink}" if permalink else link
        items.append(
            {
                "title": title[:240],
                "url": link,
                "score": score,
                "source": f"reddit-{subreddit.lower()}",
                "summary": _clean_markup(post_data.get("selftext"), limit=800),
                "published_at": published,
                "comment_count": comments,
                "comments_url": comments_url,
            }
        )

    for subreddit in subreddits:
        # 1) Live search (works when Reddit is not blocking the runner).
        try:
            url = (
                f"https://old.reddit.com/r/{subreddit}/search.json"
                f"?q={search_query}&sort=top&t=week&limit={per_sub}&restrict_sr=1"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            for post in data.get("data", {}).get("children", []):
                _append_post(post.get("data", {}), subreddit)
            if any(item["source"] == f"reddit-{subreddit.lower()}" for item in items):
                continue
        except Exception:
            pass
        # 2) Arctic Shift archive fallback (public, no auth; single-token
        # query — multi-term queries 422 on some subreddits).
        try:
            fallback_query = urllib.parse.quote_plus(
                (str(query or "AI").split() or ["AI"])[0][:40]
            )
            url = (
                "https://arctic-shift.photon-reddit.com/api/posts/search"
                f"?query={fallback_query}&subreddit={subreddit}&limit={per_sub}&sort=desc"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                data = json.loads(response.read().decode("utf-8"))
            for post_data in data.get("data", []):
                _append_post(post_data, subreddit)
        except Exception:
            continue

    items.sort(key=lambda item: (int(item.get("score", 0)), int(item.get("comment_count", 0))), reverse=True)
    return items[:limit]


def _fetch_github_trending(limit: int = 15) -> list[Mapping[str, Any]]:
    """
    Fetch trending AI tooling repos via the public GitHub Search API.
    Stars map to score (likes) and forks map to comment_count so the
    ranker can surface the most-discussed tooling.
    """
    import urllib.parse

    items: list[Mapping[str, Any]] = []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d")
    queries = [
        f"topic:llm stars:>1000 pushed:>{cutoff}",
        f"mcp ai-agent stars:>500 pushed:>{cutoff}",
    ]
    seen: set[str] = set()

    for query in queries:
        try:
            url = (
                "https://api.github.com/search/repositories?q="
                + urllib.parse.quote_plus(query)
                + f"&sort=stars&order=desc&per_page={max(3, min(limit, 10))}"
            )
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
            for repo in data.get("items", []):
                html_url = str(repo.get("html_url") or "")
                full_name = str(repo.get("full_name") or "")
                if not html_url or not _safe_public_url(html_url) or html_url in seen:
                    continue
                seen.add(html_url)
                try:
                    stars = int(repo.get("stargazers_count") or 0)
                except (TypeError, ValueError):
                    stars = 0
                try:
                    forks = int(repo.get("forks_count") or 0)
                except (TypeError, ValueError):
                    forks = 0
                description = _clean_markup(repo.get("description"), limit=800)
                language = str(repo.get("language") or "").strip()
                topics = repo.get("topics") or []
                topic_text = " ".join(str(topic) for topic in topics[:6] if topic)
                summary = " ".join(
                    part
                    for part in (
                        description,
                        f"Language: {language}." if language else "",
                        f"Topics: {topic_text}." if topic_text else "",
                        f"{stars} stars, {forks} forks." if stars else "",
                    )
                    if part
                )[:800]
                title = f"{full_name}: {description[:140]}" if description else full_name
                published = _published_at(repo.get("pushed_at")) or _published_at(
                    repo.get("updated_at")
                )
                if title and html_url:
                    items.append(
                        {
                            "title": title[:240],
                            "url": html_url,
                            "score": stars,
                            "source": "github-trending",
                            "summary": summary,
                            "published_at": published,
                            "comment_count": forks,
                            "comments_url": f"{html_url}/issues",
                        }
                    )
                if len(items) >= limit:
                    break
        except Exception:
            continue
        if len(items) >= limit:
            break

    items.sort(
        key=lambda item: (int(item.get("score", 0)), int(item.get("comment_count", 0))),
        reverse=True,
    )
    return items[:limit]
