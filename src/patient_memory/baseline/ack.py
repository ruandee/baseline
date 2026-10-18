"""KAZE acknowledgement tokens and the public acknowledgement page (BL-27, decisions 018 and 023).

A token is 32 random bytes (`secrets.token_urlsafe(32)`, 256 bits), minted once per SMS escalation
row, so it is scoped to exactly one session, episode, ladder level and contact. Only its SHA-256 is
stored. `pm_acknowledge_escalation(hash)` checks expiry, episode and session state under row locks
and answers only `acknowledged`, `recorded` or `invalid`; a replay of a used token is `recorded`
and changes nothing.

`GET /ack/{token}` records acknowledgement and returns a minimal result page, per the
specified KAZE contract. POST is equivalent. No page names a person, contact or session.
"""
import hashlib
import html
import re
import secrets
from dataclasses import dataclass

import psycopg

TOKEN_BYTES = 32
# token_urlsafe(32) is exactly 43 base64url characters with no padding.
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
RESULTS = ("acknowledged", "recorded", "invalid")


@dataclass(frozen=True)
class AckToken:
    token: str
    digest: bytes


def new_token() -> AckToken:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return AckToken(token, token_hash(token))


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def well_formed(token: str) -> bool:
    return bool(TOKEN_PATTERN.fullmatch(token))


def ack_link(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/ack/{token}"


def acknowledge(cfg, token: str) -> str:
    """Record a tap. The route has no bearer identity, so this is a bare runtime-role connection
    with no tenant set: RLS hides every row and only the SECURITY DEFINER function can act."""
    if not well_formed(token):
        return "invalid"
    with psycopg.connect(cfg.database_url, connect_timeout=5) as conn:
        conn.execute("SET LOCAL statement_timeout='5s'")
        result = conn.execute("SELECT pm_acknowledge_escalation(%s)",
                              (token_hash(token),)).fetchone()[0]
    return result if result in RESULTS else "invalid"


# A page with no script, style, image or external resource; the only form posts to itself.
HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
    "Content-Security-Policy": ("default-src 'none'; form-action 'self'; frame-ancestors 'none'; "
                                "base-uri 'none'"),
}

PAGES = {
    "confirm": ("Check-in request",
                "Someone asked you to check on them. Tap the button to let us know you are "
                "following up. This does not contact them or anyone else for you.", True),
    "acknowledged": ("Thank you",
                     "You are marked as following up, so no more texts will go out for this "
                     "alert. Please keep trying to reach them. If you can't reach them "
                     "and you are worried, call 911.", False),
    "recorded": ("Thank you",
                 "Your response was recorded. Please keep trying to reach them. If you can't "
                 "reach them and you are worried, call 911.", False),
    "invalid": ("Link not active",
                "This link has expired or is no longer active. If you are worried about "
                "someone, try to reach them directly, or call 911 in an emergency.", False),
    "unavailable": ("Please try again",
                    "We couldn't record that just now. Please try again in a moment, and keep "
                    "trying to reach them directly.", True),
}


def page(kind: str) -> str:
    title, text, button = PAGES[kind]
    form = ('<form method="post"><button type="submit">I\'m on it</button></form>'
            if button else "")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex, nofollow\">"
            f"<title>{html.escape(title)}</title></head><body><main>"
            f"<h1>{html.escape(title)}</h1><p>{html.escape(text)}</p>{form}"
            "</main></body></html>")
