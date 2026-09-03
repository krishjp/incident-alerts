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

ENV PYTHONUNBUFFERED=1

# One check_and_notify() pass, then exit. No HTTP API and no port to expose —
# a Cloud Run Job (or a local scheduled loop) invokes this container per cycle
# and reads its exit code, rather than probing a liveness endpoint.
CMD ["uv", "run", "python", "main.py"]
