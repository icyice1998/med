# Pages Converter (.pages -> PDF / Word) with LINE bot

Small FastAPI service that converts Apple Pages documents to PDF or DOCX
using headless LibreOffice (libetonyek import filter). Works three ways:

1. Web page: open `/`, drop a `.pages` file, choose PDF or Word.
2. LINE bot: user sends a `.pages` file in LINE chat; bot replies with a download link.
3. REST API: for workflows (n8n, Make, Google Apps Script) that receive the file from LINE themselves.

```
LINE user --file--> LINE Platform --webhook--> /line/webhook
                                                 | download content (api-data.line.me)
                                                 | LibreOffice convert
                                                 v
LINE user <--text + link-- reply/push <------ /d/<token>/<file>  (expires after FILE_TTL_MINUTES)
```

LINE bots cannot send PDF/DOCX attachments, so the bot replies with a temporary link.

## Supported input

| Pages version          | Format inside zip         | Result          |
|------------------------|---------------------------|-----------------|
| Pages '09 (4.x)        | index.xml                 | Converts        |
| Pages 5+ / iCloud      | Index/*.iwa               | Converts (text, styles; complex layout may differ) |
| Old files, unreadable  | QuickLook/Preview.pdf     | Fallback: embedded preview PDF |

## Run locally

```bash
cd pages-converter
docker build -t pages-converter .
docker run -p 8080:8080 --env-file .env pages-converter
# open http://localhost:8080
```

Without Docker (LibreOffice must be installed, `soffice` on PATH):

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8080
pytest -q tests
```

## REST API

```
POST /api/convert   multipart/form-data
  file      .pages file (required)
  format    pdf | docx | word          (default pdf)
  response  file | link                (default file)
  header    X-API-Key: <API_KEY>        (only if API_KEY is set)
```

```bash
curl -F file=@report.pages -F format=docx -o report.docx https://<host>/api/convert
curl -F file=@report.pages -F response=link https://<host>/api/convert
# {"filename":"report.pdf","url":"https://<host>/d/.../report.pdf","expires_in_minutes":60}
```

## Deploy

GitHub only stores the code; the converter needs a server that can run LibreOffice.
Any Docker host works (Render, Railway, Fly.io, Google Cloud Run).

Render: New > Blueprint > select this repo (uses `render.yaml` at repo root), then set env vars.

Cloud Run:

```bash
gcloud run deploy pages-converter --source pages-converter \
  --region asia-southeast1 --memory 1Gi --allow-unauthenticated \
  --set-env-vars PUBLIC_BASE_URL=https://...,LINE_CHANNEL_SECRET=...,LINE_CHANNEL_ACCESS_TOKEN=...
```

Note: converted files live in local `/tmp`; on Cloud Run use `--min-instances 1 --max-instances 1`
so download links hit the same instance (or move storage to a bucket).

## LINE setup

1. LINE Developers console > create a Messaging API channel.
2. Copy Channel secret and issue a Channel access token (long-lived) into env vars.
3. Webhook URL: `https://<host>/line/webhook`, enable "Use webhook", press Verify.
4. LINE Official Account Manager: turn off auto-reply messages.
5. In chat: type `pdf` or `word` to choose output, then send the `.pages` file.

## Environment variables

See `.env.example`.

| Variable                  | Purpose                                         | Default |
|---------------------------|-------------------------------------------------|---------|
| LINE_CHANNEL_SECRET       | Verifies X-Line-Signature                       | -       |
| LINE_CHANNEL_ACCESS_TOKEN | Download content / reply / push                 | -       |
| LINE_DEFAULT_FORMAT       | pdf or docx when user has not chosen            | pdf     |
| PUBLIC_BASE_URL           | Base for download links sent to LINE            | -       |
| API_KEY                   | Protects /api/convert when set                  | empty   |
| MAX_UPLOAD_MB             | Upload size limit                               | 50      |
| FILE_TTL_MINUTES          | Lifetime of download links                      | 60      |
| MAX_PARALLEL              | Concurrent LibreOffice conversions              | 2       |
