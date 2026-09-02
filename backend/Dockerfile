FROM python:3.11-slim

# uv is pinned so an image rebuild can't pick up a breaking resolver change.
RUN pip install --no-cache-dir uv==0.5.11

WORKDIR /app

# Dependency layer first: source edits don't invalidate the (slow) install.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Run as a non-root user. The worker needs no write access to its own code.
RUN useradd --create-home --uid 1001 worker && chown -R worker:worker /app
USER worker

ENV PYTHONUNBUFFERED=1 \
    PORT=8080

# The worker has no HTTP API; this port serves only the liveness endpoint that
# Cloud Run (and any orchestrator's probes) require. See backend/health.py.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"

CMD ["uv", "run", "python", "main.py"]
