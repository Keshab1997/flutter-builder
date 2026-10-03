#!/usr/bin/env bash
# Capture screenshots of a built Flutter web app.
#
# Why web and not an emulator: a GitHub runner can start an Android emulator,
# but it costs 10-15 minutes per run, and driving the app to a second screen
# needs integration tests the project may not have. A web build starts in
# about a minute, needs no device, and is good enough to answer the question
# the workflow exists for - "what does this screen look like now?" - for every
# app that supports web. Apps that use platform-only plugins (camera,
# bluetooth, local notifications) will not run on web; for those, use a manual
# Android build.
#
#   bash scripts/capture-screenshots.sh \
#     --build-dir build/web --out ui-screenshots \
#     --routes /,/settings --viewports 390x844,768x1024
#
# This script owns the server, the browser download and the summary; the
# screenshotting itself (polling until the page really painted, plus console
# diagnostics when it did not) lives in capture-pages.cjs next to it.
#
# Output: <out>/*.png plus manifest.tsv, consumed by embed-screenshots.sh.
# Needs: node + npm (playwright is installed into a temporary directory),
# curl, and network on the first run.
set -euo pipefail

# Pinned so a new playwright release cannot change the images between runs.
# Bump deliberately; tests/test_ui_screenshots.py asserts this line.
PLAYWRIGHT_VERSION="${PLAYWRIGHT_VERSION:-1.49.0}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

BUILD_DIR="build/web"
OUT="ui-screenshots"
ROUTES="/"
VIEWPORTS="390x844"
# 12 s before the first shot, then poll up to 60 s in total. A cold release
# build has to fetch and boot CanvasKit (~6 MB) before it paints anything, and
# the first CI run of this pipeline photographed a white page at 6 s.
WAIT_MS=12000
MAX_WAIT_MS=60000
MIN_KB=5
SELECTOR=""
PORT=8080

usage() {
  cat <<'HELP'
Capture screenshots of a built Flutter web app.

  --build-dir DIR      directory holding index.html (default: build/web)
  --out DIR            where the PNGs and manifest.tsv go (default: ui-screenshots)
  --routes LIST        comma separated app routes (default: /)
                       '/' becomes #/, '/settings' becomes #/settings - the
                       default Flutter web URL strategy is hash based.
  --viewports LIST     comma separated WxH pairs (default: 390x844, a phone)
  --wait-ms MS         pause between polls (default: 12000)
  --max-wait-ms MS     give up on a page after this long (default: 60000)
  --min-kb KB          below this size a shot is treated as blank (default: 5)
  --wait-for-selector S
                       also wait for a CSS selector (for example `flutter-view`)
  --port PORT          local port for the static server (default: 8080)
  -h, --help           this text

Run `flutter build web --release` first; this script never invokes Flutter.
HELP
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --build-dir) BUILD_DIR="${2:?--build-dir needs a value}"; shift 2 ;;
    --out)       OUT="${2:?--out needs a value}"; shift 2 ;;
    --routes)    ROUTES="${2:?--routes needs a value}"; shift 2 ;;
    --viewports) VIEWPORTS="${2:?--viewports needs a value}"; shift 2 ;;
    --wait-ms)   WAIT_MS="${2:?--wait-ms needs a value}"; shift 2 ;;
    --max-wait-ms) MAX_WAIT_MS="${2:?--max-wait-ms needs a value}"; shift 2 ;;
    --min-kb)    MIN_KB="${2:?--min-kb needs a value}"; shift 2 ;;
    --wait-for-selector) SELECTOR="${2:?--wait-for-selector needs a value}"; shift 2 ;;
    --port)      PORT="${2:?--port needs a value}"; shift 2 ;;
    -h|--help)   usage; exit 0 ;;
    *) printf 'capture-screenshots: unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -f "$BUILD_DIR/index.html" ] || {
  printf 'capture-screenshots: %s/index.html not found - run `flutter build web --release` first.\n' "$BUILD_DIR" >&2
  exit 2
}
for tool in node npm curl; do
  command -v "$tool" >/dev/null 2>&1 || {
    printf 'capture-screenshots: %s is required.\n' "$tool" >&2
    exit 2
  }
done

mkdir -p "$OUT"
rm -f "$OUT"/*.png
manifest="$OUT/manifest.tsv"
: > "$manifest"

server_pid=""
workdir=""
cleanup() {
  if [ -n "$server_pid" ]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  [ -n "$workdir" ] && rm -rf -- "$workdir"
  return 0
}
trap cleanup EXIT

# http-server rather than `python3 -m http.server`: the Python one serves .wasm
# as application/octet-stream, which makes CanvasKit fall back and can leave a
# blank canvas behind the screenshot.
printf 'Serving %s on 127.0.0.1:%s\n' "$BUILD_DIR" "$PORT"
npx --yes http-server "$BUILD_DIR" -a 127.0.0.1 -p "$PORT" -s >/dev/null 2>&1 &
server_pid=$!

ready=false
for _ in $(seq 1 30); do
  if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/index.html"; then
    ready=true
    break
  fi
  sleep 1
done
[ "$ready" = true ] || {
  printf 'capture-screenshots: the static server never answered on port %s.\n' "$PORT" >&2
  exit 1
}

# --with-deps apt-installs the libraries chromium needs; it needs root, which
# GitHub runners have and a dev machine usually does not. Falling back to the
# browser alone keeps local runs working where the libraries already exist, and
# the failure message says what to do when they do not.
printf 'Preparing chromium for playwright@%s (cached after the first run)\n' "$PLAYWRIGHT_VERSION"
if ! npx --yes "playwright@${PLAYWRIGHT_VERSION}" install --with-deps chromium >/dev/null 2>&1; then
  printf '  --with-deps failed (needs root); trying the browser alone\n'
  npx --yes "playwright@${PLAYWRIGHT_VERSION}" install chromium >/dev/null 2>&1 || {
    printf 'capture-screenshots: chromium could not be installed.\n' >&2
    printf '  Debian/Ubuntu:  sudo npx playwright@%s install --with-deps chromium\n' "$PLAYWRIGHT_VERSION" >&2
    exit 1
  }
fi

# The playwright *module* (not just the CLI) is needed to import it. Installed
# into a temp directory so nothing lands in the app repository, and without its
# own browser download because the browser is already there.
workdir="$(mktemp -d)"
printf 'Installing the playwright module into %s\n' "$workdir"
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --prefix "$workdir" --no-save \
  --no-package-lock --no-audit --no-fund "playwright@${PLAYWRIGHT_VERSION}" >/dev/null 2>&1 || {
  printf 'capture-screenshots: npm could not install playwright@%s.\n' "$PLAYWRIGHT_VERSION" >&2
  exit 1
}

printf 'Capturing %s at %s\n' "$ROUTES" "$VIEWPORTS"
NODE_PATH="$workdir/node_modules" node "$SCRIPT_DIR/capture-pages.cjs" \
  --out "$OUT" \
  --base-url "http://127.0.0.1:${PORT}" \
  --routes "$ROUTES" \
  --viewports "$VIEWPORTS" \
  --wait-ms "$WAIT_MS" \
  --max-wait-ms "$MAX_WAIT_MS" \
  --min-bytes "$((MIN_KB * 1024))" \
  ${SELECTOR:+--selector "$SELECTOR"}

printf '\n%-40s %-16s %-10s %s\n' "file" "route" "viewport" "size"
small=0
taken=0
while IFS=$'\t' read -r name route viewport size colors _share; do
  [ -n "$name" ] || continue
  printf '%-40s %-16s %-10s %s KB, %s colours\n' \
    "$name.png" "$route" "$viewport" "$((size / 1024))" "$colors"
  taken=$((taken + 1))
  # A flat screen (<= 2 colours) is what a page that never painted looks like;
  # see pngStats() in capture-pages.cjs for why size alone cannot say this.
  if [ "$colors" -le 2 ] 2>/dev/null; then small=$((small + 1)); fi
done < "$manifest"

[ "$taken" -gt 0 ] || {
  printf 'capture-screenshots: nothing was captured.\n' >&2
  exit 1
}
printf '\ncapture-screenshots: %s screenshot(s) in %s' "$taken" "$OUT"
if [ "$small" -gt 0 ]; then
  printf ' (%s still blank after %s ms - the diagnostics above say why)' \
    "$small" "$MAX_WAIT_MS"
fi
printf '\n'
