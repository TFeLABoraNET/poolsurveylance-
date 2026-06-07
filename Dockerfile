# Multi-arch Image, läuft u. a. auf Raspberry Pi (arm64/armv7) und x86.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POOL_DATABASE_URL=sqlite:////data/pool.db

WORKDIR /app

# Abhängigkeiten zuerst (besseres Layer-Caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungscode
COPY app ./app

# Datenverzeichnis für die SQLite-DB (per Volume gemountet)
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
