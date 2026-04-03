"""
Speed-to-Lead: Facebook Messenger Webhook
==========================================
Receives Facebook Messenger messages via the Meta Webhooks API, detects
lead keywords, and instantly notifies the business owner via Email + Telegram.
Always sends a professional auto-reply to the customer on Messenger.

Converted from line_lead_bot.py — LINE SDK replaced with Meta Graph API calls.
The lead-triage brain, email/Telegram notification stack, and Google Sheets
stub are all preserved unchanged.

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
from fastapi.responses import PlainTextResponse

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fb_lead_bot")

# ---------------------------------------------------------------------------
# Config — required secrets fail fast at startup (KeyError), not mid-request
# ---------------------------------------------------------------------------
FB_PAGE_ACCESS_TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
FB_VERIFY_TOKEN = os.environ["FB_VERIFY_TOKEN"]

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
ALERT_EMAIL_TO = os.environ["ALERT_EMAIL_TO"]

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Meta Send API endpoint
FB_SEND_API_URL = "https://graph.facebook.com/v20.0/me/messages"

# ---------------------------------------------------------------------------
# Lead keyword detection  (unchanged from LINE version)
# ---------------------------------------------------------------------------
LEAD_KEYWORDS: frozenset[str] = frozenset({
    "price", "pricing", "cost", "costs", "quote", "booking", "book",
    "available", "availability", "location", "address", "appointment",
    "hours", "open", "menu", "order", "interested", "buy", "purchase",
    "reserve", "reservation", "rate", "rates", "package", "packages",
    "schedule", "delivery", "inquiry", "enquiry", "info", "information",
    "service", "services", "deal", "deals", "offer", "offers",
})

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
# Notifications  (unchanged from LINE version)
# ---------------------------------------------------------------------------

def _build_email_body(sender_id: str, message_text: str, timestamp: str) -> str:
    return (
        f"🔥 NEW LEAD DETECTED\n"
        f"{'─' * 40}\n"
        f"Time        : {timestamp}\n"
        f"FB Sender   : {sender_id}\n"
        f"Message     : {message_text}\n"
        f"{'─' * 40}\n"
        f"Log in to your Facebook Page Inbox to reply directly.\n"
    )


def _send_email_sync(sender_id: str, message_text: str, timestamp: str) -> None:
    """Blocking SMTP send — called via run_in_executor to stay async-safe."""
    subject = f"[LEAD] New inquiry from Messenger — {timestamp}"
    body = _build_email_body(sender_id, message_text, timestamp)

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
        else:  # 587 STARTTLS
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
        logger.info("Email alert sent to %s", ALERT_EMAIL_TO)
    except Exception:
        logger.exception("Failed to send email alert")
        raise


async def send_email_alert(sender_id: str, message_text: str, timestamp: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_email_sync, sender_id, message_text, timestamp)


async def send_telegram_alert(sender_id: str, message_text: str, timestamp: str) -> None:
    text = (
        f"🔥 *NEW LEAD*\n\n"
        f"*Time:* {timestamp}\n"
        f"*FB Sender:* `{sender_id}`\n"
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


async def notify_owner(sender_id: str, message_text: str, timestamp: str) -> None:
    """Fire email + Telegram concurrently. A failure in one won't block the other."""
    await asyncio.gather(
        send_email_alert(sender_id, message_text, timestamp),
        send_telegram_alert(sender_id, message_text, timestamp),
        return_exceptions=True,
    )


# ---------------------------------------------------------------------------
# Google Sheets stub  (unchanged from LINE version)
# ---------------------------------------------------------------------------

async def log_to_sheets(sender_id: str, message_text: str, timestamp: str) -> None:
    """
    TODO: Log every lead to a Google Sheet.

    Steps to activate:
      1.  pip install gspread google-auth  (add to requirements_fb.txt)
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
          sheet.append_row([timestamp, sender_id, message_text])
    """
    pass


# ---------------------------------------------------------------------------
# Facebook Messenger helpers
# ---------------------------------------------------------------------------

async def send_messenger_reply(recipient_id: str, text: str) -> None:
    """POST a text reply to the Meta Send API."""
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "messaging_type": "RESPONSE",
    }
    params = {"access_token": FB_PAGE_ACCESS_TOKEN}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(FB_SEND_API_URL, json=payload, params=params)
            resp.raise_for_status()
        logger.info("Messenger reply sent to %s", recipient_id)
    except Exception:
        logger.exception("Failed to send Messenger reply to %s", recipient_id)
        raise


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="FB Messenger Speed-to-Lead Bot", version="1.0.0")

AUTO_REPLY_TEXT = (
    "Hi! We've received your inquiry. "
    "Our team has been alerted and will get back to you personally within 10 minutes."
)


@app.get("/webhook")
async def verify_webhook(request: Request) -> PlainTextResponse:
    """
    Meta Webhook Verification (one-time setup).
    Meta sends a GET with hub.mode, hub.verify_token, and hub.challenge.
    Return the challenge as plain text to confirm ownership of the endpoint.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == FB_VERIFY_TOKEN:
        logger.info("Webhook verified by Meta")
        return PlainTextResponse(content=challenge, status_code=200)

    logger.warning("Webhook verification failed — token mismatch or wrong mode")
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    """
    Main Messenger webhook endpoint.
    Meta sends a POST for each messaging event in this shape:
    {
      "object": "page",
      "entry": [
        {
          "id": "<PAGE_ID>",
          "time": 1234567890,
          "messaging": [
            {
              "sender":    {"id": "<PSID>"},
              "recipient": {"id": "<PAGE_ID>"},
              "timestamp": 1234567890,
              "message":   {"mid": "...", "text": "Hello!"}
            }
          ]
        }
      ]
    }
    """
    body = await request.json()

    # Meta always sets object="page" for Page subscriptions
    if body.get("object") != "page":
        raise HTTPException(status_code=400, detail="Unexpected object type")

    for entry in body.get("entry", []):
        for event in entry.get("messaging", []):
            # Skip delivery confirmations, read receipts, postbacks, etc.
            message = event.get("message")
            if not message:
                continue

            # Skip echo events (messages sent by the page itself)
            if message.get("is_echo"):
                continue

            text: str | None = message.get("text")
            if not text:
                # Non-text message (image, sticker, etc.) — still auto-reply
                text = ""

            sender_id: str = event["sender"]["id"]
            timestamp: str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            logger.info("Message from %s: %r", sender_id, text)

            if text and is_lead_message(text):
                logger.info("Lead detected from %s — notifying owner", sender_id)
                await asyncio.gather(
                    notify_owner(sender_id, text, timestamp),
                    log_to_sheets(sender_id, text, timestamp),
                    return_exceptions=True,
                )

            # Always send auto-reply (even for non-text / non-lead messages)
            await send_messenger_reply(sender_id, AUTO_REPLY_TEXT)

    # Meta expects a 200 OK quickly — always return it
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict:
    """Liveness probe for Render.com health checks."""
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Local development entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("fb_lead_bot:app", host="0.0.0.0", port=8000, reload=True)
