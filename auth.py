"""
auth.py
Password hashing + OTP generation/verification + SMS sending.

REAL-TIME SMS:
To send actual SMS on a real phone number, this uses Twilio if credentials
are present as environment variables:

    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_FROM_NUMBER

Without those set, the app runs in DEMO MODE: the OTP is shown directly on
the web page (clearly labeled) instead of being texted, so you can still
demo the full flow with no external account. This is the only part of the
project that cannot be "pure Python simulation" -- an actual SMS requires a
paid telecom gateway (Twilio, MSG91, Fast2SMS, etc). Plug your own account
in and it will start sending real texts with no other code changes.
"""
import os
import random
import string
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash, check_password_hash

from database import get_db, now

OTP_TTL_MINUTES = 5

TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER")

SMS_ENABLED = bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM)


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password, password_hash):
    return check_password_hash(password_hash, password)


def generate_otp():
    return "".join(random.choices(string.digits, k=6))


def create_otp(contact, purpose):
    code = generate_otp()
    expires = (datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO otp_codes (contact, code, purpose, expires_at, used, created_at) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (contact, code, purpose, expires, now()),
    )
    conn.commit()
    conn.close()
    return code


def send_otp_sms(contact, code):
    """Sends via Twilio if configured, otherwise returns demo info for the UI."""
    if SMS_ENABLED and _looks_like_phone(contact):
        try:
            from twilio.rest import Client
            client = Client(TWILIO_SID, TWILIO_TOKEN)
            client.messages.create(
                body=f"Your AgroGuard AI verification code is {code}. "
                     f"It expires in {OTP_TTL_MINUTES} minutes.",
                from_=TWILIO_FROM,
                to=contact,
            )
            return {"sent": True, "channel": "sms", "demo_code": None}
        except Exception as exc:
            return {"sent": False, "channel": "sms", "demo_code": code, "error": str(exc)}

    # Demo mode: no telecom account configured
    return {"sent": False, "channel": "demo", "demo_code": code}


def _looks_like_phone(contact):
    digits = "".join(ch for ch in contact if ch.isdigit())
    return len(digits) >= 8


def verify_otp(contact, code, purpose):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM otp_codes WHERE contact = ? AND purpose = ? "
        "ORDER BY id DESC LIMIT 1",
        (contact, purpose),
    ).fetchone()

    if row is None:
        conn.close()
        return False, "No OTP was requested for this contact."

    if row["used"]:
        conn.close()
        return False, "This OTP has already been used. Request a new one."

    if datetime.utcnow() > datetime.fromisoformat(row["expires_at"]):
        conn.close()
        return False, "OTP expired. Request a new one."

    if row["code"] != code.strip():
        conn.close()
        return False, "Incorrect OTP."

    conn.execute("UPDATE otp_codes SET used = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return True, "OK"
