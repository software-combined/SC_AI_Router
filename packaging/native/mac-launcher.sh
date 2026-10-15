#!/bin/sh
set -eu
resources=$(CDPATH= cd -- "$(dirname -- "$0")/../Resources" && pwd)
exec "$resources/runtime/python/bin/python3.14" \
  "$resources/router/packaging/native_setup.py" --resources "$resources" "$@"
