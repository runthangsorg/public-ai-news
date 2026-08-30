"""Email delivery for a rich news digest without leaking runtime data to logs."""

from datetime import datetime
from email.message import EmailMessage
import html
import os
import smtplib
import ssl
from typing import Any, List, Mapping


class MailConfigError(RuntimeError):
    """Raised when a live delivery cannot be configured safely."""


def _display_date(value: Any) -> str:
    raw = str(value or "")
    if not raw:
        return "Date unavailable"
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return "Date unavailable"


def _button(url: str, label: str, *, secondary: bool = False) -> str:
    if not url:
        return ""
    background = "#21262d" if secondary else "#238636"
    color = "#f0f6fc"
    return (
        f'<a href="{html.escape(url, quote=True)}" '
        f'style="display:inline-block;background-color:{background};color:{color};'
        'text-decoration:none;font-weight:700;font-size:13px;padding:10px 15px;'
        f'border-radius:7px;margin:8px 8px 0 0;">{html.escape(label)}</a>'
    )


def _build_html(items: List[Mapping[str, Any]]) -> str:
    """Build an email-safe, evidence-labelled AI engineering briefing."""
    cards = []
    for index, item in enumerate(items, 1):
        title = html.escape(str(item.get("title") or "Untitled story"))
        url = str(item.get("url") or "")
        comments_url = str(item.get("comments_url") or "")
        source = html.escape(str(item.get("source") or "public-feed"))
        category = html.escape(str(item.get("category") or "AI Engineering"))
        summary = html.escape(
            str(item.get("summary") or "No source extract was available; open the article for details.")
        )
        date = html.escape(_display_date(item.get("published_at")))
        score = html.escape(str(item.get("score") or 0))
        comments = html.escape(str(item.get("comment_count") or 0))
        relevance = html.escape(str(item.get("relevance") or 0))
        actions = _button(url, "Read source")
        actions += _button(comments_url, "HN discussion", secondary=True)
        cards.append(
            f"""
            <article style="background-color:#0d1117;border:1px solid #30363d;border-radius:12px;margin:0 0 18px 0;overflow:hidden;">
              <div style="background-color:#161b22;border-bottom:1px solid #30363d;padding:11px 18px;">
                <span style="display:inline-block;background-color:#1f6feb;color:#ffffff;border-radius:20px;padding:3px 9px;font-size:11px;font-weight:800;margin-right:6px;">#{index}</span>
                <span style="display:inline-block;background-color:#1f3d2b;color:#7ee787;border-radius:20px;padding:3px 9px;font-size:11px;font-weight:700;margin-right:6px;">{category}</span>
                <span style="color:#8b949e;font-size:12px;">{source} · {date}</span>
              </div>
              <div style="padding:18px 20px 20px;">
                <h2 style="font-size:19px;line-height:1.4;color:#f0f6fc;margin:0 0 13px 0;">{title}</h2>
                <div style="background-color:#161b22;border-left:4px solid #58a6ff;border-radius:6px;padding:12px 14px;margin:0 0 12px 0;">
                  <div style="color:#79c0ff;font-size:11px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;margin-bottom:6px;">Source extract</div>
                  <p style="color:#c9d1d9;font-size:14px;line-height:1.55;margin:0;">{summary}</p>
                </div>
                <div style="color:#8b949e;font-size:12px;margin-top:10px;">Signal {relevance} · Source score {score} · {comments} comments</div>
                <div style="margin-top:8px;">{actions}</div>
              </div>
            </article>
            """
        )

    body = "".join(cards)
    if not body:
        body = (
            '<div style="background-color:#0d1117;border:1px solid #30363d;'
            'border-radius:12px;padding:22px;color:#8b949e;">'
            "No story passed the engineering relevance and evidence gates today."
            "</div>"
        )
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="background-color:#010409;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;margin:0;padding:24px 12px;">
  <main style="max-width:760px;margin:0 auto;">
    <header style="border-bottom:3px solid #2f81f7;padding:8px 4px 18px;margin-bottom:22px;">
      <h1 style="color:#f0f6fc;font-size:28px;line-height:1.2;margin:0 0 7px 0;">⚡ AI Engineering Brief</h1>
      <p style="color:#8b949e;font-size:14px;line-height:1.5;margin:0;">{len(items)} deduplicated developments · source extracts only · direct article links</p>
    </header>
    {body}
    <footer style="border-top:1px solid #30363d;color:#8b949e;font-size:12px;line-height:1.5;margin-top:28px;padding:16px 4px 0;">
      Summaries are bounded extracts from public source metadata, not model-written claims. Open the source before relying on technical details.
    </footer>
  </main>
</body>
</html>"""


def send_digest(items: List[Mapping[str, Any]], dry_run: bool = False) -> bool:
    """Send the HTML digest via SMTP; dry-run performs no delivery or logging."""
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    recipient = os.environ.get("REPORT_RECIPIENT")

    if dry_run:
        return False
    if not all([host, port, user, password, recipient]):
        raise MailConfigError("SMTP delivery configuration is incomplete")

    html_content = _build_html(items)
    text_lines = ["AI Engineering Brief", ""]
    for index, item in enumerate(items, 1):
        text_lines.extend(
            [
                f"{index}. {item.get('title', 'Untitled story')}",
                f"   {item.get('source', 'public-feed')} · {_display_date(item.get('published_at'))}",
                f"   Source extract: {item.get('summary') or 'No source extract available.'}",
                f"   Read: {item.get('url', '')}",
            ]
        )
        if item.get("comments_url"):
            text_lines.append(f"   Discussion: {item['comments_url']}")
        text_lines.append("")

    message = EmailMessage()
    message["Subject"] = f"AI Engineering Brief ({len(items)} stories)"
    message["From"] = user
    message["To"] = recipient
    message.set_content("\n".join(text_lines))
    message.add_alternative(html_content, subtype="html")
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(user, password)
        server.send_message(message)
    return True
