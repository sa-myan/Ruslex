#!/bin/sh
set -eu
cd "$(dirname "$0")"
command=${1:-help}
shift || true
case "$command" in
  admin) docker compose exec web python manage.py createsuperuser "$@" ;;
  logs) docker compose logs -f --tail=100 web ;;
  status) docker compose ps -a ;;
  check) docker compose exec web python manage.py check_lexicon ; docker compose exec web python manage.py check ;;
  backup) python3 scripts/backup.py "$@" ;;
  stop) docker compose stop web ;;
  start) docker compose up -d web ;;
  update) python3 scripts/backup.py ; docker compose up -d --build --force-recreate web ;;
  shell) docker compose exec web python manage.py shell ;;
  test) docker compose run --rm --no-deps --entrypoint python web /app/scripts/smoke_test.py ;;
  *) echo 'Usage: ./manage.sh {admin|logs|status|check|backup|stop|start|update|shell|test}';;
esac
