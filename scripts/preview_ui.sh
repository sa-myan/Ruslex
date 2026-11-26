#!/bin/sh
# Isolated Ruslex UI preview. Does not modify production containers, Caddy or data.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PRODUCTION=/srv/apps/ruslex
NAME=ruslex-ui-preview
IMAGE=ruslex-ui-preview:local
PORT=8791

usage() {
    printf 'Usage: sh scripts/preview_ui.sh start /path/to/dated-backup | stop | status\n' >&2
    exit 2
}

action=${1:-}
case "$action" in
    start)
        [ "$#" -eq 2 ] || usage
        BACKUP=$2
        [ -f "$BACKUP/lexicon.db" ] || { echo "Missing backup lexicon.db" >&2; exit 1; }
        [ -f "$BACKUP/admin.sqlite3" ] || { echo "Missing backup admin.sqlite3" >&2; exit 1; }
        [ -f "$PRODUCTION/.env" ] || { echo "Missing production .env" >&2; exit 1; }
        if docker container inspect "$NAME" >/dev/null 2>&1; then
            echo "Preview container already exists. Stop it first." >&2
            exit 1
        fi
        # Deliberately refuse a busy loopback port.
        if command -v ss >/dev/null 2>&1 &&
          ss -ltn | grep -q ":$PORT "; then
            echo "Port $PORT is already in use." >&2
            exit 1
        fi
        docker build -t "$IMAGE" "$ROOT"
        SNAPSHOT=$(mktemp -d /srv/data/ruslex/ui-preview-XXXXXXXX)
        chmod 700 "$SNAPSHOT"
        mkdir -p "$SNAPSHOT/lexicon" "$SNAPSHOT/admin"
        cp "$BACKUP/lexicon.db" "$SNAPSHOT/lexicon/lexicon.db"
        cp "$BACKUP/admin.sqlite3" "$SNAPSHOT/admin/admin.sqlite3"
        chmod -R u+rwX,go-rwx "$SNAPSHOT"
        # All preview traffic remains on loopback. No shared proxy network.
        docker run -d --name "$NAME" --restart no \
            --user "$(id -u):$(id -g)" \
            --publish "127.0.0.1:$PORT:8000" \
            --env-file "$PRODUCTION/.env" \
            --env DATA_DIR=/data \
            --env DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost \
            --env PUBLIC_ORIGIN="http://127.0.0.1:$PORT" \
            --env HTTPS_ENABLED=0 \
            --volume "$SNAPSHOT:/data" \
            "$IMAGE" >/dev/null
        printf 'Preview: http://127.0.0.1:%s (via SSH tunnel)\n' "$PORT"
        printf 'Private disposable database snapshot: %s\n' "$SNAPSHOT"
        printf 'Run: sh scripts/preview_ui.sh status\n'
        ;;
    status)
        [ "$#" -eq 1 ] || usage
        docker ps -a --filter "name=^/$NAME$" \
            --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
        ;;
    stop)
        [ "$#" -eq 1 ] || usage
        docker rm -f "$NAME" >/dev/null
        echo "Preview container stopped. Snapshot folder retained for manual inspection/cleanup."
        ;;
    *) usage ;;
esac
