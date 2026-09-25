#!/usr/bin/env bash
#
# flutter-builder doctor
# ----------------------
# Checks that a Flutter app repository is actually ready to produce a signed,
# cloud-connected, ad-carrying release — and names whatever is not.
#
# Run it from the ROOT OF YOUR APP REPOSITORY, not from flutter-builder:
#
#     bash /path/to/flutter-builder/scripts/doctor.sh
#     curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/main/scripts/doctor.sh | bash
#
# It never prints a secret value, only names, paths and lengths.
#
# Exit status: 0 = nothing broken, 1 = at least one FAIL.

set -uo pipefail
# deliberately no `set -e`: we want every check to run and collect all problems.

REPO_OVERRIDE=""
if [ "${1:-}" = "--repo" ]; then REPO_OVERRIDE="${2:-}"; fi

# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #
if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_GRN=$'\033[32m'
  C_DIM=$'\033[2m';  C_BLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_YEL=""; C_GRN=""; C_DIM=""; C_BLD=""; C_OFF=""
fi

PASS=0; FAIL=0; WARN=0
FAILED_ITEMS=()

pass() { printf '%s  PASS%s  %s\n'  "$C_GRN" "$C_OFF" "$*"; PASS=$((PASS+1)); }
fail() { printf '%s  FAIL%s  %s\n'  "$C_RED" "$C_OFF" "$*"; FAIL=$((FAIL+1)); FAILED_ITEMS+=("$1"); }
warn() { printf '%s  WARN%s  %s\n'  "$C_YEL" "$C_OFF" "$*"; WARN=$((WARN+1)); }
info() { printf '%s  ..  %s%s\n'    "$C_DIM" "$*" "$C_OFF"; }
head_() { printf '\n%s%s%s\n' "$C_BLD" "$*" "$C_OFF"; }

have() { command -v "$1" >/dev/null 2>&1; }

# version compare: ver_ge 1.6.0 1.7.0 -> true when 1.7.0 >= 1.6.0
ver_ge() { [ "$(printf '%s\n' "$1" "$2" | sort -V | head -1)" = "$1" ]; }

echo "${C_BLD}flutter-builder doctor${C_OFF}"
echo "======================"

# --------------------------------------------------------------------------- #
# 1. environment
# --------------------------------------------------------------------------- #
head_ "1. Environment"
for t in git python3 openssl; do
  have "$t" && pass "$t available" || fail "$t not found (required)"
done
if have gh; then
  pass "gh available"
  if gh auth status >/dev/null 2>&1; then pass "gh authenticated"
  else fail "gh is installed but not authenticated — run: gh auth login"; fi
else
  warn "gh not installed — GitHub secret checks will be skipped"
  warn "   install: brew install gh   (or https://cli.github.com)"
fi

# --------------------------------------------------------------------------- #
# 2. repository
# --------------------------------------------------------------------------- #
head_ "2. Repository"
if git rev-parse --git-dir >/dev/null 2>&1; then
  pass "inside a git repository"
else
  fail "not a git repository — run this from your app repo root"; exit 1
fi

REPO="$REPO_OVERRIDE"
if [ -z "$REPO" ] && have gh; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
fi
[ -n "$REPO" ] && pass "repository: $REPO" || info "repository: unknown"

if [ "$(git rev-parse --show-prefix 2>/dev/null)" = "" ] && \
   [ -f ".github/workflows/flutter-build.yml" ]; then
  warn "this looks like the flutter-builder repo itself — run doctor from your APP repo"
fi

# locate the Android / iOS modules
ANDROID_DIR=""; IOS_DIR=""
for d in android flutter_app/android .; do
  if [ -d "$d/app" ] && { [ -f "$d/app/build.gradle.kts" ] || [ -f "$d/app/build.gradle" ]; }; then
    ANDROID_DIR="$d/app"; break
  fi
done
for d in ios flutter_app/ios; do [ -d "$d/Runner" ] && IOS_DIR="$d/Runner" && break; done
[ -n "$ANDROID_DIR" ] && pass "Android module: $ANDROID_DIR" || warn "no Android module found"
[ -n "$IOS_DIR" ]     && pass "iOS module: $IOS_DIR"         || info "no iOS module (fine if you only ship Android)"

APP_ID=""
if [ -n "$ANDROID_DIR" ]; then
  for g in "$ANDROID_DIR/build.gradle.kts" "$ANDROID_DIR/build.gradle"; do
    [ -f "$g" ] || continue
    APP_ID="$(grep -oE 'applicationId[[:space:]]*=?[[:space:]]*"[^"]+"' "$g" | head -1 \
              | grep -oE '"[^"]+"' | tr -d '"' || true)"
    [ -n "$APP_ID" ] && break
  done
fi
[ -n "$APP_ID" ] && info "applicationId: $APP_ID"

# --------------------------------------------------------------------------- #
# 3. signing files
# --------------------------------------------------------------------------- #
head_ "3. Android signing"
KEYPROPS=""
for p in "${ANDROID_DIR%/app}/key.properties" android/key.properties \
         flutter_app/android/key.properties key.properties; do
  [ -f "$p" ] && KEYPROPS="$p" && break
done

if [ -n "$KEYPROPS" ]; then
  pass "key.properties found: $KEYPROPS"
  prop() { grep -E "^$1=" "$KEYPROPS" 2>/dev/null | head -1 | cut -d= -f2- || true; }
  for k in storePassword keyPassword keyAlias storeFile; do
    [ -n "$(prop "$k")" ] && pass "  $k present" || fail "  $k MISSING in key.properties"
  done
  STORE_FILE="$(prop storeFile)"
  case "$STORE_FILE" in
    /*) [ -f "$STORE_FILE" ] && pass "  keystore exists" || fail "  keystore not found: $STORE_FILE" ;;
    "") : ;;
    *)  if [ -f "$STORE_FILE" ]; then pass "  keystore exists"
        elif [ -f "${ANDROID_DIR%/app}/$STORE_FILE" ]; then pass "  keystore exists"
        else fail "  keystore not found: $STORE_FILE" ; fi ;;
  esac
  git ls-files --error-unmatch "$KEYPROPS" >/dev/null 2>&1 \
    && fail "  $KEYPROPS IS TRACKED BY GIT — remove it: git rm --cached $KEYPROPS" \
    || pass "  key.properties is not tracked by git"
else
  warn "no key.properties — release AAB signing cannot be configured"
  warn "   see docs/ANDROID_SIGNING.md"
fi

# --------------------------------------------------------------------------- #
# 4. Firebase client config
# --------------------------------------------------------------------------- #
head_ "4. Firebase client config"
if [ -n "$ANDROID_DIR" ]; then
  GS="$ANDROID_DIR/google-services.json"
  if [ -f "$GS" ]; then
    pass "google-services.json present locally"
    if python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$GS" 2>/dev/null; then
      pass "  valid JSON"
      PKGS="$(python3 - "$GS" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
p=[c.get("client_info",{}).get("android_client_info",{}).get("package_name")
   for c in d.get("client",[])]
print("\n".join(sorted({x for x in p if x})))
PY
)"
      [ -n "$PKGS" ] && info "  package(s): $(echo "$PKGS" | tr '\n' ' ')"
      if [ -n "$APP_ID" ] && [ -n "$PKGS" ]; then
        echo "$PKGS" | grep -qx "$APP_ID" \
          && pass "  package matches applicationId ($APP_ID)" \
          || fail "  PACKAGE MISMATCH: firebase has [$(echo "$PKGS"|tr '\n' ' ')] but app is $APP_ID — wrong file, Google Sign-In will fail"
      fi
    else
      fail "  INVALID JSON — an empty or truncated secret will look exactly like this"
    fi
    git ls-files --error-unmatch "$GS" >/dev/null 2>&1 \
      && fail "  google-services.json IS TRACKED BY GIT — git rm --cached $GS" \
      || pass "  not tracked by git"
  else
    warn "google-services.json not present locally"
    warn "   the build can still get it from the GOOGLE_SERVICES_JSON_BASE64 secret"
  fi
fi

if [ -n "$IOS_DIR" ]; then
  PL="$IOS_DIR/GoogleService-Info.plist"
  [ -f "$PL" ] && pass "GoogleService-Info.plist present" \
               || info "GoogleService-Info.plist absent (fine if you only ship Android)"
fi

# --------------------------------------------------------------------------- #
# 5. GitHub secrets & variables
# --------------------------------------------------------------------------- #
head_ "5. GitHub Actions secrets and variables"
if have gh && [ -n "$REPO" ] && gh auth status >/dev/null 2>&1; then
  have_names() {
    if [ "$1" = secret ]; then gh secret list   --repo "$REPO" --json name -q '.[].name' 2>/dev/null
    else                        gh variable list --repo "$REPO" --json name -q '.[].name' 2>/dev/null; fi | sort
  }
  want() { printf '%s\n' "$@" | sort; }
  report() { # report LABEL kind names...
    local label="$1" kind="$2"; shift 2
    local out; out="$(comm -23 <(want "$@") <(have_names "$kind"))"
    if [ -z "$out" ]; then pass "every required $label is present"
    else while IFS= read -r n; do [ -n "$n" ] && fail "  MISSING $label: $n"; done <<< "$out"; fi
  }
  report secret   secret   ANDROID_KEYSTORE_BASE64 KEYSTORE_PASSWORD KEY_ALIAS \
                           KEY_PASSWORD GOOGLE_SERVICES_JSON_BASE64
  report variable variable ADMOB_APP_ID ADMOB_BANNER_ID ADMOB_INTERSTITIAL_ID \
                           ADMOB_REWARDED_ID
  info "remember: an EMPTY secret still shows up as present here"
  info "gh cannot read values back — see section 7"
else
  warn "skipped (no gh, or not authenticated)"
fi

# --------------------------------------------------------------------------- #
# 6. workflow wiring
# --------------------------------------------------------------------------- #
head_ "6. Workflow wiring"
WF_DIR=".github/workflows"
if [ -d "$WF_DIR" ]; then
  WFS="$(ls "$WF_DIR"/*.yml "$WF_DIR"/*.yaml 2>/dev/null || true)"
  [ -n "$WFS" ] && pass "workflows found" || warn "no workflow files"

  MIN_VER="1.6.0"   # first release that writes google-services.json from a secret
  OLD=""
  for f in $WFS; do
    v="$(grep -oE 'flutter-builder/\.github/workflows/[a-zA-Z0-9._-]+\.yml@v[0-9][0-9.]*' "$f" \
         | grep -oE 'v[0-9][0-9.]*$' | tr -d 'v' | sort -V | head -1 || true)"
    [ -n "$v" ] || continue
    ver_ge "$MIN_VER" "$v" || OLD="$OLD"$'\n'"  $f pins @$v"
  done
  [ -z "$OLD" ] && pass "flutter-builder pinned to >= v$MIN_VER" \
                || fail "  OUTDATED builder (< v$MIN_VER) — google-services.json injection will not work:$OLD"

  # ${{ secrets.* }} inside a `with:` block kills the run with zero jobs
  BAD="$(awk '
    /^[[:space:]]*with:[[:space:]]*$/ { inw=1; next }
    /^[[:space:]]{0,4}[a-zA-Z_-]+:/  { inw=0 }
    inw && /\$\{\{[[:space:]]*secrets\./ { print FILENAME " line " FNR }
  ' $WFS 2>/dev/null || true)"
  [ -z "$BAD" ] && pass "no \${{ secrets.* }} inside with: blocks" \
                || fail "  \${{ secrets.* }} USED INSIDE with: — the run dies with zero jobs and no error:"$'\n'"$BAD"$'\n'"     use \${{ vars.* }} for dart-defines / build-env instead"

  # Is the Firebase secret actually forwarded? Only workflows that produce a
  # build artifact need it — a CI job that only runs analyze/test should NOT
  # receive secrets, so it is skipped rather than warned about.
  FWD=""
  for f in $WFS; do
    grep -q 'flutter-builder' "$f" || continue
    builds=no
    grep -qE 'build-(apk|aab):[[:space:]]*true' "$f" && builds=yes
    grep -q 'publish-release\.yml' "$f" && builds=yes
    [ "$builds" = yes ] || continue
    if grep -q 'secrets:[[:space:]]*inherit' "$f" || grep -q 'GOOGLE_SERVICES_JSON_BASE64' "$f"; then
      :
    else
      FWD="$FWD"$'\n'"  $f builds an artifact but does not forward GOOGLE_SERVICES_JSON_BASE64"
    fi
  done
  [ -z "$FWD" ] && pass "GOOGLE_SERVICES_JSON_BASE64 forwarded by every build workflow" \
                || warn "  workflow(s) that build but never receive the Firebase secret:$FWD"
else
  warn "no .github/workflows directory"
fi

# --------------------------------------------------------------------------- #
# 7. source hygiene
# --------------------------------------------------------------------------- #
head_ "7. Source hygiene (would the release gate fail?)"
LIB_DIR="${ANDROID_DIR%/app}"
for cand in lib "$LIB_DIR/lib" flutter_app/lib; do [ -d "$cand" ] && LIB="$cand" && break; done
LIB="${LIB:-lib}"

if [ -d "$LIB" ]; then
  HITS="$(grep -rlE 'ca-app-pub-3940256099942544' "$LIB" 2>/dev/null || true)"
  [ -z "$HITS" ] && pass "no Google test ad IDs under $LIB/" \
                 || fail "  GOOGLE TEST AD ID IN SOURCE — release gate will fail:"$'\n'"$HITS"
else
  info "no lib/ directory to scan"
fi

# A *production* AdMob app ID hardcoded in source. Google's own sample ID
# (3940256099942544) is deliberately excluded: keeping it as a Gradle fallback
# is safe, because the release gate only scans lib/ and the SDK never
# initialises without real unit IDs.
PROD="$(grep -rnE 'ca-app-pub-[0-9]{8,}~[0-9]+' --include='*.dart' --include='*.kts' \
        --include='*.xml' --include='*.gradle' . 2>/dev/null \
        | grep -v '^./.git' \
        | grep -v 'ca-app-pub-3940256099942544' \
        | cut -d: -f1 | sort -u || true)"
[ -z "$PROD" ] && pass "no production AdMob app ID hardcoded in source" \
               || warn "  production AdMob app ID hardcoded — move it to a secret/variable:"$'\n'"$PROD"

EX="$(grep -rlE 'com\.example\.' --include='*.dart' --include='*.kts' \
      --include='*.xml' --include='*.gradle' . 2>/dev/null | grep -v '^./.git' || true)"
[ -z "$EX" ] && pass "no com.example placeholders" \
             || warn "  com.example placeholders present:"$'\n'"$EX"

TRACKED="$(git ls-files | grep -E '(google-services\.json|GoogleService-Info\.plist|key\.properties|\.jks$|\.keystore$)' || true)"
[ -z "$TRACKED" ] && pass "no secrets/config tracked by git" \
                  || fail "  SECRET FILES STILL TRACKED BY GIT:"$'\n'"$TRACKED"

# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #
echo
echo "======================"
printf '%sSummary:%s %s%d passed%s, %s%d warnings%s, %s%d failures%s\n' \
  "$C_BLD" "$C_OFF" "$C_GRN" "$PASS" "$C_OFF" "$C_YEL" "$WARN" "$C_OFF" \
  "$([ "$FAIL" -gt 0 ] && echo "$C_RED" || echo "$C_DIM")" "$FAIL" "$C_OFF"

if [ "$FAIL" -gt 0 ]; then
  echo
  echo "${C_BLD}Fix these first:${C_OFF}"
  n=0
  for it in "${FAILED_ITEMS[@]}"; do n=$((n+1)); echo "  $n. $it"; done
fi

echo
echo "${C_DIM}One thing doctor can never check: whether a secret's VALUE is empty.${C_OFF}"
echo "${C_DIM}Run a real build and grep the log for:${C_OFF}"
echo "${C_DIM}  OK: android/app/google-services.json is valid JSON${C_OFF}"
echo "${C_DIM}No such line = GOOGLE_SERVICES_JSON_BASE64 is empty. Re-set it with:${C_OFF}"
echo "${C_DIM}  openssl base64 -A -in ${ANDROID_DIR:-android/app}/google-services.json | gh secret set GOOGLE_SERVICES_JSON_BASE64${C_OFF}"

[ "$FAIL" -gt 0 ] && exit 1 || exit 0
