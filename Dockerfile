FROM python:3.12-slim

# No .pyc files; stdout unbuffered so log lines reach the platform immediately.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY main.py .

# Don't run as root.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Platforms like Render/Railway inject PORT; 8000 locally.
ENV PORT=8000
EXPOSE 8000

# Liveness only: the process answers. Readiness (DB) is /health/ready.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health/live', timeout=2)"

# One process per container: the Prometheus counters live in process memory,
# so several workers would each report only their own share. The app is async,
# so one process already handles the concurrency; scale with more containers.
# --proxy-headers: trust X-Forwarded-* from the platform's load balancer.
# exec: uvicorn becomes PID 1 and receives SIGTERM for a graceful shutdown.
CMD exec uvicorn main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips "*" \
    --timeout-graceful-shutdown 20
