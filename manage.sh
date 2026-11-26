#!/bin/sh
# VPS-only project commands. Only publish/unpublish touches shared Caddy config.
set -eu
cd "$(dirname "$0")"
command=${1:-help}
shift || true
case "$command" in
  init|install) python3 scripts/install.py "$@" ;;
  publish) python3 scripts/proxy.py publish "$@" ;;
  unpublish) python3 scripts/proxy.py unpublish "$@" ;;
  doctor|preflight) python3 scripts/release.py preflight --allow-dirty "$@" ;;
  build) python3 scripts/release.py build "$@" ;;
  migrate) python3 scripts/release.py migrate "$@" ;;
  deploy|update) python3 scripts/release.py deploy "$@" ;;
  health) python3 scripts/release.py health ;;
  lock) docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/frontend:/frontend" -w /frontend node:22-alpine npm install --package-lock-only --ignore-scripts --no-audit --no-fund ;;
  status) docker compose ps -a ;;
  logs) docker compose logs -f --tail=100 web ;;
  check) docker compose exec web python manage.py check_lexicon; docker compose exec web python manage.py check ;;
  backup) python3 scripts/backup.py "$@" ;;
  restore) python3 scripts/restore.py "$@" ;;
  stop) docker compose stop web ;;
  start) docker compose up -d --no-deps web ;;
  disable) docker compose stop web; python3 scripts/proxy.py unpublish ;;
  remove-containers) docker compose down --remove-orphans ;;
  admin) docker compose exec web python manage.py createsuperuser "$@" ;;
  shell) docker compose exec web python manage.py shell ;;
  test)
    # Only a read-only lexicon source is supplied. The smoke runner creates
    # its own isolated lexicon/admin copies under /tmp; it cannot write live data,
    # read OpenRussian, or access AI credentials, and has no network.
    [ -f .env ] || { echo 'Missing .env; run ./manage.sh init first.' >&2; exit 1; }
    data_root=$(sed -n 's/^DATA_ROOT=//p' .env | tail -n 1)
    uid=$(sed -n 's/^PUID=//p' .env | tail -n 1)
    gid=$(sed -n 's/^PGID=//p' .env | tail -n 1)
    case "$data_root" in /*) ;; *) echo 'DATA_ROOT must be an absolute path' >&2; exit 1 ;; esac
    case "$uid" in ''|*[!0-9]*) echo 'PUID must be numeric' >&2; exit 1 ;; esac
    case "$gid" in ''|*[!0-9]*) echo 'PGID must be numeric' >&2; exit 1 ;; esac
    docker run --rm --network none --read-only \
      --tmpfs /tmp:rw,nosuid,nodev,size=256m \
      --user "$uid:$gid" \
      -v "$data_root/lexicon:/data/lexicon:ro" \
      -e DATA_DIR=/data \
      -e DJANGO_SECRET_KEY=isolated-smoke-test-only \
      --entrypoint python ruslex:local /app/scripts/smoke_test.py
    ;;
  *) printf '%s\n' 'Usage: ./manage.sh {init|publish|unpublish|doctor|lock|build|migrate|deploy|health|status|logs|check|backup|restore|start|stop|disable|remove-containers|admin|shell|test}';;
esac
