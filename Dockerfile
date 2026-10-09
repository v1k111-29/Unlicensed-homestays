# Verified Stays web image (M11, D83). Not built on the dev machine (no Docker, Q14): CI job
# `docker` in .github/workflows/ci.yml builds it and smoke-tests it against PostgreSQL.
# Python 3.11 line as everywhere else (D28); the patch level follows the base image for
# security fixes.
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Application code, and the data files the app reads at run time (Q20):
# - gazetteer.csv + localities.csv: matching.gazetteer resolves localities from them;
# - out/: synthetic dev/test sets for the one-off `load_synthetic` demo load (runbook).
COPY src ./src
COPY data/synthetic/gazetteer.csv data/synthetic/localities.csv ./data/synthetic/
COPY data/synthetic/out ./data/synthetic/out
COPY scripts/docker-start.sh /usr/local/bin/docker-start

# Hashed, compressed static files for WhiteNoise (D83). Build-time values only: collectstatic
# needs no database or secret, and DEBUG=1 here does not reach the running container.
WORKDIR /app/src
RUN DJANGO_DEBUG=1 DJANGO_SECRET_KEY=collectstatic-build-only \
    python manage.py collectstatic --noinput \
    && chmod 0755 /usr/local/bin/docker-start \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

# Everything above is owned by root and read-only for the app user.
USER app

# Render sets PORT [A]; 8000 elsewhere.
ENV PORT=8000
EXPOSE 8000

# Liveness only (no database, D81). /livez is answered before host checks and HTTPS redirect.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/livez', timeout=4)"]

CMD ["docker-start"]
