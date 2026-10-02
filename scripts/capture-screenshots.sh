#!/usr/bin/env bash
# Capture screenshots of a built Flutter web app.
#
# Why web and not an emulator: a GitHub runner can start an Android emulator,
# but it costs 10-15 minutes per run, and driving the app to a second screen
# needs integration tests the project may not have. A web build starts in
# about a minute, needs no device, and is good enough to answer the question
# the workflow exists for - "what does this screen look like now?" - for every
# app that supports web. Apps that use platform-only plugins (camera,
# bluetooth, local notifications) will not run on web; for those, use the
# Android emulator lane or a manual build.
#
#   bash scripts/capture-screenshots.sh \
#     --build-dir build/web --out ui-screenshots \
#     --routes /,/settings --viewports 390x844,768x1024 --wait-ms 8000
#
# Output: <out>/*.png plus a manifest.tsv consumed by embed-screenshots.sh.
# Needs: node (for npx), python3 not required, network for the first run
# (http-server and playwright/chromium are downloaded and then cached).
set -euo pipefail

# Pinned so a new playwright release cannot change the images between runs.
# Bump deliberately; the same value is asserted by tests/test_ui_screenshots.py.
PLAYWRIGHT_VERSION="${PLAYWRIGHT_VERSION:-1.49.0}"

BUILD_DIR="build/web"
OUT="ui-screenshots"
ROUTES="/"
VIEWPORTS="390x844"
# 12 s, not 8: the wait only starts after the page's load event, and a cold
# release build still has to fetch and boot CanvasKit (~6 MB) before the first
# frame. The first CI run of this script produced a solid white 390x844 PNG at
# 6 s, which is exactly that.
WAIT_MS=12000
RETRIES=2
MIN_KB=5
WAIT_FOR_SELECTOR=""
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
  --wait-ms MS         settle time before each shot (default: 12000; raise it
                       on a slow runner - a cold CanvasKit boot is ~15 s)
  --retries N          extra attempts when a shot looks blank, each waiting
                       twice as long (default: 2)
  --min-kb KB          below this size a shot is treated as blank (default: 5)
  --wait-for-selector S
                       wait for a CSS selector before shooting (for example
                       `flutter-view`); empty waits only for --wait-ms
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
    --retries)   RETRIES="${2:?--retries needs a value}"; shift 2 ;;
    --min-kb)    MIN_KB="${2:?--min-kb needs a value}"; shift 2 ;;
    --wait-for-selector) WAIT_FOR_SELECTOR="${2:?--wait-for-selector needs a value}"; shift 2 ;;
    --port)      PORT="${2:?--port needs a value}"; shift 2 ;;
    -h|--help)   usage; exit 0 ;;
    *) printf 'capture-screenshots: unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -f "$BUILD_DIR/index.html" ] || {
  printf 'capture-screenshots: %s/index.html not found - run `flutter build web --release` first.\n' "$BUILD_DIR" >&2
  exit 2
}
command -v node >/dev/null 2>&1 || {
  printf 'capture-screenshots: node is required (playwright runs through npx).\n' >&2
  exit 2
}
command -v curl >/dev/null 2>&1 || {
  printf 'capture-screenshots: curl is required to wait for the static server.\n' >&2
  exit 2
}

mkdir -p "$OUT"
rm -f "$OUT"/*.png
manifest="$OUT/manifest.tsv"
: > "$manifest"

server_pid=""
cleanup() {
  if [ -n "$server_pid" ]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
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

# --with-deps apt-installs the system libraries chromium needs; it needs root,
# which GitHub runners have and a dev machine usually does not. Falling back to
# the browser alone keeps local runs working wherever the libraries are
# already present, and the failure message below says what to do when they are
# not. The download itself is cached in ~/.cache/ms-playwright afterwards.
printf 'Preparing chromium for playwright@%s (cached after the first run)\n' "$PLAYWRIGHT_VERSION"
if ! npx --yes "playwright@${PLAYWRIGHT_VERSION}" install --with-deps chromium >/dev/null 2>&1; then
  printf '  --with-deps failed (needs root); trying the browser alone\n'
  npx --yes "playwright@${PLAYWRIGHT_VERSION}" install chromium >/dev/null 2>&1 || {
    printf 'capture-screenshots: chromium could not be installed.\n' >&2
    printf '  Debian/Ubuntu:  sudo npx playwright@%s install --with-deps chromium\n' "$PLAYWRIGHT_VERSION" >&2
    exit 1
  }
fi

slug() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -e 's#[^a-z0-9]\+#-#g' -e 's#^-\{1,\}##' -e 's#-\{1,\}$##'
}

taken=0
small=0

IFS=',' read -r -a route_list <<< "$ROUTES"
IFS=',' read -r -a viewport_list <<< "$VIEWPORTS"

for viewport in "${viewport_list[@]}"; do
  viewport="$(printf '%s' "$viewport" | tr -d ' ')"
  width="${viewport%%x*}"
  height="${viewport##*x}"
  for route in "${route_list[@]}"; do
    route="$(printf '%s' "$route" | tr -d ' ')"
    case "$route" in
      '#'|'#/') fragment="#/" ;;
      '#'*)     fragment="$route" ;;
      '/'|'')   fragment="#/" ;;
      *)        fragment="#$route" ;;
    esac
    route_slug="$(slug "${route}")"
    [ -n "$route_slug" ] || route_slug="home"   # '/' slugs to nothing
    name="${route_slug}-${width}x${height}"
    file="$OUT/$name.png"
    url="http://127.0.0.1:${PORT}/${fragment}"
    printf '  -> %-24s %sx%s\n' "$route" "$width" "$height"
    delay="$WAIT_MS"
    attempt=0
    min_bytes=$((MIN_KB * 1024))
    while : ; do
      selector_args=()
      [ -n "$WAIT_FOR_SELECTOR" ] && selector_args=(--wait-for-selector "$WAIT_FOR_SELECTOR")
      npx --yes "playwright@${PLAYWRIGHT_VERSION}" screenshot \
        --viewport-size="${width},${height}" \
        --wait-for-timeout="$delay" \
        ${selector_args[@]+"${selector_args[@]}"} \
        "$url" "$file" >/dev/null
      size="$(wc -c < "$file")"
      if [ "$size" -ge "$min_bytes" ] || [ "$attempt" -ge "$RETRIES" ]; then
        break
      fi
      attempt=$((attempt + 1))
      delay=$((delay * 2))
      [ "$delay" -le 60000 ] || delay=60000
      printf '     .. only %s KB after %ss - retry %s with %ss\n' \
        "$((size / 1024))" "$((delay / 2))" "$attempt" "$delay"
    done
    printf '%s\t%s\t%s\t%s\n' "$name" "$route" "${width}x${height}" "$size" >> "$manifest"
    if [ "$size" -lt "$min_bytes" ]; then
      # A solid-colour canvas compresses to a couple of KB even after every
      # retry; that is the shape of a blank screen - the app needs longer than
      # 60 s, a platform-only plugin is missing on web, or the route threw.
      printf '     ! %s is only %s KB after %ss - still blank, check the app\n' \
        "$name.png" "$((size / 1024))" "$delay"
      small=$((small + 1))
    fi
    taken=$((taken + 1))
  done
done

printf '\n%-40s %-16s %-10s %s\n' "file" "route" "viewport" "size"
while IFS=$'\t' read -r name route viewport size; do
  printf '%-40s %-16s %-10s %s KB\n' "$name.png" "$route" "$viewport" "$((size / 1024))"
done < "$manifest"

[ "$taken" -gt 0 ] || {
  printf 'capture-screenshots: nothing was captured.\n' >&2
  exit 1
}
printf '\ncapture-screenshots: %s screenshot(s) in %s' "$taken" "$OUT"
if [ "$small" -gt 0 ]; then
  printf ' (%s small enough to be blank - check the app really renders)' "$small"
fi
printf '\n'
