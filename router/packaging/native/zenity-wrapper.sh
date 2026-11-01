#!/bin/sh
set -eu
gui=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export LD_LIBRARY_PATH="$gui/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export GI_TYPELIB_PATH="$gui/lib/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
export GSETTINGS_SCHEMA_DIR="$gui/share/glib-2.0/schemas"
loaders="$gui/lib/gdk-pixbuf/loaders"
if [ -d "$loaders" ]; then
  export GDK_PIXBUF_MODULEDIR="$loaders"
  cache=$(mktemp)
  trap 'rm -f "$cache"' EXIT HUP INT TERM
  "$gui/libexec/gdk-pixbuf-query-loaders" "$loaders"/*.so > "$cache"
  export GDK_PIXBUF_MODULE_FILE="$cache"
fi
"$gui/libexec/zenity" "$@"
