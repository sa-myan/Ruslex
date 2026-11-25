#!/bin/sh
# Pre-release verification on production snapshots; no live schema/data writes.
set -eu
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo 'Missing .env; link this worktree to the initialized production .env' >&2
  exit 1
fi
data_root=$(sed -n 's/^DATA_ROOT=//p' .env | tail -n 1)
case "$data_root" in
  /*) ;;
  *) echo 'DATA_ROOT must be an absolute path' >&2; exit 1 ;;
esac
if [ ! -r "$data_root/lexicon/lexicon.db" ]; then
  echo "Missing readable dictionary under $data_root/lexicon" >&2
  exit 1
fi

printf '\n== Offline workflow, pronunciation and morphology regression tests ==\n'
python3 scripts/offline_checks.py

printf '\n== Isolated Django/Svelte image and build checks ==\n'
docker build -t ruslex-book-check-web:local -f Dockerfile .

printf '\n== Independent on-demand processing image ==\n'
export PROCESSING_IMAGE=ruslex-book-check-processing:local
./process.sh build

printf '\n== Snapshot-based forms migration and backfill rehearsal ==\n'
output=$(./process.sh forms rehearse)
printf '%s\n' "$output"
stamp=$(printf '%s\n' "$output" |
  sed -n 's@.*"rehearsal_path": "/work/form_rehearsals/\([0-9-]*\)".*@\1@p' | tail -n 1)
case "$stamp" in
  ''|*[!0-9-]*) echo "Cannot identify isolated form rehearsal database" >&2; exit 1 ;;
esac
db_path="$data_root/processing/form_rehearsals/$stamp/lexicon.db"
if [ ! -r "$db_path" ]; then
  echo "Missing rehearsal dictionary: $db_path" >&2
  exit 1
fi

printf '\n== Django smoke tests using the migrated disposable dictionary ==\n'
docker run --rm --network none \
  -v "$data_root:/data:ro" \
  -e DATA_DIR=/data \
  -e RUSLEX_SMOKE_LEXICON_SOURCE="/data/processing/form_rehearsals/$stamp/lexicon.db" \
  --entrypoint python ruslex-book-check-web:local /app/scripts/smoke_test.py

printf '\nPASS: new-book and word-form checks completed; live data untouched.\n'
