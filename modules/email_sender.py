"""
modules/email_sender.py
Brevo REST API integration: send emails and personalise HTML templates.
"""
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

# Default Brevo REST API v3 endpoint for transactional email dispatch
DEFAULT_BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


class EmailSendError(Exception):
    """Raised when Brevo returns a non-2xx status."""
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Brevo API error {status_code}: {body}")


def _get_brevo_config() -> dict:
    return {
        "api_key": os.getenv("BREVO_API_KEY", ""),
        "api_url": os.getenv("BREVO_API_URL", DEFAULT_BREVO_API_URL),
        "sender_email": os.getenv("BREVO_SENDER_EMAIL", ""),
        "sender_name": os.getenv("BREVO_SENDER_NAME", ""),
    }


def send_email_brevo(
    to_email: str,
    to_name: str,
    subject: str,
    html_content: str,
) -> dict:
    """
    Send a single email via the Brevo REST API (HTTP POST).
    Returns the response JSON on success.
    Raises EmailSendError on API failure.
    """
    cfg = _get_brevo_config()
    if not cfg["api_key"]:
        raise EmailSendError(0, "BREVO_API_KEY is not set in .env")

    headers = {
        "api-key": cfg["api_key"],
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "sender": {
            "name": cfg["sender_name"],
            "email": cfg["sender_email"],
        },
        "to": [{"email": to_email, "name": to_name or to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }

    response = requests.post(cfg["api_url"], json=payload, headers=headers, timeout=30)

    if not response.ok:
        raise EmailSendError(response.status_code, response.text)

    try:
        return response.json()
    except Exception:
        return {"status": "ok", "messageId": "unknown"}


def _safe_value(val,key) -> str:
    """
    Convert a row value to a clean string.
    Returns empty string for missing / NaN / None values so that
    templates never show 'nan', 'None', or raw {{placeholder}} text.
    """
    if key.strip().lower() == "owner name":
        return "Sir/Mam"
    if val is None:
        return ""
    # Catch pandas / float NaN without importing pandas here
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return ""
    except Exception:
        pass
    s = str(val).strip()
    # Also treat literal "nan", "none", "null" strings as empty
    
    if s.lower() in ("nan", "none", "null", "n/a", "na"):
        return ""
    return s


def personalise_template(html_content: str, row: dict) -> str:
    """
    Replace {{column_name}} placeholders in the HTML with values from the row dict.
    - If the key exists but the value is NaN / None / empty → replaced with "".
    - If the key does not exist in the row → replaced with "" (not left as {{placeholder}}).
    """
    def replacer(match):
        key = match.group(1).strip()
        if key in row:
            return _safe_value(row[key],key)
        # Key not present in CSV at all — use empty string, not the raw placeholder
        return ""

    return re.sub(r"\{\{(.*?)\}\}", replacer, html_content)


def personalise_subject(subject: str, row: dict) -> str:
    """Replace {{column_name}} placeholders in the subject line."""
    return personalise_template(subject, row)


def extract_and_strip_title(html_content: str) -> tuple:
    """
    Extract the text from the <title> tag and return it along with
    the HTML with the <title> tag removed.

    Returns:
        (title_text, cleaned_html)
        title_text is None if no <title> tag is found.
    """
    pattern = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
    match = pattern.search(html_content)
    if match:
        title_text = match.group(1).strip()
        cleaned_html = pattern.sub("", html_content, count=1)
        return title_text, cleaned_html
    return None, html_content
