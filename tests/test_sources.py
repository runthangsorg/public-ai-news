import io
import json
import unittest

from public_ai_news.sources import (
    SourceConfigError,
    _validated_sources,
    fetch_hacker_news,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class HackerNewsSourceTests(unittest.TestCase):
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
            '[{"type": "hackernews", "token": "secret"}]',
            '[{"type": "unknown"}]',
        ):
            with self.subTest(payload=payload), self.assertRaises(SourceConfigError):
                _validated_sources(payload)


if __name__ == "__main__":
    unittest.main()
