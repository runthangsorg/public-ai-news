"""Email delivery for news digest."""
import os
import smtplib
from email.message import EmailMessage
from typing import Any, List, Mapping

def _build_html(items: List[Mapping[str, Any]]) -> str:
    """Build a dark-themed, email-safe HTML digest."""
    items_html = ""
    for i, item in enumerate(items, 1):
        score = item.get("score", 0)
        relevance = item.get("relevance", 0)
        source = item.get("source", "unknown")
        url = item.get("url", "")
        title = item.get("title", "Unknown")

        items_html += f"""
        <div style="margin-bottom: 16px; padding: 18px; background-color: #1a2332; border: 1px solid #2a3a50; border-radius: 12px;">
            <div style="margin-bottom: 8px;">
                <span style="display: inline-block; background-color: #0284c7; color: #ffffff; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; margin-right: 6px;">#{i}</span>
                <span style="display: inline-block; background-color: #1e3a5f; color: #7dd3fc; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; margin-right: 6px;">{source}</span>
                <span style="display: inline-block; background-color: #14432a; color: #6ee7b7; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px;">Score {score}</span>
            </div>
            <h3 style="margin: 0 0 10px 0; font-size: 17px; line-height: 1.4;">
                <a href="{url}" style="color: #38bdf8; text-decoration: none; font-weight: 600;">{title}</a>
            </h3>
            <div style="font-size: 12px; color: #94a3b8;">
                Relevance: {relevance} pts · <a href="{url}" style="color: #64748b; text-decoration: underline;">Read article →</a>
            </div>
        </div>
        """
        
    return f"""<!doctype html>
    <html>
    <body style="background-color: #0b111e; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; padding: 24px; margin: 0;">
        <div style="max-width: 680px; margin: 0 auto;">
            <div style="border-bottom: 1px solid #1e293b; padding-bottom: 16px; margin-bottom: 24px;">
                <h1 style="color: #f8fafc; font-size: 24px; margin: 0 0 6px 0;">⚡ AI News Digest</h1>
                <p style="color: #94a3b8; font-size: 13px; margin: 0;">Curated high-signal engineering & research developments</p>
            </div>
            {items_html if items_html else "<p style='color: #94a3b8;'>No relevant news found today.</p>"}
            <footer style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #1e293b; color: #64748b; font-size: 12px;">
                Automated digest generated from curated public sources.
            </footer>
        </div>
    </body>
    </html>
    """

def send_digest(items: List[Mapping[str, Any]], dry_run: bool = False) -> None:
    """Send the HTML digest via SMTP."""
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    recipient = os.environ.get("REPORT_RECIPIENT")
    
    html_content = _build_html(items)
    text_content = "AI News Digest\n\n" + "\n\n".join(
        f"{i}. {item.get('title', 'Unknown')}\n   {item.get('url', '')}\n   Score: {item.get('score', 0)} | Relevance: {item.get('relevance', 0)} | Source: {item.get('source', 'unknown')}"
        for i, item in enumerate(items, 1)
    )
    
    if dry_run:
        print("--- DRY RUN: Would send email ---")
        print(f"Recipient: {recipient}")
        print(html_content)
        return
        
    if not all([host, port, user, password, recipient]):
        print("Warning: Missing SMTP credentials. Skipping email delivery.")
        return
        
    msg = EmailMessage()
    msg["Subject"] = f"AI News Digest ({len(items)} items)"
    msg["From"] = user
    msg["To"] = recipient
    msg.set_content(text_content)
    msg.add_alternative(html_content, subtype="html")
    
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
