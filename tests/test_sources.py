import io
import json
import unittest

from public_ai_news.sources import (
    SourceConfigError,
    _validated_sources,
    fetch_hacker_news,
    _fetch_x_search,
    _fetch_reddit,
    _fetch_github_trending,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class HackerNewsSourceTests(unittest.TestCase):
    def test_algolia_query_is_recent_and_hn_fallback_has_an_id(self):
        captured = []
        payload = {
            "hits": [
                {
                    "title": "Recent LLM release",
                    "objectID": "98765",
                    "points": 12,
                }
            ]
        }

        def opener(request, timeout):
            captured.append(request.full_url)
            return _Response(json.dumps(payload).encode())

        from public_ai_news.sources import fetch_hn_algolia

        items = fetch_hn_algolia(limit=1, opener=opener)
        self.assertEqual(items[0]["url"], "https://news.ycombinator.com/item?id=98765")
        self.assertIn("numericFilters", captured[0])

    def test_fetch_is_bounded_and_returns_only_generic_fields(self):
        payloads = {
            "https://hacker-news.firebaseio.com/v0/topstories.json": [11, 12, 13],
            "https://hacker-news.firebaseio.com/v0/item/11.json": {
                "title": "LLM inference release",
                "url": "https://example.test/11?tracking=abc",
                "score": 8,
                "descendants": 4,
                "time": 1893542400,
                "text": "A source-provided inference release summary.",
                "by": "private-ish-author",
            },
            "https://hacker-news.firebaseio.com/v0/item/12.json": {
                "title": "Machine learning compiler",
                "url": "https://example.test/12",
                "score": 7,
            },
        }

        def opener(request, timeout):
            url = request.full_url
            return _Response(json.dumps(payloads[url]).encode())

        items = fetch_hacker_news(limit=2, opener=opener)

        self.assertEqual(len(items), 2)
        self.assertEqual(
            set(items[0]),
            {
                "title",
                "url",
                "source",
                "score",
                "comment_count",
                "comments_url",
                "published_at",
                "summary",
            },
        )
        self.assertNotIn("by", json.dumps(items))

    def test_rss_extracts_summary_date_and_canonical_link(self):
        from public_ai_news.sources import fetch_rss

        payload = b"""<rss><channel><item>
        <title>New multimodal model release</title>
        <link>https://example.test/model?tracking=1</link>
        <description><![CDATA[<p>The model handles text, images, and audio.</p>]]></description>
        <pubDate>Tue, 02 Jan 2030 08:00:00 GMT</pubDate>
        </item></channel></rss>"""

        def opener(request, timeout):
            return _Response(payload)

        items = fetch_rss(
            "https://example.test/feed.xml",
            source_name="example-feed",
            opener=opener,
        )

        self.assertEqual(items[0]["summary"], "The model handles text, images, and audio.")
        self.assertEqual(items[0]["published_at"], "2030-01-02T08:00:00+00:00")
        self.assertEqual(items[0]["source"], "example-feed")

    def test_rss_uses_permalink_guid_when_link_is_omitted(self):
        from public_ai_news.sources import fetch_rss

        payload = b"""<rss><channel><item>
        <title>LLM training update</title>
        <guid isPermaLink="true">https://example.test/training-update</guid>
        <description>Training efficiency improved.</description>
        </item></channel></rss>"""

        def opener(request, timeout):
            return _Response(payload)

        items = fetch_rss("https://example.test/feed.xml", opener=opener)

        self.assertEqual(items[0]["url"], "https://example.test/training-update")

    def test_article_meta_description_provides_bounded_source_extract(self):
        from public_ai_news.sources import fetch_article_extract

        payload = b"""<html><head>
        <meta property="og:description" content="A technical source extract about GPU inference.">
        </head><body></body></html>"""

        def opener(request, timeout):
            return _Response(payload)

        extract = fetch_article_extract("https://example.test/article", opener=opener)

        self.assertEqual(extract, "A technical source extract about GPU inference.")

    def test_article_fetch_rejects_private_host_before_opening(self):
        def forbidden_opener(*args, **kwargs):
            raise AssertionError("unsafe URL reached network opener")

        from public_ai_news.sources import fetch_article_extract

        self.assertEqual(
            fetch_article_extract("http://127.0.0.1/internal", opener=forbidden_opener),
            "",
        )

    def test_missing_summaries_are_enriched_without_overwriting_feed_extracts(self):
        from public_ai_news.sources import enrich_missing_summaries

        calls = []

        def fetcher(url):
            calls.append(url)
            return "Article metadata extract."

        items = enrich_missing_summaries(
            [
                {"url": "https://example.test/one", "summary": ""},
                {"url": "https://example.test/two", "summary": "Feed extract."},
            ],
            fetcher=fetcher,
            max_fetches=1,
        )

        self.assertEqual(calls, ["https://example.test/one"])
        self.assertEqual(items[0]["summary"], "Article metadata extract.")
        self.assertEqual(items[1]["summary"], "Feed extract.")


class SourceConfigTests(unittest.TestCase):
    def test_config_is_required_bounded_and_strict(self):
        for payload in ("", "not json", "[]", '{"sources": []}', '{"unknown": []}'):
            with self.subTest(payload=payload), self.assertRaises(SourceConfigError):
                _validated_sources(payload)

    def test_config_accepts_supported_public_sources(self):
        sources = _validated_sources(
            '{"sources": ['
            '{"type": "hn_algolia", "query": "AI inference", "limit": 10},'
            '{"type": "rss", "url": "https://example.test/feed.xml", '
            '"source": "example", "limit": 5}]}'
        )

        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]["query"], "AI inference")
        self.assertEqual(sources[1]["url"], "https://example.test/feed.xml")

    def test_config_rejects_private_schemes_and_unknown_fields(self):
        for payload in (
            '[{"type": "rss", "url": "file:///private/feed.xml"}]',
            '[{"type": "rss", "url": "http://127.0.0.1/feed.xml"}]',
            '[{"type": "rss", "url": "https://user:pass@example.test/feed.xml"}]',
            '[{"type": "hackernews", "token": "secret"}]',
            '[{"type": "unknown"}]',
        ):
            with self.subTest(payload=payload), self.assertRaises(SourceConfigError):
                _validated_sources(payload)

    def test_config_accepts_new_source_types(self):
        sources = _validated_sources(
            '{"sources": ['
            '{"type": "x_search", "query": "AI", "limit": 10},'
            '{"type": "reddit", "query": "machine learning", "limit": 10},'
            '{"type": "github_trending", "limit": 10}]}'
        )
        
        self.assertEqual(len(sources), 3)
        self.assertEqual(sources[0]["type"], "x_search")
        self.assertEqual(sources[0]["query"], "AI")
        self.assertEqual(sources[0]["limit"], 10)
        self.assertEqual(sources[1]["type"], "reddit")
        self.assertEqual(sources[1]["query"], "machine learning")
        self.assertEqual(sources[1]["limit"], 10)
        self.assertEqual(sources[2]["type"], "github_trending")
        self.assertEqual(sources[2]["limit"], 10)
        
    def test_x_search_returns_empty_list_due_to_privacy_boundary(self):
        # X search returns empty list to maintain privacy boundary (no API keys)
        items = _fetch_x_search("AI")
        self.assertEqual(items, [])
        
    def test_reddit_fetcher_returns_items_with_correct_structure(self):
        # Mock the reddit response to test structure
        import public_ai_news.sources as sources_module
        
        # Store original function
        original_urlopen = sources_module.urllib.request.urlopen
        
        try:
            # Mock response
            class MockResponse:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def read(self):
                    return json.dumps({
                        "data": {
                            "children": [{
                                "data": {
                                    "title": "Test AI Post",
                                    "url": "https://example.com/test",
                                    "is_self": False,
                                    "score": 100,
                                    "created_utc": 1693171200,
                                    "num_comments": 25,
                                    "permalink": "/r/MachineLearning/comments/test/",
                                    "selftext": "This is a test post about AI",
                                    "stickied": False,
                                    "removed_by_category": None
                                }
                            }]
                        }
                    }).encode()
            
            def mock_opener(request, timeout):
                return MockResponse()
            
            # Patch the urlopen function
            sources_module.urllib.request.urlopen = mock_opener
            
            items = _fetch_reddit("AI")
            
            # Should have 2 items (from 2 subreddits being processed)
            self.assertEqual(len(items), 2)
            # Check first item
            item = items[0]
            self.assertIn("title", item)
            self.assertIn("url", item)
            self.assertIn("source", item)
            self.assertIn("score", item)
            self.assertEqual(item["source"], "reddit-machinelearning")
            self.assertTrue(item["url"].startswith("https://"))
            # Check second item
            item = items[1]
            self.assertIn("title", item)
            self.assertIn("url", item)
            self.assertIn("source", item)
            self.assertIn("score", item)
            self.assertEqual(item["source"], "reddit-artificial")
            self.assertTrue(item["url"].startswith("https://"))
        finally:
            # Restore original function
            sources_module.urllib.request.urlopen = original_urlopen
            
    def test_github_trending_fetcher_returns_items_with_correct_structure(self):
        # Mock the github trending response to test structure
        import public_ai_news.sources as sources_module
        
        # Store original function
        original_urlopen = sources_module.urllib.request.urlopen
        
        try:
            # Mock response
            class MockResponse:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def read(self):
                    return json.dumps([{
                        "author": "test-user",
                        "name": "awesome-ai",
                        "description": "An awesome AI repository",
                        "url": "https://github.com/test-user/awesome-ai",
                        "stars": 1500
                    }]).encode()
            
            def mock_opener(request, timeout):
                return MockResponse()
            
            # Patch the urlopen function
            sources_module.urllib.request.urlopen = mock_opener
            
            items = _fetch_github_trending()
            
            # Should have one item with correct structure
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertIn("title", item)
            self.assertIn("url", item)
            self.assertIn("source", item)
            self.assertIn("score", item)
            self.assertEqual(item["source"], "github-trending")
            self.assertEqual(item["score"], 1500)
            self.assertTrue(item["url"].startswith("https://github.com/"))
        finally:
            # Restore original function
            sources_module.urllib.request.urlopen = original_urlopen


if __name__ == "__main__":
    unittest.main()
