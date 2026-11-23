#!/bin/sh
# Backwards-compatible convenience alias. Initial setup is now explicit.
set -eu
cd "$(dirname "$0")"
exec ./manage.sh deploy "$@"
