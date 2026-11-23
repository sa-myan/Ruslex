#!/bin/sh
# Run ALL OCR/AI work on the VPS, separately from the public website.
set -eu
cd "$(dirname "$0")"
compose() { docker compose -f docker-compose.processing.yml "$@"; }
command=${1:-help}
shift || true
case "$command" in
  build) compose build worker ;;
  auth) compose run --rm --no-deps --entrypoint opencode worker auth login ;;
  version) compose run --rm --no-deps --entrypoint opencode worker --version ;;
  promote) compose run --rm --no-deps promoter python -m processing.cli promote "$@" ;;
  help|-h|--help) compose run --rm --no-deps worker python -m processing.cli --help ;;
  *) compose run --rm --no-deps worker python -m processing.cli "$command" "$@" ;;
esac
