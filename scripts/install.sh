#!/usr/bin/env bash
# Install the flutter-builder caller workflows into an existing Flutter repo.
# This file is self-contained so it also works when streamed through curl | bash.
set -euo pipefail

DEFAULT_REF=v1.8.0
REUSABLE=Keshab1997/flutter-builder/.github/workflows
FILES=(ci.yml manual-build.yml publish-release.yml release.yml web-preview.yml)

say() { printf '[flutter-builder] %s\n' "$*"; }
fail() { printf '[flutter-builder] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'HELP'
Install GitHub Actions callers for a Flutter project (no Flutter SDK needed).

Run from your project directory (or any directory inside its Git repository):
  curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.8.0/scripts/install.sh | bash

Options when running a downloaded/local script:
  --app-dir DIR     Flutter app directory, relative to the Git repository root
  --app-name NAME   Display name for GitHub Releases (default: pubspec name)
  --ref REF         Pin the reusable workflows to a tag/SHA (default: v1.8.0)
  --dry-run         Show changes without writing files
  --force           Replace differing workflows, backing up originals first
  -h, --help        Show this help

Options over a pipe: curl -fsSL URL | bash -s -- --app-dir apps/mobile --app-name "My App"
Installs ci.yml, manual-build.yml, publish-release.yml, release.yml and web-preview.yml into
.github/workflows/ at the Git repository root. Never adds GitHub secrets or
pushes code. Only --force may replace an existing workflow.
HELP
}

is_flutter_pubspec() {
  [ -f "$1" ] && grep -Eq "^[[:space:]]*sdk:[[:space:]]*['\\\"]?flutter['\\\"]?([[:space:]]*(#.*)?)?$" "$1"
}

yaml_quote() {
  local value="$1"
  value="${value//\\/\\\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '"%s"' "$value"
}

app_dir_arg=''
app_name=''
ref="$DEFAULT_REF"
force=false
dry_run=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --app-dir|--app-name|--ref)
      option="$1"
      [ "$#" -ge 2 ] && [ -n "$2" ] || fail "$option requires a nonempty value."
      case "$option" in
        --app-dir) app_dir_arg="$2" ;;
        --app-name) app_name="$2" ;;
        --ref) ref="$2" ;;
      esac
      shift 2 ;;
    --force) force=true; shift ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1 (try --help)." ;;
  esac
done

# A ref must be a tag-like name or a full commit SHA; no branch/URL/expression
# interpolation in a generated workflow. The bundled publish wrapper must be
# available under the chosen ref too.
if [[ ! "$ref" =~ ^v[0-9]+(\.[0-9]+){1,2}(-[A-Za-z0-9][A-Za-z0-9.-]*)?$ &&
      ! "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
  fail "Invalid --ref '$ref'. Use a version tag (e.g. v1.5.0) or a 40-character commit SHA."
fi
if [[ "$app_name" == *'${{'* || "$app_name" == *$'\n'* || "$app_name" == *$'\r'* || "$app_name" == *$'\t'* ]]; then
  fail "--app-name must be one line and cannot contain GitHub expressions."
fi

invoked_from="$(pwd -P)"
repo_root="$invoked_from"
if command -v git >/dev/null 2>&1 && git -C "$invoked_from" rev-parse --show-toplevel >/dev/null 2>&1; then
  repo_root="$(git -C "$invoked_from" rev-parse --show-toplevel)"
  repo_root="$(cd -- "$repo_root" && pwd -P)"
fi

if [ -n "$app_dir_arg" ]; then
  [ -d "$repo_root/$app_dir_arg" ] || fail "No such directory: $app_dir_arg (relative to $repo_root)."
  app_path="$(cd -- "$repo_root/$app_dir_arg" && pwd -P)"
  is_flutter_pubspec "$app_path/pubspec.yaml" || fail "Not a Flutter project: $app_dir_arg (expected pubspec.yaml with sdk: flutter)."
elif is_flutter_pubspec "$invoked_from/pubspec.yaml"; then
  app_path="$invoked_from"
else
  # Do not pick one at random in a monorepo. Ignore generated/dependency dirs.
  candidates=()
  while IFS= read -r -d '' pubspec; do
    if is_flutter_pubspec "$pubspec"; then
      candidates+=("${pubspec%/pubspec.yaml}")
    fi
  done < <(find "$repo_root" \
    -type d \( -name .git -o -name .dart_tool -o -name .fvm -o -name build \
      -o -name node_modules -o -name Pods -o -name .pub-cache \) -prune -o \
    -type f -name pubspec.yaml -print0)
  case "${#candidates[@]}" in
    0) fail "No Flutter pubspec.yaml found under $repo_root. Run from a Flutter project or pass --app-dir." ;;
    1) app_path="$(cd -- "${candidates[0]}" && pwd -P)" ;;
    *)
      printf '[flutter-builder] Multiple Flutter projects found:\n' >&2
      for path in "${candidates[@]}"; do printf '  %s\n' "$path" >&2; done
      fail "Choose one with --app-dir DIR (relative to the Git repository root)." ;;
  esac
fi

# Canonicalize paths: do not generate workflows that point outside the repo.
case "$app_path" in
  "$repo_root") app_dir='.' ;;
  "$repo_root"/*) app_dir="${app_path#"$repo_root"/}" ;;
  *) fail "Flutter project is outside the Git repository root: $app_path" ;;
esac
if [[ "$app_dir" == *'${{'* || "$app_dir" == *$'\n'* || "$app_dir" == *$'\r'* || "$app_dir" == *$'\t'* ]]; then
  fail "Flutter directory cannot contain GitHub expressions or control characters."
fi

# Never write through symlinks in the GitHub configuration tree.
[ ! -L "$repo_root/.github" ] || fail ".github is a symlink; refusing to follow it."
[ ! -e "$repo_root/.github" ] || [ -d "$repo_root/.github" ] || fail ".github is not a directory."
[ ! -L "$repo_root/.github/workflows" ] || fail ".github/workflows is a symlink; refusing to follow it."
[ ! -e "$repo_root/.github/workflows" ] || [ -d "$repo_root/.github/workflows" ] || fail ".github/workflows is not a directory."

yaml_dir="$(yaml_quote "$app_dir")"
stage="$(mktemp -d)"
trap 'rm -rf -- "$stage"' EXIT

# Literal heredocs preserve GitHub's ${{ ... }} expressions when this script
# is executed via a pipe. Only the uses ref, working-directory and optional
# release display name are dynamic.
{
  cat <<'YAML'
name: Flutter CI

# Validates every branch and pull request. No Android artifacts on push.
on:
  pull_request:
  push:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  ci:
YAML
  printf '    uses: %s/flutter-build.yml@%s\n' "$REUSABLE" "$ref"
  cat <<'YAML'
    with:
      flutter-channel: stable
YAML
  printf '      working-directory: %s\n' "$yaml_dir"
  cat <<'YAML'
      run-format-check: true
      run-analyze: true
      run-tests: true
      code-coverage: true
      build-apk: false
      build-aab: false
YAML
} > "$stage/ci.yml"

{
  cat <<'YAML'
name: Manual Android Build

# Actions -> Manual Android Build -> Run workflow. AAB requires signing secrets.
on:
  workflow_dispatch:
    inputs:
      format:
        description: Which Android file should be built?
        required: true
        type: choice
        options:
          - apk
          - aab
        default: apk

permissions:
  contents: read

jobs:
  build:
YAML
  printf '    uses: %s/flutter-build.yml@%s\n' "$REUSABLE" "$ref"
  cat <<'YAML'
    with:
      flutter-channel: stable
YAML
  printf '      working-directory: %s\n' "$yaml_dir"
  cat <<'YAML'
      build-apk: ${{ inputs.format == 'apk' }}
      build-aab: ${{ inputs.format == 'aab' }}
      artifact-retention-days: 14
    secrets:
      ANDROID_KEYSTORE_BASE64: ${{ secrets.ANDROID_KEYSTORE_BASE64 }}
      KEYSTORE_PASSWORD: ${{ secrets.KEYSTORE_PASSWORD }}
      KEY_ALIAS: ${{ secrets.KEY_ALIAS }}
      KEY_PASSWORD: ${{ secrets.KEY_PASSWORD }}
YAML
} > "$stage/manual-build.yml"

{
  cat <<'YAML'
name: Publish Android Release

# Manual only: builds a signed APK/AAB, creates a version tag and GitHub Release.
# The reusable publish wrapper enforces version and placeholder safety checks.
on:
  workflow_dispatch:
    inputs:
      draft:
        description: Create the GitHub Release as a draft?
        required: false
        type: boolean
        default: false
      prerelease:
        description: Mark this as a prerelease?
        required: false
        type: boolean
        default: false

permissions:
  contents: write

jobs:
  publish:
YAML
  printf '    uses: %s/publish-release.yml@%s\n' "$REUSABLE" "$ref"
  cat <<'YAML'
    with:
YAML
  printf '      working-directory: %s\n' "$yaml_dir"
  if [ -n "$app_name" ]; then
    printf '      app-name: %s\n' "$(yaml_quote "$app_name")"
  fi
  cat <<'YAML'
      release-draft: ${{ inputs.draft }}
      release-prerelease: ${{ inputs.prerelease }}
    secrets: inherit
YAML
} > "$stage/publish-release.yml"

{
  cat <<'YAML'
name: Android Release (tag build only)

# Pushing a v* tag builds a signed AAB artifact; it does not publish a Release.
on:
  push:
    tags:
      - "v*"

permissions:
  contents: read

jobs:
  release-aab:
YAML
  printf '    uses: %s/flutter-build.yml@%s\n' "$REUSABLE" "$ref"
  cat <<'YAML'
    with:
      flutter-channel: stable
YAML
  printf '      working-directory: %s\n' "$yaml_dir"
  cat <<'YAML'
      build-apk: false
      build-aab: true
      artifact-retention-days: 30
    secrets:
      ANDROID_KEYSTORE_BASE64: ${{ secrets.ANDROID_KEYSTORE_BASE64 }}
      KEYSTORE_PASSWORD: ${{ secrets.KEYSTORE_PASSWORD }}
      KEY_ALIAS: ${{ secrets.KEY_ALIAS }}
      KEY_PASSWORD: ${{ secrets.KEY_PASSWORD }}
YAML
} > "$stage/release.yml"


{
  cat <<'YAML'
name: Web Preview

# Builds the app for the web on every push and pull request and publishes it
# to GitHub Pages under preview/<branch>: test the app by opening a URL in a
# browser instead of installing an APK. One-time setup: Settings -> Pages ->
# Build and deployment -> Deploy from a branch -> gh-pages (root); the first
# run creates the branch. Needs the web platform (flutter create --platforms
# web .); plugins without web support will not work in the preview.
on:
  push:
  pull_request:

permissions:
  contents: write
  pull-requests: write

concurrency:
  group: web-preview-${{ github.ref }}
  cancel-in-progress: true

jobs:
  preview:
YAML
  printf '    uses: %s/web-preview.yml@%s\n' "$REUSABLE" "$ref"
  cat <<'YAML'
    with:
YAML
  printf '      working-directory: %s\n' "$yaml_dir"
  cat <<'YAML'
      comment-on-pr: true
    secrets: inherit
YAML
} > "$stage/web-preview.yml"

workflows="$repo_root/.github/workflows"
changes=()
conflicts=()
say "Flutter project: $app_dir (repository: $repo_root)"
say "Reusable workflow pin: @$ref"
for file in "${FILES[@]}"; do
  dest="$workflows/$file"
  [ ! -L "$dest" ] || fail "$dest is a symlink; refusing to replace it."
  if [ -e "$dest" ]; then
    [ -f "$dest" ] || fail "$dest exists but is not a regular file."
    if cmp -s "$stage/$file" "$dest"; then
      say "Already current: .github/workflows/$file"
      continue
    fi
    conflicts+=("$file")
    if [ "$force" = true ]; then
      say "Will replace (backup first): .github/workflows/$file"
    else
      say "CONFLICT (left untouched): .github/workflows/$file"
    fi
  else
    say "Will add: .github/workflows/$file"
  fi
  changes+=("$file")
done

if [ "${#conflicts[@]}" -gt 0 ] && [ "$force" = false ]; then
  fail "Existing workflow(s) differ; nothing was changed. Review them, or rerun with --force to back them up and replace them."
fi
if [ "${#changes[@]}" -eq 0 ]; then
  say "All ${#FILES[@]} workflows are already installed; nothing changed."
  exit 0
fi
if [ "$dry_run" = true ]; then
  say "Dry run: no files were changed."
  exit 0
fi

if [ "${#conflicts[@]}" -gt 0 ]; then
  backups="$repo_root/.github/flutter-builder-backups"
  [ ! -L "$backups" ] || fail "$backups is a symlink; refusing to write through it."
  [ ! -e "$backups" ] || [ -d "$backups" ] || fail "$backups is not a directory."
  mkdir -p -- "$backups"
  backup_dir="$(mktemp -d "$backups/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXXXX")"
  for file in "${conflicts[@]}"; do
    cp -p -- "$workflows/$file" "$backup_dir/$file"
  done
  say "Originals backed up to: $backup_dir"
fi

mkdir -p -- "$workflows"
for file in "${changes[@]}"; do
  # Use a temporary file in the destination directory for an atomic rename.
  (
    temp="$(mktemp "$workflows/.$file.tmp.XXXXXX")"
    trap 'rm -f -- "$temp"' EXIT
    cp -- "$stage/$file" "$temp"
    chmod 644 "$temp"
    mv -f -- "$temp" "$workflows/$file"
  )
  say "Installed: .github/workflows/$file"
done
say "Done. Review and commit .github/workflows/; no git push or release was triggered."
if [ ! -d "$app_path/android" ]; then
  say "Note: android/ is missing; Android builds need an Android platform and signing configuration."
fi
say "Before AAB/release builds, configure Android signing secrets and replace any placeholder IDs."
