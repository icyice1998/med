"""Pages -> PDF/Word web service with a LINE bot webhook."""
import asyncio
import json
import os
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from . import line_bot
from .converter import ConversionError, convert_pages, normalize_format

MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
API_KEY = os.getenv("API_KEY", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
FILE_TTL = int(os.getenv("FILE_TTL_MINUTES", "60")) * 60
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/tmp/pages-converter-out"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MEDIA = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

app = FastAPI(title="Pages Converter")
_lock = asyncio.Semaphore(int(os.getenv("MAX_PARALLEL", "2")))
_user_format: dict[str, str] = {}  # LINE userId -> "pdf" | "docx"


async def _convert(data: bytes, name: str, fmt: str) -> tuple[bytes, str]:
    if len(data) > MAX_MB * 1024 * 1024:
        raise ConversionError(f"File too large (limit {MAX_MB} MB).")
    async with _lock:
        return await asyncio.to_thread(convert_pages, data, name, fmt)


def _store(data: bytes, name: str) -> str:
    """Save output under a random token; return its public path."""
    _cleanup()
    token = secrets.token_urlsafe(16)
    d = OUTPUT_DIR / token
    d.mkdir()
    (d / name).write_bytes(data)
    return f"/d/{token}/{quote(name)}"


def _cleanup() -> None:
    cutoff = time.time() - FILE_TTL
    for d in OUTPUT_DIR.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


def _check_key(key: str | None) -> None:
    if API_KEY and key != API_KEY:
        raise HTTPException(401, "Invalid API key")


# ---------- Web UI + REST API ----------

@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/healthz")
def health():
    return {"ok": True, "line": line_bot.enabled()}


@app.post("/api/convert")
async def api_convert(
    file: UploadFile = File(...),
    format: str = Form("pdf"),
    response: str = Form("file"),  # "file" = stream back, "link" = JSON with download URL
    x_api_key: str | None = Header(None),
):
    """Used by the web page and by external workflows (n8n / Make / Apps Script)."""
    _check_key(x_api_key)
    try:
        fmt = normalize_format(format)
        out, out_name = await _convert(await file.read(), file.filename or "document.pages", fmt)
    except ConversionError as e:
        raise HTTPException(422, str(e))

    ext = Path(out_name).suffix
    if response == "link":
        path = _store(out, out_name)
        return {"filename": out_name, "url": (PUBLIC_BASE_URL + path) if PUBLIC_BASE_URL else path,
                "expires_in_minutes": FILE_TTL // 60}
    return Response(out, media_type=MEDIA[ext],
                    headers={"Content-Disposition": f"attachment; filename=\"converted{ext}\"; "
                             f"filename*=UTF-8''{quote(out_name)}"})


@app.get("/d/{token}/{name}")
def download(token: str, name: str):
    p = (OUTPUT_DIR / token / name).resolve()
    if OUTPUT_DIR.resolve() not in p.parents or not p.is_file():
        raise HTTPException(404, "File expired or not found")
    return FileResponse(p, media_type=MEDIA.get(p.suffix, "application/octet-stream"), filename=name)


# ---------- LINE webhook ----------

@app.post("/line/webhook")
async def line_webhook(request: Request, bg: BackgroundTasks,
                       x_line_signature: str = Header("")):
    body = await request.body()
    if not line_bot.verify_signature(body, x_line_signature):
        raise HTTPException(401, "Bad signature")
    for ev in json.loads(body).get("events", []):
        if ev.get("type") == "message":
            bg.add_task(_handle_line_message, ev)
    return {"ok": True}  # LINE requires a fast 200


async def _handle_line_message(ev: dict) -> None:
    msg = ev["message"]
    user = ev.get("source", {}).get("userId")
    to = ev.get("source", {}).get("groupId") or ev.get("source", {}).get("roomId") or user
    reply = ev.get("replyToken")

    if msg["type"] == "text":
        t = msg["text"].strip().lower()
        if t in ("pdf", "word", "docx"):
            _user_format[user] = normalize_format(t)
            label = "PDF" if _user_format[user] == "pdf" else "Word (.docx)"
            await line_bot.reply_or_push(reply, to, [line_bot.text(f"Output set to {label}. Send a .pages file.")])
        else:
            await line_bot.reply_or_push(reply, to, [line_bot.text(
                "Send a .pages file and I will convert it.\nChoose output format:", quick_formats=True)])
        return

    if msg["type"] != "file":
        return
    name = msg.get("fileName", "document.pages")
    if not name.lower().endswith((".pages", ".zip")):
        await line_bot.reply_or_push(reply, to, [line_bot.text("Please send a .pages file.")])
        return

    fmt = _user_format.get(user, os.getenv("LINE_DEFAULT_FORMAT", "pdf"))
    try:
        data = await line_bot.download_content(msg["id"])
        out, out_name = await _convert(data, name, fmt)
        url = PUBLIC_BASE_URL + _store(out, out_name)
        text = f"Converted: {out_name}\n{url}\n(link expires in {FILE_TTL // 60} min)"
    except ConversionError as e:
        text = f"Conversion failed: {e}"
    except Exception as e:  # network / LINE API errors
        text = f"Error: {type(e).__name__}"
    await line_bot.reply_or_push(reply, to, [line_bot.text(text, quick_formats=True)])
