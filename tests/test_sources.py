import io
import json
import unittest

from public_ai_news.sources import fetch_hacker_news


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


if __name__ == "__main__":
    unittest.main()
