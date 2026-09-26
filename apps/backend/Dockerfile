# Python 3.12 rather than the 3.14 used for local development: lxml and reportlab
# ship prebuilt aarch64 wheels for 3.12, and Oracle's Always Free tier is ARM
# (VM.Standard.A1.Flex). Without wheels those two build from source, which needs
# a toolchain this image deliberately does not carry.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so edits to source do not invalidate the install layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The FastAPI app.
COPY app ./app

# Run as a non-root user. The crawler fetches arbitrary attacker-influenced URLs
# and parses their HTML, so this process should hold no privileges it never needs.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app

# The session volume mounts at /data/sessions. This directory has to exist in
# the image, owned by appuser: Docker copies an image path's ownership onto a
# fresh named volume, and without it the volume is created root-owned, leaving
# the non-root process unable to write a single audit -- a failure that appears
# only on a real deployment with a volume attached, never in local runs.
RUN mkdir -p /data/sessions && chown -R appuser:appuser /data

USER appuser

EXPOSE 8000

# 0.0.0.0, not the 127.0.0.1 that `uvicorn --port` alone would bind: a
# loopback-only bind is invisible to Docker's port mapping and to any reverse
# proxy, and presents as a connection refused with no log line explaining it.
# Single worker is a hard requirement, not a default: session state, the crawler
# registry, the rank cache and the live WebSocket connection list all live in
# process memory, so a second worker would answer requests that cannot see them.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
