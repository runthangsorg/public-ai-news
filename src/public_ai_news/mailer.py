"""Email delivery for news digest."""
import os
import smtplib
from email.message import EmailMessage
from typing import Any, List, Mapping

def _build_html(items: List[Mapping[str, Any]]) -> str:
    """Build a dark-themed HTML digest."""
    items_html = ""
    for i, item in enumerate(items, 1):
        items_html += f"""
        <div style="margin-bottom: 20px; padding: 15px; background-color: #2a2a2a; border-radius: 8px;">
            <h3 style="margin-top: 0; margin-bottom: 10px; font-size: 18px;">
                <a href="{item.get('url', '')}" style="color: #66b3ff; text-decoration: none;">{i}. {item.get('title', 'Unknown')}</a>
            </h3>
            <p style="margin: 0; font-size: 14px; color: #aaaaaa;">
                Score: {item.get('score', 0)} | Relevance: {item.get('relevance', 0)} | Source: {item.get('source', 'unknown')}
            </p>
        </div>
        """
        
    return f"""
    <html>
    <body style="background-color: #1a1a1a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto;">
            <h2 style="color: #ffffff; border-bottom: 1px solid #444; padding-bottom: 10px;">AI News Digest</h2>
            {items_html if items_html else "<p>No relevant news found today.</p>"}
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
    msg.set_content("Please view this email in an HTML-compatible client.")
    msg.add_alternative(html_content, subtype="html")
    
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
