#!/bin/sh
# Container start (M11, D79): apply migrations, make sure the cache table exists, then run
# Gunicorn. Runs as the image's non-root user from /app/src. Needs at run time:
# DJANGO_SECRET_KEY, DATABASE_URL, DJANGO_ALLOWED_HOSTS, DJANGO_CLIENT_IP_HEADER (see
# docs/deploy-runbook.md). Migrations run here because the free host has no pre-deploy step [A];
# with one instance there is no migration race.
set -eu

python manage.py migrate --noinput
# Database cache for the login and tourist throttles (D58, D75); no-op when it exists.
python manage.py createcachetable

# No --access-logfile: Gunicorn's access log would write client addresses (AGENTS.md rule 5).
# Errors go to stderr; the app's own logs are JSON on stdout (config.logs, D80).
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --worker-tmp-dir /dev/shm \
    --error-logfile -
