import unittest

from public_ai_news.mailer import _build_html


class DigestQualityTests(unittest.TestCase):
    def test_digest_has_source_extract_date_category_and_deep_actions(self):
        rendered = _build_html(
            [
                {
                    "title": "New & capable model",
                    "url": "https://example.test/article",
                    "comments_url": "https://news.ycombinator.com/item?id=1",
                    "source": "example-feed",
                    "published_at": "2030-01-02T08:00:00+00:00",
                    "summary": "A verified source extract about the release.",
                    "category": "Models & Releases",
                    "score": 20,
                    "comment_count": 4,
                    "relevance": 12,
                }
            ]
        )

        self.assertIn("Models &amp; Releases", rendered)
        self.assertIn("Source extract", rendered)
        self.assertIn("verified source extract", rendered)
        self.assertIn("Read source", rendered)
        self.assertIn("HN discussion", rendered)
        self.assertIn("02 Jan 2030", rendered)
        self.assertNotIn("New & capable", rendered)
        self.assertIn("New &amp; capable", rendered)


if __name__ == "__main__":
    unittest.main()
