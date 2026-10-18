#!/bin/sh
# Public setup and in-place repair for hosts without repository access.
# POSIX sh + curl/python3/tar plus shasum or sha256sum only: resolves the
# pinned CPython runtime from runtimes.json, verifies every download by
# SHA-256, then runs the verified bundle installer. The feed is public: no
# token is needed.
# Usage:
#   sh bootstrap.sh [--channel=beta] [--choose-clients]
set -eu
FEED_ORIGIN="${FEED_ORIGIN:-https://dist.softwarecombined.com}"
CHANNEL="stable"
HOME_DIR="${ROUTER_HOME:-$HOME/.codex/mixed-model-router}"
if [ -f "$HOME_DIR/channel" ]; then
  saved_channel="$(cat "$HOME_DIR/channel")"
  case "$saved_channel" in stable|beta) CHANNEL="$saved_channel" ;; esac
fi
CHOOSE=""
for arg in "$@"; do
  case "$arg" in
    --channel=*) CHANNEL="${arg#--channel=}" ;;
    --choose-clients) CHOOSE="--choose-clients" ;;
    *) echo "usage: sh bootstrap.sh [--channel=beta] [--choose-clients]" >&2; exit 2 ;;
  esac
done
case "$CHANNEL" in
  stable|beta) ;;
  *) echo "error: channel must be stable or beta" >&2; exit 2 ;;
esac
OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS" in Darwin) OS=darwin ;; Linux) OS=linux ;; esac
case "$ARCH" in arm64|aarch64) ARCH=arm64 ;; x86_64|amd64) ARCH=x86_64 ;; esac
mkdir -p "$HOME_DIR"
chmod 700 "$HOME_DIR"
HOME_DIR="$(cd "$HOME_DIR" && pwd -P)"
REPAIR=""
if [ -e "$HOME_DIR/current" ] || [ -L "$HOME_DIR/current" ]; then
  REPAIR="--repair"
  echo "Updating or repairing SCG Router. Your key and saved choices stay in place."
fi
dl() {
  curl -fsSL "$FEED_ORIGIN/$1" -o "$2"
}
# Checksums read from stdin. Perl hosts ship shasum; GNU coreutils hosts
# (Amazon Linux, minimal images) ship sha256sum and no shasum. Either is
# enough; neither is a hard stop, never a skipped verification.
verify_sha256() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 -c -
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c -
  else
    echo "error: shasum or sha256sum is needed to verify downloads" >&2
    exit 1
  fi
}
dl "runtimes.json" "$HOME_DIR/runtimes.json"
TARGET="$OS/$ARCH"
export HOME_DIR TARGET
RT="$(python3 -c "import json,os;t=json.load(open(os.environ['HOME_DIR']+'/runtimes.json'))['targets'][os.environ['TARGET']];print(t['mirror'],t['sha256'],t['exec'])")"
set -- $RT; MIRROR="$1"; RSHA="$2"; REXEC="$3"
# Percent-encode the URL path: a raw '+' in an S3 key is decoded as a space
# at the edge and denied, and upstream runtime names carry '+' (3.14.7+DATE).
MIRROR_URL="$(python3 -c "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1], safe='/'))" "$MIRROR")"
PY="$HOME_DIR/runtime/$REXEC"
if ! "$PY" -c 'import sys,compression.zstd;assert sys.version_info >= (3,14)' >/dev/null 2>&1; then
  dl "$MIRROR_URL" "$HOME_DIR/runtime.tar.gz"
  echo "$RSHA  $HOME_DIR/runtime.tar.gz" | verify_sha256
  RUNTIME_DIR="$HOME_DIR/runtime"
  # A running Windows or POSIX service can still use the old runtime files.
  # Keep those files and stage a replacement beside them when repair needs one.
  if [ -d "$RUNTIME_DIR" ]; then RUNTIME_DIR="$RUNTIME_DIR/$RSHA"; fi
  mkdir -p "$RUNTIME_DIR"
  PY="$RUNTIME_DIR/$REXEC"
  if ! "$PY" -c 'import sys,compression.zstd;assert sys.version_info >= (3,14)' >/dev/null 2>&1; then
    tar -xzf "$HOME_DIR/runtime.tar.gz" -C "$RUNTIME_DIR"
  fi
fi
"$PY" -c "import compression.zstd; print('runtime ok')"
dl "$CHANNEL/latest.json" "$HOME_DIR/latest.json"
set -- $(python3 -c "import json,os;d=json.load(open(os.environ['HOME_DIR']+'/latest.json'));print(d['version'],d['url'],d['sha256'])")
VERSION="$1"; URL="$2"; SHA="$3"
ASSET="${URL##*/}"
dl "bundles/$ASSET" "$HOME_DIR/bundle.tar.gz"
echo "$SHA  $HOME_DIR/bundle.tar.gz" | verify_sha256
mkdir -p "$HOME_DIR/bootstrap"
tar -xzf "$HOME_DIR/bundle.tar.gz" -C "$HOME_DIR/bootstrap"
# Pin this run to the channel the operator asked for: the installer resolves
# its own feed from the router home, which may still name the old channel.
# Persist the channel only once the install proves out, so an aborted
# bootstrap cannot move a stable host onto pre-releases. A host already
# ahead of the requested channel is current, not deferred.
if "$PY" "$HOME_DIR/bootstrap/packaging/install.py" --home "$HOME_DIR" --python "$PY" \
     --feed "$FEED_ORIGIN/$CHANNEL/latest.json" ${REPAIR:+"$REPAIR"} ${CHOOSE:+"$CHOOSE"}; then
  CURRENT="$("$PY" -c 'import pathlib,sys;p=pathlib.Path(sys.argv[1]);print(p.resolve().name if p.is_symlink() and p.is_dir() else p.read_text().strip() if p.exists() else str())' "$HOME_DIR/current")"
else
  exit $?
fi
if ! python3 -c 'import sys;a,b=sys.argv[1:];sys.exit(0 if [int(p) for p in a.split(".")]>=[int(p) for p in b.split(".")] else 1)' "$CURRENT" "$VERSION"; then
  echo "install did not land $VERSION (current ${CURRENT:-none}); channel left unchanged" >&2
  exit 1
fi
# A channel switch invalidates the old channel's anti-replay serial.
if [ "$(cat "$HOME_DIR/channel" 2>/dev/null)" != "$CHANNEL" ]; then
  rm -f "$HOME_DIR/feed-serial"
fi
printf '%s\n' "$CHANNEL" > "$HOME_DIR/channel"
