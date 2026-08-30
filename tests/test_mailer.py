import contextlib
import io
import os
import unittest
from unittest.mock import patch

from public_ai_news.mailer import MailConfigError, _build_html, send_digest


class MailerTests(unittest.TestCase):
    def test_external_fields_are_html_escaped(self):
        rendered = _build_html(
            [
                {
                    "title": '<img src=x onerror="alert(1)"> AI model',
                    "url": 'https://example.test/story?x="unsafe"',
                    "source": "public<feed>",
                    "score": 4,
                    "relevance": 8,
                }
            ]
        )

        self.assertNotIn("<img src=x", rendered)
        self.assertNotIn('x="unsafe"', rendered)
        self.assertIn("&lt;img src=x", rendered)
        self.assertIn("public&lt;feed&gt;", rendered)

    def test_dry_run_never_prints_recipient_or_report(self):
        output = io.StringIO()
        with patch.dict(
            os.environ,
            {"REPORT_RECIPIENT": "private@example.test"},
            clear=True,
        ), contextlib.redirect_stdout(output):
            sent = send_digest(
                [{"title": "Private selection", "url": "https://example.test"}],
                dry_run=True,
            )

        self.assertFalse(sent)
        self.assertEqual(output.getvalue(), "")

    def test_live_delivery_fails_closed_when_credentials_are_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MailConfigError):
                send_digest([], dry_run=False)


if __name__ == "__main__":
    unittest.main()
