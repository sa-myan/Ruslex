#!/bin/sh
# Runtime only. Database checks/migrations belong to the explicit deploy step.
set -eu
cd /app/backend
exec gunicorn siteconf.wsgi:application --bind 0.0.0.0:8000 \
  --workers 2 --threads 2 --timeout 90 \
  --access-logfile - --error-logfile -
