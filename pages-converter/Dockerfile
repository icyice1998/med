FROM python:3.12-slim

# LibreOffice Writer (includes libetonyek for .pages import) + Thai/CJK fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer libreoffice-draw \
        fonts-thai-tlwg fonts-noto-core fonts-noto-cjk fonts-liberation fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

ENV PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
