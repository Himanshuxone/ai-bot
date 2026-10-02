# Minimal, non-root container image.            [RULE: GDPR-ART32] [RULE: SEC-SECRETS]
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FINRAG_ENVIRONMENT=production FINRAG_DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY finrag ./finrag

# Run as an unprivileged user; data volume owned by that user only.
RUN useradd --system --uid 10001 finrag && mkdir -p /data && chown finrag /data && chmod 700 /data
USER finrag
VOLUME ["/data"]
EXPOSE 8000

# Secrets (FINRAG_MASTER_KEY, ANTHROPIC_API_KEY, keys file) are injected at
# runtime from a secret manager - never baked into the image.
CMD ["uvicorn", "finrag.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
