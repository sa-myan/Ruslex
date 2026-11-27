#!/bin/sh
# All corpus and AI work happens on the VPS, outside the public web container.
set -eu
cd "$(dirname "$0")"

compose() {
  docker compose -f docker-compose.processing.yml "$@"
}

# The OpenCode home lives on a host bind mount. Docker can initially create
# that mount as root, so initialize its ownership once for the worker UID/GID.
# A small marker avoids launching a privileged setup container for every batch.
state_directory() {
  if [ ! -f .env ]; then
    echo 'Missing .env; run ./manage.sh init first.' >&2
    exit 1
  fi
  data_root=$(sed -n 's/^DATA_ROOT=//p' .env | tail -n 1)
  uid=$(sed -n 's/^PUID=//p' .env | tail -n 1)
  gid=$(sed -n 's/^PGID=//p' .env | tail -n 1)

  case "$data_root" in
    /*) ;;
    *) echo 'DATA_ROOT must be an absolute path in .env' >&2; exit 1 ;;
  esac
  case "$uid" in
    ''|*[!0-9]*) echo 'PUID must be numeric in .env' >&2; exit 1 ;;
  esac
  case "$gid" in
    ''|*[!0-9]*) echo 'PGID must be numeric in .env' >&2; exit 1 ;;
  esac
  if [ "$uid" -eq 0 ] || [ "$gid" -eq 0 ]; then
    echo 'The processing worker must not run as root; check PUID/PGID in .env.' >&2
    exit 1
  fi
  printf '%s/processing/state' "${data_root%/}"
}

ensure_state() {
  state=$(state_directory)
  # Use the container's configured UID, which may differ from the SSH user.
  configured_uid=$(sed -n 's/^PUID=//p' .env | tail -n 1)
  if [ ! -f "$state/.ruslex-ready-$configured_uid" ]; then
    setup_state
  fi
}

setup_state() {
  # Only this short-lived, network-isolated service runs as root. It repairs
  # the processing parent ownership and OpenCode state, not dictionary/Caddy.
  compose run --rm --no-deps state-init
}

command=${1:-help}
shift || true
case "$command" in
  build)
    compose build worker
    ensure_state
    ;;
  setup-state|repair-state)
    setup_state
    ;;
  doctor)
    ensure_state
    if ! compose run --rm --no-deps --entrypoint /bin/sh worker -ec \
      'mkdir -p /state/config/opencode /state/data/opencode/log /state/cache/opencode && test -w /state/data/opencode/log'; then
      echo 'OpenCode state is not writable. Run ./process.sh repair-state.' >&2
      exit 1
    fi
    echo 'OpenCode state is writable as the processing user.'
    ;;
  auth)
    ensure_state
    compose run --rm --no-deps --entrypoint opencode worker auth login
    ;;
  version)
    ensure_state
    compose run --rm --no-deps --entrypoint opencode worker --version
    ;;
  models)
    ensure_state
    compose run --rm --no-deps --entrypoint opencode worker models "$@"
    ;;
  stress)
    case "${1:-}" in
      init|backfill|ai-apply) compose run --rm --no-deps promoter python -m processing.cli stress "$@" ;;
      plan|diagnose|rehearse|ai-plan|ai-approval-plan) compose run --rm --no-deps rehearsal python -m processing.cli stress "$@" ;;
      ai-run) ensure_state; compose run --rm --no-deps worker python -m processing.cli stress "$@" ;;
      *) echo "Use ./process.sh stress {plan|diagnose|rehearse|init|backfill|ai-run|ai-plan|ai-apply}" >&2; exit 2 ;;
    esac
    ;;
  constructions)
    case "${1:-}" in
      init|apply) compose run --rm --no-deps promoter python -m processing.cli constructions "$@" ;;
      scan) ensure_state; compose run --rm --no-deps worker python -m processing.cli constructions "$@" ;;
      plan|pages) compose run --rm --no-deps rehearsal python -m processing.cli constructions "$@" ;;
      *) echo "Use ./process.sh constructions {init|pages|scan|plan|apply}" >&2; exit 2 ;;
    esac
    ;;
  pronunciation-review)
    case "${1:-}" in
      init|candidates-refresh) compose run --rm --no-deps promoter python -m processing.cli pronunciation-review "$@" ;;
      plan|candidates-plan) compose run --rm --no-deps rehearsal python -m processing.cli pronunciation-review "$@" ;;
      *) echo "Use ./process.sh pronunciation-review {plan|init|candidates-plan|candidates-refresh}" >&2; exit 2 ;;
    esac
    ;;
  abbreviations)
    case "${1:-}" in
      init|categorize) compose run --rm --no-deps promoter python -m processing.cli abbreviations "$@" ;;
      plan|rehearse) compose run --rm --no-deps rehearsal python -m processing.cli abbreviations "$@" ;;
      *) echo "Use ./process.sh abbreviations {plan|rehearse|init|categorize}" >&2; exit 2 ;;
    esac
    ;;
  forms)
    case "${1:-}" in
      init|backfill|stress-init|stress-apply) compose run --rm --no-deps promoter python -m processing.cli forms "$@" ;;
      plan|rehearse|stress-plan|stress-rehearse) compose run --rm --no-deps rehearsal python -m processing.cli forms "$@" ;;
      *) echo "Use ./process.sh forms {plan|rehearse|init|backfill|stress-plan|stress-rehearse|stress-init|stress-apply}" >&2; exit 2 ;;
    esac
    ;;
  book-promote)
    compose run --rm --no-deps promoter python -m processing.cli book-promote "$@"
    ;;
  promote)
    compose run --rm --no-deps promoter python -m processing.cli promote "$@"
    ;;
  help|-h|--help)
    ensure_state
    compose run --rm --no-deps worker python -m processing.cli --help
    ;;
  *)
    ensure_state
    compose run --rm --no-deps worker python -m processing.cli "$command" "$@"
    ;;
esac
