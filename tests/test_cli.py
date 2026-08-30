import contextlib
import io
import json
import unittest
from unittest.mock import patch

from public_ai_news.cli import main


class CliTests(unittest.TestCase):
    def test_config_run_logs_counts_only(self):
        item = {
            "title": "Secret-derived AI selection",
            "url": "https://example.test/private-choice",
            "source": "public-feed",
            "score": 5,
            "relevance": 8,
        }
        output = io.StringIO()
        with patch("public_ai_news.cli.fetch_from_config", return_value=[item]), patch(
            "public_ai_news.cli.rank_items", return_value=[item]
        ), patch("public_ai_news.cli.send_digest", return_value=False), contextlib.redirect_stdout(output):
            result = main(["--config", "--max-items", "15", "--dry-run"])

        payload = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload, {"dry_run": True, "email_sent": False, "item_count": 1})
        self.assertNotIn(item["title"], output.getvalue())
        self.assertNotIn(item["url"], output.getvalue())


if __name__ == "__main__":
    unittest.main()
