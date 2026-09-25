# Agent prompt — set this project's GitHub Actions secrets from local files

Hand this file to a coding agent. It finds the signing and Firebase files on
your disk, encodes them, and pushes them into GitHub Actions — **without ever
printing a value into the chat**.

Copy §1 into the agent, keep §2–§6 in the repository so the agent can read them.

---

## 1. Paste this to your agent

```text
Set up the GitHub Actions secrets and variables for this repository by
following docs/AGENT_SECRETS_SETUP.md (from Keshab1997/flutter-builder).

Rules:
- Never print, echo or cat a secret value into this conversation, a log or a
  file. Report only: name, kind (secret/variable), source file, byte count.
- Never guess a missing value. Skip it and list it under "Still needed".
- Run the verification block in section 5 and paste its output.

End your reply with:
1. a table of what was set (name / kind / source / size)
2. a "Still needed" list
3. the verification output
```

---

## 2. Rules the agent must follow

1. **Never use `base64 -w0`.** macOS ships BSD `base64`, which has no `-w`
   flag: the command fails, prints nothing, and `gh secret set` then stores an
   **empty value** while still printing "✓ Set Actions secret". Use
   `openssl base64 -A` — identical output, works on macOS and Linux.
2. **Never set a value you have not measured.** Every helper below refuses
   anything shorter than 40 characters. A 0-byte secret produces a green build
   with silently missing Firebase config.
3. **Never print a value.** Not to stdout, not into the conversation, not into
   a file. Print the *length*.
4. **Never commit the source files.** If `google-services.json`,
   `GoogleService-Info.plist`, `key.properties` or a `.jks` is tracked by git,
   stop and say so instead of setting the secret.
5. **Skip, don't guess.** A missing keystore is not an error — report it.

---

## 3. What gets set

| Name | Kind | Source |
|---|---|---|
| `ANDROID_KEYSTORE_BASE64` | secret | base64 of the upload keystore (`.jks`), path from `key.properties` |
| `KEYSTORE_PASSWORD` | secret | `key.properties` → `storePassword` |
| `KEY_ALIAS` | secret | `key.properties` → `keyAlias` |
| `KEY_PASSWORD` | secret | `key.properties` → `keyPassword` |
| `GOOGLE_SERVICES_JSON_BASE64` | secret | base64 of `android/app/google-services.json` |
| `GOOGLE_SERVICES_PLIST_BASE64` | secret | base64 of `ios/Runner/GoogleService-Info.plist` (iOS only) |
| `PLAY_SERVICE_ACCOUNT_JSON` | secret | Play service-account JSON (only if you upload to Play from CI) |
| `FIREBASE_SERVICE_CREDENTIALS` | secret | Firebase service-account JSON (only for App Distribution) |
| `ADMOB_APP_ID` | **variable** | AdMob → Apps → your app → App ID |
| `ADMOB_BANNER_ID` | **variable** | AdMob ad unit |
| `ADMOB_INTERSTITIAL_ID` | **variable** | AdMob ad unit |
| `ADMOB_REWARDED_ID` | **variable** | AdMob ad unit |

> **Why variables for AdMob?** GitHub does not expose the `secrets` context
> inside a reusable workflow's `with:` inputs — `${{ secrets.X }}` there makes
> the run die with zero jobs and no error. The `vars` context is available, and
> AdMob IDs are public identifiers compiled into every APK anyway.

---

## 4. The script

Save as `/tmp/set-secrets.sh` and run from the repository root. Safe to re-run.

```bash
#!/usr/bin/env bash
# Sets every secret/variable the shared Flutter builder needs, from local files.
set -euo pipefail

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "Repository: $REPO"

# --- locate the Android / iOS modules -------------------------------------
ANDROID_DIR=""; IOS_DIR=""
for d in android flutter_app/android .; do
  [ -d "$d/app" ] && [ -f "$d/app/build.gradle.kts" -o -f "$d/app/build.gradle" ] \
    && ANDROID_DIR="$d/app" && break
done
for d in ios flutter_app/ios; do
  [ -d "$d/Runner" ] && IOS_DIR="$d/Runner" && break
done
echo "Android module: ${ANDROID_DIR:-none}   iOS module: ${IOS_DIR:-none}"

# --- helpers ---------------------------------------------------------------
# openssl base64 -A = one line, on macOS (BSD) and Linux (GNU) alike.
b64() { openssl base64 -A -in "$1"; }

set_secret_file() {            # set_secret_file NAME FILE
  local name="$1" file="$2" value
  if [ ! -f "$file" ]; then echo "SKIP   $name  ($file not found)"; return 0; fi
  value="$(b64 "$file")"
  if [ "${#value}" -lt 40 ]; then
    echo "FAIL   $name  ($file encoded to ${#value} chars - refusing to set)"
    return 1
  fi
  printf '%s' "$value" | gh secret set "$name" --repo "$REPO"
  echo "OK     $name  <- $file  (${#value} chars)"
}

set_value() {                  # set_value NAME VALUE   (secret)
  [ -n "${2:-}" ] || { echo "SKIP   $1  (no value)"; return 0; }
  gh secret set "$1" --repo "$REPO" -b "$2"
  echo "OK     $1  (secret, ${#2} chars)"
}

set_var() {                    # set_var NAME VALUE     (variable)
  [ -n "${2:-}" ] || { echo "SKIP   $1  (no value)"; return 0; }
  gh variable set "$1" --repo "$REPO" -b "$2"
  echo "OK     $1  (variable, ${#2} chars)"
}

prop() { grep -E "^$1=" "$2" 2>/dev/null | head -1 | cut -d= -f2- || true; }

# --- 1. Android signing ----------------------------------------------------
KEYPROPS=""
for p in "$ANDROID_DIR/../key.properties" android/key.properties \
         flutter_app/android/key.properties key.properties; do
  [ -f "$p" ] && KEYPROPS="$p" && break
done

if [ -n "$KEYPROPS" ]; then
  echo "Reading signing config from $KEYPROPS (values are not printed)"
  STORE_FILE="$(prop storeFile "$KEYPROPS")"
  [ -f "$STORE_FILE" ] || STORE_FILE="$ANDROID_DIR/../$STORE_FILE"
  set_secret_file ANDROID_KEYSTORE_BASE64 "${STORE_FILE:-}"
  set_value KEYSTORE_PASSWORD "$(prop storePassword "$KEYPROPS")"
  set_value KEY_ALIAS         "$(prop keyAlias      "$KEYPROPS")"
  set_value KEY_PASSWORD      "$(prop keyPassword   "$KEYPROPS")"
else
  echo "SKIP   Android signing  (no key.properties found - see section 6)"
fi

# --- 2. Firebase client config --------------------------------------------
[ -n "$ANDROID_DIR" ] && \
  set_secret_file GOOGLE_SERVICES_JSON_BASE64 "$ANDROID_DIR/google-services.json"
[ -n "$IOS_DIR" ] && \
  set_secret_file GOOGLE_SERVICES_PLIST_BASE64 "$IOS_DIR/GoogleService-Info.plist"

# --- 3. Optional distribution credentials ---------------------------------
# Uncomment and point at your own files if you use these features.
# set_value PLAY_SERVICE_ACCOUNT_JSON "$(cat ~/keys/play-service-account.json)"
# set_value FIREBASE_SERVICE_CREDENTIALS "$(cat ~/keys/firebase-service.json)"

# --- 4. AdMob IDs (variables, not secrets) --------------------------------
# Ask the human for these - they are not on disk. Leave empty to skip.
# set_var ADMOB_APP_ID            "ca-app-pub-XXXXXXXXXXXXXXXX~YYYYYYYYYY"
# set_var ADMOB_BANNER_ID         "ca-app-pub-XXXXXXXXXXXXXXXX/ZZZZZZZZZZ"
# set_var ADMOB_INTERSTITIAL_ID   "ca-app-pub-XXXXXXXXXXXXXXXX/ZZZZZZZZZZ"
# set_var ADMOB_REWARDED_ID       "ca-app-pub-XXXXXXXXXXXXXXXX/ZZZZZZZZZZ"

echo "--- done ---"
```

Then run the AdMob block for real, filled in with the IDs the human gives you:

```bash
gh variable set ADMOB_APP_ID          --repo "$REPO" -b "ca-app-pub-...~..."
gh variable set ADMOB_BANNER_ID       --repo "$REPO" -b "ca-app-pub-.../..."
gh variable set ADMOB_INTERSTITIAL_ID --repo "$REPO" -b "ca-app-pub-.../..."
gh variable set ADMOB_REWARDED_ID     --repo "$REPO" -b "ca-app-pub-.../..."
```

---

## 5. Verification (the agent must run this)

`gh` can never read a secret back, so presence plus a fresh timestamp is the
only local proof:

```bash
echo "--- secrets (Updated must be TODAY) ---"
gh secret list --repo "$REPO"
echo "--- variables ---"
gh variable list --repo "$REPO"
```

Then run a real build and read the log — this is the only check that proves the
*content* is right:

```bash
gh workflow run manual-build.yml --repo "$REPO" -f format=aab   # name may differ
gh run watch --repo "$REPO"
```

| Log line | Meaning |
|---|---|
| `OK: android/app/google-services.json is valid JSON` | `GOOGLE_SERVICES_JSON_BASE64` decoded correctly 🔴 most important |
| `OK: ios/Runner/GoogleService-Info.plist is valid` | iOS config decoded correctly |
| `Dart defines (values hidden): ADMOB_APP_ID, …` | AdMob variables reached the compile |
| `No release placeholders found.` | no test IDs or `com.example` left in the source |

**Missing the first line means the secret is still empty** — re-run step 2 of
the script and check it printed `OK … (3468 chars)`, not `SKIP` or `FAIL`.

---

## 6. When something is missing

| Missing | What to tell the human |
|---|---|
| `key.properties` | Generate an upload keystore and write `android/key.properties` (`storePassword`, `keyPassword`, `keyAlias`, `storeFile`). Ask them — never invent one. |
| `google-services.json` | Firebase Console → Project settings → Your apps → download it into `android/app/`. |
| `GoogleService-Info.plist` | Same page, iOS app. iOS-only; skip if not shipping iOS. |
| AdMob IDs | AdMob → Apps → your app → App ID, and the three ad unit IDs. |

Do not continue with a guessed value. List it under "Still needed".

---

## 7. Hardening that no secret can do for you

Setting secrets does not close the two real holes:

1. **Restrict the Firebase API key** — Google Cloud Console → APIs & Services →
   Credentials → the `AIzaSy…` key → restrict to *Android apps* with your
   package name and every SHA-1 fingerprint. Without this, anyone holding your
   `google-services.json` (which may already be in git history) can spend your
   quota.
2. **Turn on Firebase App Check** with Play Integrity and enforce it for
   Firestore and Authentication. This is what actually blocks unauthorized
   clients.
