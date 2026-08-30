import json
import unittest

from public_ai_news.pipeline import rank_items, sanitize_item


class SanitizationTests(unittest.TestCase):
    def test_private_identity_and_request_fields_never_cross_boundary(self):
        raw = {
            "title": "@private_handle released a new LLM runtime",
            "url": "https://news.example/story?account=private_handle&token=secret#profile",
            "source": "private_following",
            "author": "private_handle",
            "handle": "@private_handle",
            "raw_response": {"token": "secret"},
            "query_url": "https://social.example/private",
            "score": 50,
        }

        clean = sanitize_item(raw)
        serialized = json.dumps(clean)

        self.assertNotIn("private_handle", serialized)
        self.assertNotIn("token", serialized)
        self.assertNotIn("author", clean)
        self.assertNotIn("handle", clean)
        self.assertEqual(clean["url"], "https://news.example/story")
        self.assertEqual(clean["source"], "private-bridge")

    def test_rejects_non_public_url_schemes(self):
        clean = sanitize_item(
            {"title": "AI model release", "url": "file:///private/item", "source": "feed"}
        )
        self.assertEqual(clean["url"], "")


class RankingTests(unittest.TestCase):
    def test_keeps_ai_engineering_items_and_discards_unrelated_engagement(self):
        ranked = rank_items(
            [
                {
                    "title": "New LLM inference runtime reduces GPU latency",
                    "url": "https://example.test/ai",
                    "source": "public-feed",
                    "score": 10,
                },
                {
                    "title": "A popular sandwich thread",
                    "url": "https://example.test/lunch",
                    "source": "public-feed",
                    "score": 100000,
                },
            ]
        )

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["url"], "https://example.test/ai")
        self.assertGreater(ranked[0]["relevance"], 0)


if __name__ == "__main__":
    unittest.main()
