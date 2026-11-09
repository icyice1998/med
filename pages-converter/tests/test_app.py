import base64, hashlib, hmac, io, json, zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import line_bot
from app.converter import ConversionError, convert_pages
from app.main import app

DATA = Path(__file__).parent / "data"
client = TestClient(app)


@pytest.mark.parametrize("sample", ["Pages_4.pages", "Pages_5.pages"])
@pytest.mark.parametrize("fmt,magic", [("pdf", b"%PDF"), ("docx", b"PK")])
def test_convert_samples(sample, fmt, magic):
    out, name = convert_pages((DATA / sample).read_bytes(), sample, fmt)
    assert out.startswith(magic)
    assert name == Path(sample).stem + "." + fmt


def test_preview_pdf_fallback():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("QuickLook/Preview.pdf", b"%PDF-1.4 fake")
    out, _ = convert_pages(buf.getvalue(), "old.pages", "pdf")
    assert out == b"%PDF-1.4 fake"


def test_not_a_zip():
    with pytest.raises(ConversionError):
        convert_pages(b"hello", "x.pages", "pdf")


def test_api_file_and_link():
    f = (DATA / "Pages_5.pages").read_bytes()
    r = client.post("/api/convert", files={"file": ("รายงาน.pages", f)}, data={"format": "word"})
    assert r.status_code == 200 and r.content[:2] == b"PK"
    r = client.post("/api/convert", files={"file": ("a.pages", f)}, data={"format": "pdf", "response": "link"})
    url = r.json()["url"]
    assert client.get(url).content.startswith(b"%PDF")


def test_line_signature(monkeypatch):
    monkeypatch.setattr(line_bot, "CHANNEL_SECRET", "s3cret")
    body = json.dumps({"events": []}).encode()
    sig = base64.b64encode(hmac.new(b"s3cret", body, hashlib.sha256).digest()).decode()
    assert client.post("/line/webhook", content=body, headers={"X-Line-Signature": sig}).status_code == 200
    assert client.post("/line/webhook", content=body, headers={"X-Line-Signature": "bad"}).status_code == 401


def test_line_file_flow(monkeypatch):
    import app.main as m
    sent = []

    async def fake_download(mid):
        return (DATA / "Pages_5.pages").read_bytes()

    async def fake_reply(token, to, msgs):
        sent.append(msgs[0]["text"])

    monkeypatch.setattr(line_bot, "CHANNEL_SECRET", "s3cret")
    monkeypatch.setattr(line_bot, "download_content", fake_download)
    monkeypatch.setattr(line_bot, "reply_or_push", fake_reply)
    monkeypatch.setattr(m, "PUBLIC_BASE_URL", "https://example.test")

    def post(event):
        body = json.dumps({"events": [event]}).encode()
        sig = base64.b64encode(hmac.new(b"s3cret", body, hashlib.sha256).digest()).decode()
        return client.post("/line/webhook", content=body, headers={"X-Line-Signature": sig})

    src = {"type": "user", "userId": "U1"}
    post({"type": "message", "replyToken": "r", "source": src, "message": {"type": "text", "text": "word"}})
    post({"type": "message", "replyToken": "r", "source": src,
          "message": {"type": "file", "id": "1", "fileName": "note.pages"}})
    assert "Word" in sent[0]
    assert "https://example.test/d/" in sent[1] and "note.docx" in sent[1]
