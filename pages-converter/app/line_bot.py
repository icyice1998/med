"""Minimal LINE Messaging API helpers (no SDK dependency)."""
import base64
import hashlib
import hmac
import os

import httpx

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
CHANNEL_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
API = "https://api.line.me/v2/bot"
DATA_API = "https://api-data.line.me/v2/bot"


def enabled() -> bool:
    return bool(CHANNEL_SECRET and CHANNEL_TOKEN)


def verify_signature(body: bytes, signature: str) -> bool:
    if not CHANNEL_SECRET or not signature:
        return False
    digest = hmac.new(CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def _headers() -> dict:
    return {"Authorization": f"Bearer {CHANNEL_TOKEN}"}


async def download_content(message_id: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{DATA_API}/message/{message_id}/content", headers=_headers())
        r.raise_for_status()
        return r.content


async def reply_or_push(reply_token: str | None, to: str | None, messages: list[dict]) -> None:
    """Reply tokens expire quickly; fall back to push if the reply fails."""
    async with httpx.AsyncClient(timeout=30) as c:
        if reply_token:
            r = await c.post(f"{API}/message/reply", headers=_headers(),
                             json={"replyToken": reply_token, "messages": messages})
            if r.status_code == 200:
                return
        if to:
            await c.post(f"{API}/message/push", headers=_headers(),
                         json={"to": to, "messages": messages})


def text(msg: str, quick_formats: bool = False) -> dict:
    m = {"type": "text", "text": msg}
    if quick_formats:
        m["quickReply"] = {"items": [
            {"type": "action", "action": {"type": "message", "label": "PDF", "text": "pdf"}},
            {"type": "action", "action": {"type": "message", "label": "Word", "text": "word"}},
        ]}
    return m
