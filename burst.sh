#!/usr/bin/env sh
# On-sale stampede + PASS/FAIL checks. Needs only python3 (standard library).
#   ./burst.sh <BASE_URL> [--requests 2000] [--concurrency 200] [--seats N] [--ramp 3] [--admin-key KEY]
set -e
[ -n "$1" ] || { echo "usage: ./burst.sh <BASE_URL> [--requests N] [--concurrency N] [--seats N] [--ramp S] [--admin-key KEY]" >&2; exit 2; }
exec python3 "$(dirname "$0")/scripts/burst.py" "$@"
