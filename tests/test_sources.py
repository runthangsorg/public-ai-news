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
        self.assertEqual(set(items[0]), {"title", "url", "source", "score"})
        self.assertNotIn("by", json.dumps(items))


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
