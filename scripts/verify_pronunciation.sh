#!/bin/sh
# Verify stress and ё changes without touching the running web image/container.
set -eu
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo 'Missing .env. Run from an initialized Ruslex checkout on the VPS.' >&2
  exit 1
fi
data_root=$(sed -n 's/^DATA_ROOT=//p' .env | tail -n 1)
case "$data_root" in
  /*) ;;
  *) echo 'DATA_ROOT must be an absolute path.' >&2; exit 1 ;;
esac
if [ ! -r "$data_root/lexicon/lexicon.db" ]; then
  echo 'The lexicon database is missing or unreadable.' >&2
  exit 1
fi
if [ ! -r "$data_root/reference/openrussian.db" ]; then
  echo 'OpenRussian reference database is missing or unreadable.' >&2
  exit 1
fi

printf '\n== Python offline regressions ==\n'
python3 scripts/offline_checks.py

printf '\n== Isolated web image (Svelte check + build) ==\n'
docker build -t ruslex-pronunciation-check:local -f Dockerfile .

printf '\n== Isolated Django smoke test: copy of live data, no network ==\n'
docker run --rm --network none \
  -v "$data_root:/data:ro" \
  -e DATA_DIR=/data \
  --entrypoint python \
  ruslex-pronunciation-check:local /app/scripts/smoke_test.py

printf '\n== Build on-demand processing image ==\n'
./process.sh build

printf '\n== Read-only OpenRussian info ==\n'
./process.sh reference info

printf '\n== Rehearse stress migration/backfill on disposable DB ==\n'
./process.sh stress rehearse

printf '\nPASS: checks completed without touching production data or web container.\n'
