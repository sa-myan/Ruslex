#!/bin/sh
# Verify the pronunciation feature without mutating the production databases.
set -eu
cd "$(dirname "$0")/.."
printf '\n== Python offline regressions ==\n'
python3 scripts/offline_checks.py
printf '\n== Build web image (Svelte check + compile) ==\n'
./manage.sh build
printf '\n== Django smoke tests (disposable DB copies) ==\n'
./manage.sh test
printf '\n== Processing image ==\n'
./process.sh build
printf '\n== Read-only OpenRussian summary ==\n'
./process.sh reference info
printf '\n== Rehearse stress schema/backfill on disposable DB ==\n'
./process.sh stress rehearse
printf '\nPASS: verification completed without production stress migration.\n'
