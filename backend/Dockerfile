# PyroScope API. Data (archives, Parquet, SQLite) is mounted at /app/data - never baked into the image.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/app ./app
RUN useradd --create-home --uid 10001 pyro && mkdir -p /app/data /app/docs && chown -R pyro /app
USER pyro

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import json,urllib.request,sys; h=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)); sys.exit(0 if h['database']['ok'] else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
