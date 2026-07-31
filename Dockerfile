FROM python:3.12-slim

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py index.html ./

# Local-disk save is dev-only (see README) — no PersistentVolume is assumed
# in this image, so the default here matches the Kubernetes deployment.
ENV SAVE_TO_LOCAL_DISK=false \
    PORT=4174

RUN mkdir -p /app/submissions && chown -R app:app /app
USER app

EXPOSE 4174

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:4174/healthz', timeout=3).status == 200"

CMD ["gunicorn", "--bind", "0.0.0.0:4174", "--workers", "2", "--threads", "4", "--timeout", "60", "app:app"]
