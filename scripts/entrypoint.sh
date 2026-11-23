#!/bin/sh
set -eu
cd /app/backend
python manage.py check_lexicon
python manage.py migrate --database=default --noinput
python manage.py initialize_roles
python manage.py check
exec gunicorn siteconf.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 2 --timeout 90 --access-logfile - --error-logfile -
