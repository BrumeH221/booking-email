# gmail_service.py — same Gmail wrapper as the AI project, but searches a
# wider query (no subject filter — AI decides intent from body).

import base64
import html
import re
from email.mime.text import MIMEText
from email.utils import parseaddr

import config
from backend.auth_service import get_gmail_service


def search_unread_booking_emails(query=None, max_results=None):
    service = get_gmail_service()
    q = query or config.GMAIL_SEARCH_QUERY
    n = max_results or config.MAX_EMAILS_PER_RUN
    return service.users().messages().list(
        userId="me", q=q, maxResults=n,
    ).execute().get("messages", [])


def get_email_detail(message_id):
    service = get_gmail_service()
    message = service.users().messages().get(
        userId="me", id=message_id, format="full",
    ).execute()
    payload = message.get("payload", {})
    headers = payload.get("headers", [])
    subject, sender = "", ""
    for h in headers:
        name = h.get("name", "").lower()
        if name == "subject": subject = h.get("value", "")
        elif name == "from":  sender = h.get("value", "")
    sender_name, sender_email = parseaddr(sender)
    body = _extract_body(payload)
    return {
        "message_id": message_id,
        "thread_id": message.get("threadId"),
        "subject": subject,
        "sender": sender,
        "sender_name": sender_name,
        "sender_email": sender_email,
        "body": body,
    }


def _extract_body(payload):
    plain = _find_mime(payload, "text/plain")
    if plain: return plain
    html_text = _find_mime(payload, "text/html")
    if html_text: return _html_to_text(html_text)
    return ""


def _find_mime(payload, mime_type):
    if payload.get("mimeType") == mime_type:
        data = payload.get("body", {}).get("data")
        if data:
            return _b64dec(data)
    for part in payload.get("parts", []):
        r = _find_mime(part, mime_type)
        if r: return r
    return None


def _b64dec(data):
    pad = len(data) % 4
    if pad: data += "=" * (4 - pad)
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")


def _html_to_text(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def send_email(to, subject, body, thread_id=None):
    service = get_gmail_service()
    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = to
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    payload = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id
    return service.users().messages().send(userId="me", body=payload).execute()


def mark_email_as_read(message_id):
    service = get_gmail_service()
    service.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]},
    ).execute()


if __name__ == "__main__":
    emails = search_unread_booking_emails()
    print(f"Found {len(emails)} unread email(s)")
