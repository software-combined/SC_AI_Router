#!/bin/sh
# First-install bootstrap for hosts without repo access (Plan 054 T).
# POSIX sh + curl/python3/tar/shasum only: resolves the pinned CPython
# runtime from runtimes.json, verifies every download by SHA-256, writes
# the feed token owner-only, then runs the verified bundle installer.
# Usage (token from the Technology library page):
#   SCG_FEED_TOKEN=<token> sh bootstrap.sh [--channel=beta]
set -eu
FEED_ORIGIN="${FEED_ORIGIN:-https://dist.softwarecombined.com}"
CHANNEL="stable"
HOME_DIR="${ROUTER_HOME:-$HOME/.codex/mixed-model-router}"
TOKEN="${SCG_FEED_TOKEN:-}"
for arg in "$@"; do
  case "$arg" in
    --channel=*) CHANNEL="${arg#--channel=}" ;;
    *) echo "usage: SCG_FEED_TOKEN=<token> sh bootstrap.sh [--channel=beta]" >&2; exit 2 ;;
  esac
done
case "$CHANNEL" in
  stable|beta) ;;
  *) echo "error: channel must be stable or beta" >&2; exit 2 ;;
esac
if [ -z "$TOKEN" ]; then
  echo "error: set SCG_FEED_TOKEN from the Technology library page" >&2
  exit 2
fi
OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS" in Darwin) OS=darwin ;; Linux) OS=linux ;; esac
case "$ARCH" in arm64|aarch64) ARCH=arm64 ;; x86_64|amd64) ARCH=x86_64 ;; esac
mkdir -p "$HOME_DIR"
chmod 700 "$HOME_DIR"
# Keep the token off curl's argv: curl reads it from an owner-only header
# file whose name, not the token, is what other users can see via ps.
HEADERS="$HOME_DIR/feed-headers.tmp"
printf 'X-SCG-Feed-Token: %s\n' "$TOKEN" > "$HEADERS"
chmod 600 "$HEADERS"
trap 'rm -f "$HEADERS"' EXIT INT TERM
dl() {
  curl -fsSL -H "@$HEADERS" "$FEED_ORIGIN/$1" -o "$2"
}
dl "runtimes.json" "$HOME_DIR/runtimes.json"
# Persist only after the token fetched successfully; keep the previous
# value for the updater's one-time 403 retry, as feed.py does.
if [ -f "$HOME_DIR/feed-token" ]; then CURRENT="$(cat "$HOME_DIR/feed-token")"; else CURRENT=""; fi
if [ -n "$CURRENT" ] && [ "$CURRENT" != "$TOKEN" ]; then
  printf '%s\n' "$CURRENT" > "$HOME_DIR/feed-token.previous"
  chmod 600 "$HOME_DIR/feed-token.previous"
fi
printf '%s\n' "$TOKEN" > "$HOME_DIR/feed-token.tmp"
chmod 600 "$HOME_DIR/feed-token.tmp"
mv "$HOME_DIR/feed-token.tmp" "$HOME_DIR/feed-token"
TARGET="$OS/$ARCH"
export HOME_DIR TARGET
RT="$(python3 -c "import json,os;t=json.load(open(os.environ['HOME_DIR']+'/runtimes.json'))['targets'][os.environ['TARGET']];print(t['mirror'],t['sha256'],t['exec'])")"
set -- $RT; MIRROR="$1"; RSHA="$2"; REXEC="$3"
# Percent-encode the URL path: a raw '+' in an S3 key is decoded as a space
# at the edge and denied, and upstream runtime names carry '+' (3.14.7+DATE).
MIRROR_URL="$(python3 -c "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1], safe='/'))" "$MIRROR")"
dl "$MIRROR_URL" "$HOME_DIR/runtime.tar.gz"
echo "$RSHA  $HOME_DIR/runtime.tar.gz" | shasum -a 256 -c -
mkdir -p "$HOME_DIR/runtime"
tar -xzf "$HOME_DIR/runtime.tar.gz" -C "$HOME_DIR/runtime"
PY="$HOME_DIR/runtime/$REXEC"
"$PY" -c "import compression.zstd; print('runtime ok')"
dl "$CHANNEL/latest.json" "$HOME_DIR/latest.json"
set -- $(python3 -c "import json,os;d=json.load(open(os.environ['HOME_DIR']+'/latest.json'));print(d['url'],d['sha256'])")
URL="$1"; SHA="$2"
ASSET="${URL##*/}"
dl "bundles/$ASSET" "$HOME_DIR/bundle.tar.gz"
echo "$SHA  $HOME_DIR/bundle.tar.gz" | shasum -a 256 -c -
mkdir -p "$HOME_DIR/bootstrap"
tar -xzf "$HOME_DIR/bundle.tar.gz" -C "$HOME_DIR/bootstrap"
rm -f "$HEADERS"
# Pin this run to the channel the operator asked for: the installer resolves
# its own feed from the router home, which may still name the old channel.
# Persist the channel only once the install proves out, so an aborted
# bootstrap cannot move a stable host onto pre-releases.
if "$PY" "$HOME_DIR/bootstrap/packaging/install.py" --home "$HOME_DIR" \
     --feed "$FEED_ORIGIN/$CHANNEL/latest.json"; then
  printf '%s\n' "$CHANNEL" > "$HOME_DIR/channel"
else
  exit $?
fi
