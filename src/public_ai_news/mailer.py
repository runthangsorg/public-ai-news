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


def _compact_extract(value: Any, *, limit: int = 220) -> str:
    """Bound the email extract so rows stay short."""
    clean = " ".join(str(value or "").split()).strip()
    if len(clean) <= limit:
        return clean or "No source extract was available; open the article for details."
    cut = clean[: limit - 1].rsplit(" ", 1)[0] or clean[: limit - 1]
    return cut.rstrip(" ,;:") + "…"


def _link(url: str, label: str) -> str:
    if not url:
        return ""
    return (
        f'<a href="{html.escape(url, quote=True)}" '
        f'style="color:#58a6ff;text-decoration:none;font-size:10px;">{html.escape(label)}</a>'
    )


def _build_html(items: List[Mapping[str, Any]]) -> str:
    """Build a compact, email-safe AI engineering briefing."""
    cards = []
    for index, item in enumerate(items, 1):
        title = html.escape(str(item.get("title") or "Untitled story"))
        url = str(item.get("url") or "")
        comments_url = str(item.get("comments_url") or "")
        source = html.escape(str(item.get("source") or "public-feed"))
        category = html.escape(str(item.get("category") or "AI Engineering"))
        summary = html.escape(_compact_extract(item.get("summary")))
        date = html.escape(_display_date(item.get("published_at")))
        score = html.escape(str(item.get("score") or 0))
        comments = html.escape(str(item.get("comment_count") or 0))
        links = _link(url, "Read")
        discuss = _link(comments_url, "Discuss")
        if links and discuss:
            links = f"{links} · {discuss}"
        elif discuss:
            links = discuss
        cards.append(
            f"""
            <article style="background:#0d1117;border:1px solid #30363d;border-radius:5px;margin:0 0 6px 0;">
              <div style="padding:6px 8px 7px;">
                <div style="color:#8b949e;font-size:9px;margin:0 0 2px 0;">#{index} · {category} · {source} · {date}</div>
                <div style="font-size:12.5px;line-height:1.3;color:#f0f6fc;margin:0 0 2px 0;">{title}</div>
                <div style="color:#c9d1d9;font-size:11px;line-height:1.35;margin:0 0 3px 0;">{summary}</div>
                <div style="color:#8b949e;font-size:9.5px;">★ {score} · 💬 {comments}{' · ' + links if links else ''}</div>
              </div>
            </article>
            """
        )

    body = "".join(cards)
    if not body:
        body = (
            '<div style="background:#0d1117;border:1px solid #30363d;'
            'border-radius:5px;padding:10px;color:#8b949e;font-size:11px;">'
            "No story passed the engineering relevance and evidence gates today."
            "</div>"
        )
    return f"""<!doctype html>
 <html>
 <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
 <body style="background:#010409;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;margin:0;padding:8px 6px;">
   <main style="max-width:680px;margin:0 auto;">
     <header style="border-bottom:1px solid #2f81f7;padding:2px 2px 6px;margin-bottom:8px;">
       <h1 style="color:#f0f6fc;font-size:16px;line-height:1.1;margin:0;">⚡ AI Engineering Brief ({len(items)})</h1>
     </header>
     {body}
     <footer style="border-top:1px solid #30363d;color:#8b949e;font-size:9px;line-height:1.3;margin-top:8px;padding:5px 2px 0;">
       Source extracts only · open the source before relying on details.
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
