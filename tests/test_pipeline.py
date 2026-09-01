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
            "summary": "@private_handle says token=secret about this LLM release.",
            "published_at": "2030-01-02T08:00:00Z",
            "comments_url": "https://news.example/comments?id=private_handle",
            "score": 50,
        }

        clean = sanitize_item(raw)
        serialized = json.dumps(clean)

        self.assertNotIn("private_handle", serialized)
        self.assertNotIn("token", serialized)
        self.assertNotIn("author", clean)
        self.assertNotIn("handle", clean)
        self.assertEqual(clean["url"], "https://news.example/story")
        self.assertEqual(clean["comments_url"], "https://news.example/comments")
        self.assertEqual(clean["source"], "private-bridge")

    def test_rejects_non_public_url_schemes(self):
        clean = sanitize_item(
            {"title": "AI model release", "url": "file:///private/item", "source": "feed"}
        )
        self.assertEqual(clean["url"], "")

    def test_rejects_private_hosts_and_url_credentials(self):
        for url in (
            "http://127.0.0.1/internal",
            "https://localhost/internal",
            "https://user:password@example.test/article",
        ):
            with self.subTest(url=url):
                self.assertEqual(sanitize_item({"title": "AI", "url": url})["url"], "")

    def test_preserves_only_numeric_hacker_news_item_id(self):
        clean = sanitize_item(
            {
                "title": "LLM inference release",
                "url": "https://news.ycombinator.com/item?id=12345&utm_source=private",
                "comments_url": "https://news.ycombinator.com/item?id=12345&token=secret",
                "source": "hacker-news",
            }
        )
        self.assertEqual(clean["url"], "https://news.ycombinator.com/item?id=12345")
        self.assertEqual(clean["comments_url"], "https://news.ycombinator.com/item?id=12345")
        self.assertNotIn("token", repr(clean))


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

    def test_weak_ai_mentions_are_dropped_and_source_extract_is_ranked(self):
        ranked = rank_items(
            [
                {
                    "title": "No AI Fridays",
                    "url": "https://example.test/weak",
                    "source": "hacker-news",
                    "score": 500,
                },
                {
                    "title": "Compiler release notes",
                    "summary": "A new LLM inference compiler reduces GPU memory use.",
                    "url": "https://example.test/strong",
                    "source": "engineering-feed",
                    "score": 2,
                },
            ]
        )

        self.assertEqual([item["url"] for item in ranked], ["https://example.test/strong"])
        self.assertEqual(ranked[0]["category"], "Inference & Infrastructure")
        self.assertIn("GPU memory", ranked[0]["summary"])

    def test_near_duplicate_cross_source_titles_collapse(self):
        ranked = rank_items(
            [
                {
                    "title": "New Claude reasoning model launches for developers",
                    "summary": "The model adds tool use and stronger coding performance.",
                    "url": "https://one.example/story",
                    "source": "first-feed",
                    "score": 20,
                },
                {
                    "title": "Claude reasoning model launches for developers today",
                    "summary": "A second write-up of the same model announcement.",
                    "url": "https://two.example/story",
                    "source": "second-feed",
                    "score": 10,
                },
            ]
        )

        self.assertEqual(len(ranked), 1)

    def test_curated_engineering_source_outranks_social_engagement(self):
        ranked = rank_items(
            [
                {
                    "title": "Show HN: Claude LLM helper",
                    "summary": "A small personal wrapper around an API.",
                    "url": "https://social.example/item",
                    "source": "hacker-news",
                    "score": 900,
                },
                {
                    "title": "LLM inference capacity recovery architecture",
                    "summary": "The engineering design restores serving capacity after GPU failure.",
                    "url": "https://engineering.example/item",
                    "source": "nvidia-technical-blog",
                    "score": 2,
                },
            ]
        )

        self.assertEqual(ranked[0]["source"], "nvidia-technical-blog")

    def test_education_marketing_and_chatty_social_titles_are_rejected(self):
        ranked = rank_items(
            [
                {
                    "title": "Bringing ChatGPT for teachers to more school districts",
                    "summary": "Students and teachers can use AI in education.",
                    "url": "https://example.test/education",
                    "source": "official-feed",
                },
                {
                    "title": "Talk Like Claude Day",
                    "summary": "A social prompt about a language model.",
                    "url": "https://example.test/chatty",
                    "source": "hacker-news",
                },
            ]
        )

        self.assertEqual(ranked, [])

    def test_equally_relevant_stories_sort_newest_first(self):
        ranked = rank_items(
            [
                {
                    "title": "LLM inference runtime alpha",
                    "url": "https://example.test/older",
                    "source": "public-feed",
                    "published_at": "2030-01-01T08:00:00+00:00",
                },
                {
                    "title": "LLM inference runtime beta",
                    "url": "https://example.test/newer",
                    "source": "public-feed",
                    "published_at": "2030-01-02T08:00:00+00:00",
                },
            ]
        )

        self.assertEqual(ranked[0]["url"], "https://example.test/newer")

    def test_company_expansion_without_technical_change_is_rejected(self):
        ranked = rank_items(
            [
                {
                    "title": "Expanding OpenAI presence in a new country",
                    "summary": "The company is opening an office and supporting local startups.",
                    "url": "https://example.test/company-news",
                    "source": "openai",
                }
            ]
        )

        self.assertEqual(ranked, [])


if __name__ == "__main__":
    unittest.main()
