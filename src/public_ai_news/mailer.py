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


def _compact_extract(value: Any, *, limit: int = 170) -> str:
    """Bound the email extract so rows stay short."""
    import re

    clean = " ".join(str(value or "").split()).strip()
    if not clean:
        return "No source extract was available; open the article for details."
    cjk = len(
        re.findall(
            "[\u2e80-\u2eff\u3000-\u303f\u3040-\u30ff\u3100-\u312f\u3200-\u32ff"
            "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]",
            clean,
        )
    )
    if len(clean) > 20 and cjk / len(clean) > 0.3:
        return "No English extract available — open the source for details."
    if len(clean) <= limit:
        return clean
    cut = clean[: limit - 1].rsplit(" ", 1)[0] or clean[: limit - 1]
    return cut.rstrip(" ,;:") + "…"


def _meta(item: Mapping[str, Any]) -> dict:
    # NOTE: categories are uppercased via CSS (text-transform), never by
    # upper()-ing escaped HTML (which corrupts entities like &amp;).
    return {
        "title": html.escape(str(item.get("title") or "Untitled story")),
        "url": str(item.get("url") or ""),
        "comments_url": str(item.get("comments_url") or ""),
        "source": html.escape(str(item.get("source") or "public-feed")),
        "category": html.escape(str(item.get("category") or "AI Engineering")),
        "summary": html.escape(_compact_extract(item.get("summary"))),
        "date": html.escape(_display_date(item.get("published_at"))),
        "score": html.escape(str(item.get("score") or 0)),
        "comments": html.escape(str(item.get("comment_count") or 0)),
    }


def _title_link(meta: dict) -> str:
    if not meta["url"]:
        return meta["title"]
    return (
        f'<a href="{html.escape(meta["url"], quote=True)}" '
        f'style="color:#58a6ff;text-decoration:none;">{meta["title"]}</a>'
    )


def _action_links(meta: dict) -> str:
    parts = []
    if meta["url"]:
        parts.append(
            f'<a href="{html.escape(meta["url"], quote=True)}" '
            f'style="color:#0b57d0;text-decoration:none;">Read →</a>'
        )
    if meta["comments_url"]:
        parts.append(
            f'<a href="{html.escape(meta["comments_url"], quote=True)}" '
            f'style="color:#0b57d0;text-decoration:none;">Discuss</a>'
        )
    return " · ".join(parts)


def _row(index: int, meta: dict) -> str:
    links = _action_links(meta)
    links_html = f" · {links}" if links else ""
    return (
        f'<tr><td style="padding:9px 14px;border-bottom:1px solid #21262d;">'
        f'<div style="font-size:10px;color:#8b949e;margin:0 0 2px 0;">'
        f"#{index} · "
        f'<span style="text-transform:uppercase;letter-spacing:.3px;">{meta["category"]}</span>'
        f" · {meta['source']} · {meta['date']}</div>"
        f'<div style="font-size:14.5px;line-height:1.35;font-weight:700;color:#f0f6fc;margin:0 0 2px 0;">'
        f"{_title_link(meta)}</div>"
        f'<div style="font-size:12.5px;line-height:1.45;color:#c9d1d9;margin:0 0 4px 0;">'
        f"{meta['summary']}</div>"
        f'<div style="font-size:10.5px;color:#8b949e;">'
        f"★ {meta['score']} · 💬 {meta['comments']}{links_html}</div>"
        f"</td></tr>"
    )


def _build_html(items: List[Mapping[str, Any]]) -> str:
    """Build a light, scannable, email-safe AI engineering briefing."""
    today = datetime.now().strftime("%d %b %Y")
    if not items:
        body = (
            '<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;'
            'padding:14px;color:#8b949e;font-size:13px;">'
            "No story passed the engineering relevance and evidence gates today."
            "</div>"
        )
        table = body
    else:
        top = list(items[:5])
        top_rows = []
        for rank, raw in enumerate(top, 1):
            meta = _meta(raw)
            top_rows.append(
                f'<div style="padding:5px 0;border-bottom:1px solid #21262d;">'
                f'<span style="color:#f0883e;font-weight:700;">{rank}.</span> '
                f'<span style="font-size:13.5px;font-weight:600;color:#f0f6fc;">{_title_link(meta)}</span><br>'
                f'<span style="font-size:10.5px;color:#8b949e;">{meta["source"]} · '
                f"★ {meta['score']} · 💬 {meta['comments']}</span>"
                f"</div>"
            )
        top_box = (
            '<div style="background:#161b22;border:1px solid #f0883e;border-radius:8px;'
            'padding:10px 14px;margin:0 0 12px 0;">'
            '<div style="font-size:11px;font-weight:700;letter-spacing:.4px;color:#f0883e;'
            'margin-bottom:4px;">🔥 TOP 5 TODAY</div>' + "".join(top_rows) + "</div>"
        )
        rows = "".join(_row(index, _meta(raw)) for index, raw in enumerate(items, 1))
        table = (
            top_box
            + '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'width="100%" style="background:#0d1117;border:1px solid #30363d;'
            'border-radius:8px;border-collapse:collapse;">'
            + rows
            + "</table>"
        )
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="background:#010409;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;margin:0;padding:12px 8px;">
  <main style="max-width:640px;margin:0 auto;">
    <header style="padding:2px 2px 8px;margin-bottom:10px;">
      <h1 style="color:#f0f6fc;font-size:19px;line-height:1.2;margin:0;">⚡ AI Engineering Brief ({len(items)})</h1>
      <div style="color:#8b949e;font-size:11px;margin-top:3px;">{today} · ranked by usefulness (relevance × social) — open the source before relying on details.</div>
    </header>
    {table}
    <footer style="color:#8b949e;font-size:9.5px;line-height:1.4;margin-top:10px;padding:4px 2px 0;">
      Source extracts only, not model-written claims. Scores are directional.
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
    top = list(items[:5])
    if top:
        text_lines.append("TOP 5 TODAY:")
        for rank, pick in enumerate(top, 1):
            text_lines.append(f"  {rank}. {pick.get('title', 'Untitled story')}")
            text_lines.append(f"     Read: {pick.get('url', '')}")
        text_lines.append("")
    for index, item in enumerate(items, 1):
        text_lines.extend(
            [
                f"{index}. {item.get('title', 'Untitled story')}",
                f"   [{item.get('category', 'AI Engineering')}] "
                f"{item.get('source', 'public-feed')} · {_display_date(item.get('published_at'))} "
                f"· score {item.get('score', 0)} · comments {item.get('comment_count', 0)}",
                f"   {_compact_extract(item.get('summary'))}",
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
