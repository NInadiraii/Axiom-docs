"""
Speed-to-Lead: LINE Messaging API Webhook
==========================================
Receives LINE messages, detects lead keywords, and instantly notifies the
business owner via Email + Telegram. Always sends an auto-reply on LINE.

Extend this file by filling in log_to_sheets() when you're ready to add
Google Sheets logging.

Deployment: Render.com (see render.yaml / Procfile)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("line_lead_bot")

# ---------------------------------------------------------------------------
# Config — required secrets fail fast at startup (KeyError), not mid-request
# ---------------------------------------------------------------------------
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
ALERT_EMAIL_TO = os.environ["ALERT_EMAIL_TO"]

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ---------------------------------------------------------------------------
# LINE SDK initialisation
# ---------------------------------------------------------------------------
parser = WebhookParser(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

# ---------------------------------------------------------------------------
# Lead keyword detection
# ---------------------------------------------------------------------------
LEAD_KEYWORDS: frozenset[str] = frozenset({
    "price", "pricing", "cost", "costs", "quote", "booking", "book",
    "available", "availability", "location", "address", "appointment",
    "hours", "open", "menu", "order", "interested", "buy", "purchase",
    "reserve", "reservation", "rate", "rates", "package", "packages",
    "schedule", "delivery", "inquiry", "enquiry", "info", "information",
    "service", "services", "deal", "deals", "offer", "offers",
})

# Multi-word phrases checked separately (can't be caught by word-split)
LEAD_PHRASES: tuple[str, ...] = (
    "how much",
    "how many",
    "do you have",
    "can i",
    "i want",
    "i need",
    "sign up",
    "sign me up",
    "get started",
)


def is_lead_message(text: str) -> bool:
    """Return True if the message text contains a lead-intent keyword."""
    lower = text.lower()
    words = set(re.findall(r"[a-z]+", lower))
    if words & LEAD_KEYWORDS:
        return True
    return any(phrase in lower for phrase in LEAD_PHRASES)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def _build_email_body(user_id: str, message_text: str, timestamp: str) -> str:
    return (
        f"🔥 NEW LEAD DETECTED\n"
        f"{'─' * 40}\n"
        f"Time      : {timestamp}\n"
        f"LINE User : {user_id}\n"
        f"Message   : {message_text}\n"
        f"{'─' * 40}\n"
        f"Log in to your LINE Official Account Manager to reply directly.\n"
    )


def _send_email_sync(user_id: str, message_text: str, timestamp: str) -> None:
    """Blocking SMTP send — called via run_in_executor to stay async-safe."""
    subject = f"[LEAD] New inquiry from LINE — {timestamp}"
    body = _build_email_body(user_id, message_text, timestamp)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL_TO
    msg.attach(MIMEText(body, "plain"))

    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
        else:  # 587 STARTTLS or other
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
        logger.info("Email alert sent to %s", ALERT_EMAIL_TO)
    except Exception:
        logger.exception("Failed to send email alert")
        raise


async def send_email_alert(user_id: str, message_text: str, timestamp: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_email_sync, user_id, message_text, timestamp)


async def send_telegram_alert(user_id: str, message_text: str, timestamp: str) -> None:
    text = (
        f"🔥 *NEW LEAD*\n\n"
        f"*Time:* {timestamp}\n"
        f"*LINE User:* `{user_id}`\n"
        f"*Message:* {message_text}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        logger.info("Telegram alert sent to chat %s", TELEGRAM_CHAT_ID)
    except Exception:
        logger.exception("Failed to send Telegram alert")
        raise


async def notify_owner(user_id: str, message_text: str, timestamp: str) -> None:
    """Fire email + Telegram concurrently. A failure in one won't block the other."""
    await asyncio.gather(
        send_email_alert(user_id, message_text, timestamp),
        send_telegram_alert(user_id, message_text, timestamp),
        return_exceptions=True,  # Notification failure must NEVER block the LINE auto-reply
    )


# ---------------------------------------------------------------------------
# Google Sheets stub — fill this in when ready
# ---------------------------------------------------------------------------

async def log_to_sheets(user_id: str, message_text: str, timestamp: str) -> None:
    """
    TODO: Log every lead to a Google Sheet.

    Steps to activate:
      1.  pip install gspread google-auth  (add to requirements_line.txt)
      2.  Create a Google Cloud service account and download the JSON key.
      3.  Share your target Google Sheet with the service account email.
      4.  Add GOOGLE_SHEETS_CREDS_JSON and GOOGLE_SHEET_ID to your .env.
      5.  Replace the pass below with:

          import gspread
          from google.oauth2.service_account import Credentials
          import json

          creds_dict = json.loads(os.environ["GOOGLE_SHEETS_CREDS_JSON"])
          creds = Credentials.from_service_account_info(
              creds_dict,
              scopes=["https://spreadsheets.google.com/feeds",
                      "https://www.googleapis.com/auth/drive"],
          )
          gc = gspread.authorize(creds)
          sheet = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"]).sheet1
          sheet.append_row([timestamp, user_id, message_text])
    """
    pass  # No-op until Google Sheets integration is added


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="LINE Speed-to-Lead Bot", version="1.0.0")

AUTO_REPLY_TEXT = (
    "Hi! We've received your inquiry. "
    "Our team has been alerted and will get back to you personally within 10 minutes."
)


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    """Main LINE webhook endpoint. Handles signature verification and lead triage."""
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()

    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        logger.warning("Rejected request with invalid LINE signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        if not isinstance(event.message, TextMessageContent):
            continue

        text: str = event.message.text
        user_id: str = event.source.user_id
        timestamp: str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        logger.info("Message from %s: %r", user_id, text)

        if is_lead_message(text):
            logger.info("Lead detected from %s — notifying owner", user_id)
            await asyncio.gather(
                notify_owner(user_id, text, timestamp),
                log_to_sheets(user_id, text, timestamp),
                return_exceptions=True,
            )

        # Always send an auto-reply — even for non-leads (professional experience)
        async with AsyncApiClient(configuration) as api_client:
            line_api = AsyncMessagingApi(api_client)
            await line_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=AUTO_REPLY_TEXT)],
                )
            )

    return {"status": "ok"}


@app.get("/health")
async def health() -> dict:
    """Liveness probe for Render.com health checks."""
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Local development entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("line_lead_bot:app", host="0.0.0.0", port=8000, reload=True)
