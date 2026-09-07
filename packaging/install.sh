#!/bin/sh
# Thin wrapper: the installer lives in install.py (Plan 041).
set -eu
exec python3 "$(dirname "$0")/install.py" "$@"
