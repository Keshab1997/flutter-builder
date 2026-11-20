#!/usr/bin/env bash
# Install the flutter-builder caller workflows into an existing Flutter repo.
# This file is self-contained so it also works when streamed through curl | bash.
set -euo pipefail

DEFAULT_REF=v1.18.7
REUSABLE=Keshab1997/flutter-builder/.github/workflows
FILES=(ci.yml manual-build.yml publish-release.yml web-preview.yml)

say() { printf '[flutter-builder] %s\n' "$*"; }
fail() { printf '[flutter-builder] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'HELP'
Install GitHub Actions callers for a Flutter project (no Flutter SDK needed).

Run from your project directory (or any directory inside its Git repository):
  curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.18.7/scripts/install.sh | bash

Options when running a downloaded/local script:
  --app-dir DIR           Flutter app directory, relative to the Git repository root
  --app-name NAME         Display name for GitHub Releases (default: the app's android:label, else the pubspec name)
  --ref REF               Pin the reusable workflows to a tag/SHA (default: v1.18.7)
  --with-screenshots      Also install ui-screenshots.yml (manual UI screenshot caller)
  --with-widget-tests     Also install widget-tests.yml (manual widget-test diagnostics caller)
  --dry-run               Show changes without writing files
  --force                 Replace differing workflows, backing up originals first
  -h, --help              Show this help

Options over a pipe: curl -fsSL URL | bash -s -- --app-dir apps/mobile --app-name "My App"
Installs ci.yml, manual-build.yml, publish-release.yml and web-preview.yml into
.github/workflows/ at the Git repository root; the two --with-* flags add
ui-screenshots.yml and widget-tests.yml on top of those four. web-preview.yml
also removes a branch's preview from gh-pages when that branch is deleted, and
keeps the repository's About -> Website link on the default branch's preview
when a credential is configured (see the README). Never adds GitHub secrets or
pushes code. Only --force may replace an existing workflow.
--force replaces whole files; to move an existing install to a new @ref
without touching customised workflows, use scripts/bump-ref.sh.
HELP
}

is_flutter_pubspec() {
  [ -f "$1" ] && grep -Eq "^[[:space:]]*sdk:[[:space:]]*['\\\"]?flutter['\\\"]?([[:space:]]*(#.*)?)?$" "$1"
}

yaml_quote() {
  # sed instead of ${var//pattern/replacement}: bash 5.2 point releases
  # changed how backslashes inside quoted replacement strings are interpreted,
  # which silently doubled every backslash in the output on Ubuntu 24.04's
  # bash 5.2.21. sed is deterministic everywhere. Callers validate that the
  # value is a single line without control characters before calling this.
  printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
}

app_dir_arg=''
app_name=''
ref="$DEFAULT_REF"
force=false
dry_run=false
with_screenshots=false
with_widget_tests=false
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
    --with-screenshots) with_screenshots=true; shift ;;
    --with-widget-tests) with_widget_tests=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1 (try --help)." ;;
  esac
done
# The four standard callers always install; the two diagnostic callers are
# opt-in, so the default run installs exactly what it used to.
if [ "$with_screenshots" = true ]; then FILES+=(ui-screenshots.yml); fi
if [ "$with_widget_tests" = true ]; then FILES+=(widget-tests.yml); fi

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
# Play release notes belong to the repository, not to the app directory: the
# generated caller points at the root copy, stepping out of a subdirectory app.
if [ "$app_dir" = "." ]; then
  notes_input='distribution/whatsnew'
else
  notes_input='../distribution/whatsnew'
fi
stage="$(mktemp -d)"
trap 'rm -rf -- "$stage"' EXIT

# Literal heredocs preserve GitHub's ${{ ... }} expressions when this script
# is executed via a pipe. Only the uses ref, working-directory and optional
# release display name are dynamic.
{
  cat <<'YAML'
name: Flutter CI — Format, Analyze & Test

# Manual only: nothing runs on push or pull request. Batch your changes, then
# run this once from Actions -> Flutter CI — Format, Analyze & Test -> Run
# workflow. That keeps small edits from spending a CI run each.
on:
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
name: Build Android APK or AAB (Manual)

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
      # Optional for apps using ImgBB; extractable from the built APK/AAB.
      IMGBB_API_KEY: ${{ secrets.IMGBB_API_KEY }}
YAML
} > "$stage/manual-build.yml"

{
  cat <<'YAML'
name: Publish Signed Android Release

# Manual only: builds a signed APK/AAB, creates a version tag and GitHub Release.
# The reusable publish wrapper enforces version and placeholder safety checks.
# Play upload is opt-in per run; the package name is read from the Gradle
# applicationId unless package_name overrides it. Release notes for Play live in
# distribution/whatsnew/ at the repository root (one whatsnew-<locale> file per
# locale) — edit them before each release.
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
      upload_to_play_internal:
        description: Also upload the signed AAB to Google Play Internal testing?
        required: false
        type: boolean
        default: false
      package_name:
        description: Play package name override (leave blank to read android/app/build.gradle)
        required: false
        type: string

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
YAML
  # The notes directory is resolved against working-directory, so an app in a
  # subdirectory reaches the repository-root notes with '../'.
  cat <<YAML
      play-track: \${{ inputs.upload_to_play_internal && 'internal' || '' }}
      play-package-name: \${{ inputs.package_name }}
      play-whats-new-directory: \${{ inputs.upload_to_play_internal && '$notes_input' || '' }}
      play-status: completed
YAML
  cat <<'YAML'
    secrets: inherit
YAML
} > "$stage/publish-release.yml"

{
  cat <<'YAML'
name: Deploy Flutter Web Preview (GitHub Pages)

# Builds the app for the web and publishes it to GitHub Pages under
# preview/<slug>: test the app by opening a URL in a browser instead of
# installing an APK. It refreshes automatically on relevant branch pushes;
# documentation/workflow-only changes are ignored. Same-repo PR comments are
# updated from the push run, avoiding duplicate builds. Use Run workflow for a
# one-off rebuild. One-time setup: Settings -> Pages -> Build and deployment ->
# Deploy from a branch -> gh-pages (root); the first run creates the branch.
# Needs the web platform (flutter create --platforms web .); plugins without web
# support will not work in the preview.
on:
  push:
    branches:
      - '**'
      - '!gh-pages'
      - '!ui-screenshots'
    paths-ignore:
      - '**/*.md'
      - 'docs/**'
      - 'distribution/**'
      - '.github/**'
      - 'LICENSE'
  workflow_dispatch:
  delete:

permissions:
  contents: write
  pull-requests: write

# All previews of one repository share a single lane, because they share one
# gh-pages branch. Every writer runs alone: the deploy action pushes with a
# compare-and-swap and refuses a push when another run moved the branch in the
# meantime ("cannot lock ref ... is expected"). Branch push is the sole
# automatic preview trigger, so a PR-branch update does not start a duplicate
# pull_request run. Queueing also keeps a deleted branch's cleanup from
# cancelling, or being cancelled by, the deploy of the default branch.
concurrency:
  group: web-preview
  cancel-in-progress: false

jobs:
  preview:
    if: github.event_name != 'delete'
YAML
  printf '    uses: %s/web-preview.yml@%s\n' "$REUSABLE" "$ref"
  cat <<'YAML'
    with:
YAML
  printf '      working-directory: %s\n' "$yaml_dir"
  cat <<'YAML'
      comment-on-pr: true
      # Keeps Settings -> About -> Website on the preview of the default branch.
      # Needs a credential: the APP_PRIVATE_KEY secret + an APP_ID variable, or
      # an ABOUT_LINK_TOKEN secret, both with administration: write. Without one
      # the job prints a notice and changes nothing.
      set-about-link: true
      app-id: ${{ vars.APP_ID }}
    secrets: inherit

  # Deleting a branch removes its preview again: the cleanup job below runs on
  # the `delete` event, so gh-pages does not keep a web bundle for every dead
  # branch. GitHub runs delete-triggered workflows from the default branch, so
  # merge this file before relying on that.
  cleanup:
    if: github.event_name == 'delete' && github.event.ref_type == 'branch'
YAML
  printf '    uses: %s/preview-cleanup.yml@%s\n' "$REUSABLE" "$ref"
  cat <<'YAML'
    with:
      branch-name: ${{ github.event.ref }}
    permissions:
      contents: write
YAML
} > "$stage/web-preview.yml"

# Optional callers, installed only with --with-screenshots /
# --with-widget-tests. Same shape as the examples/project-workflows/ callers:
# manual only, pinned to the same ref, and the resolved working-directory is
# baked in like the standard four.
if [ "$with_screenshots" = true ]; then
{
  cat <<'YAML'
name: Flutter UI screenshots

# Actions -> "Flutter UI screenshots" -> Run workflow, typing the routes you
# want photographed (`/settings,/profile`). It is manual only: nothing runs on
# a push or pull request. An agent can drive it too - `python3
# tool/see_screen.py --route /settings` from the flutter-builder agent pack
# dispatches this, waits and downloads the images, so a change can be *looked
# at* instead of guessed at.
#
# The app needs web support (`web/` in the repository, or set
# `generate-web-platform: true` below). Apps that use platform-only plugins
# (camera, bluetooth, local notifications) will not render on web - the
# capture step reports a blank screen instead of showing one silently.
on:
  workflow_dispatch:
    inputs:
      routes:
        description: Comma separated app routes to photograph, e.g. /settings,/profile
        required: false
        default: "/"
      viewports:
        description: Comma separated WxH viewports
        required: false
        default: "390x844,768x1024"
      wait-ms:
        description: Milliseconds to let the app settle before each screenshot
        required: false
        default: "8000"
      dart-defines:
        description: Compile-time defines, one KEY=VALUE per line (never secrets)
        required: false
        default: ""
      note:
        description: Free text shown in the run name (see_screen.py sets this)
        required: false
        default: ""

# The note makes a dispatched run findable: see_screen.py searches for the run
# it just started by this title instead of guessing from timestamps.
run-name: Flutter UI screenshots${{ inputs.note && format(' — {0}', inputs.note) || '' }}

# Both are required: `contents: write` to push the images to the
# `ui-screenshots` branch, `pull-requests: write` to comment them.
permissions:
  contents: write
  pull-requests: write

concurrency:
  group: ui-screenshots-${{ github.ref }}
  cancel-in-progress: true

jobs:
  ui:
YAML
  printf '    uses: %s/ui-screenshots.yml@%s\n' "$REUSABLE" "$ref"
  cat <<'YAML'
    with:
      flutter-channel: stable
YAML
  printf '      working-directory: %s\n' "$yaml_dir"
  cat <<'YAML'
      # List the screens this app actually has. `/` is the home screen; for
      # anything deeper, give the route the app navigates to (`/settings`,
      # `/profile`) or wire up an integration test. A dispatched run overrides
      # this with the routes typed into the form / passed by see_screen.py.
      routes: ${{ inputs.routes || '/' }}
      viewports: ${{ inputs.viewports || '390x844,768x1024' }}
      # `wait-ms` is a number in the reusable workflow, so the form's string is
      # converted; the hyphenated input names need the bracket syntax.
      wait-ms: ${{ fromJSON(inputs['wait-ms'] || '8000') }}
      dart-defines: ${{ inputs['dart-defines'] || '' }}
      # Apps that have never been built for the web have no web/ folder and
      # `flutter build web` would fail. Set this once and the workflow generates
      # the folder inside its own checkout (`flutter create --platforms=web .`):
      # generate-web-platform: true
      embed-in-pr: true
    secrets: inherit
YAML
} > "$stage/ui-screenshots.yml"
fi

if [ "$with_widget_tests" = true ]; then
{
  cat <<'YAML'
name: Flutter widget-test diagnostics

# Actions -> Flutter widget-test diagnostics -> Run workflow for a fast
# debug-mode check and a copyable error report. It is manual only: nothing
# runs on a push or pull request.
#
# The tests must build the screen/route being checked. For a mobile overflow,
# write the widget test at a phone-sized viewport; this workflow does not
# launch an emulator or navigate the app by itself.
on:
  workflow_dispatch:
    inputs:
      flutter-channel:
        description: Flutter channel
        required: false
        type: choice
        options:
          - stable
          - beta
          - master
        default: stable
      test-target:
        description: Test file or directory (for example test/widget_test.dart)
        required: false
        type: string
        default: test
      codegen:
        description: Code generation required before tests
        required: false
        type: choice
        options:
          - none
          - build_runner
          - gen-l10n
          - both
        default: none
      test-concurrency:
        description: 0 uses Flutter's default; a positive number limits workers
        required: false
        type: number
        default: 0

run-name: Flutter widget tests — ${{ inputs['test-target'] || 'test' }}

permissions:
  contents: read

concurrency:
  group: widget-tests-${{ github.ref }}
  cancel-in-progress: true

jobs:
  widget-tests:
YAML
  printf '    uses: %s/flutter-widget-tests.yml@%s\n' "$REUSABLE" "$ref"
  cat <<'YAML'
    with:
YAML
  printf '      working-directory: %s\n' "$yaml_dir"
  cat <<'YAML'
      flutter-channel: ${{ inputs['flutter-channel'] || 'stable' }}
      test-target: ${{ inputs['test-target'] || 'test' }}
      codegen: ${{ inputs.codegen || 'none' }}
      test-concurrency: ${{ inputs['test-concurrency'] || 0 }}
YAML
} > "$stage/widget-tests.yml"
fi

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

# Play release notes live at the repository root — callers pass
# '../distribution/whatsnew' when the app sits in a subdirectory, because the
# path is resolved against working-directory. Without the directory the Play
# upload stops on its first release, so seed it here; a file that already
# exists is never touched, since only a human knows what a release actually
# changed.
notes_dir="$repo_root/distribution/whatsnew"
if [ ! -e "$notes_dir" ]; then
  [ ! -L "$notes_dir" ] || fail "$notes_dir is a symlink; refusing to write through it."
  mkdir -p -- "$notes_dir"
fi
for notes_file in whatsnew-en-US whatsnew-bn-BD; do
  target="$notes_dir/$notes_file"
  [ -e "$target" ] && continue
  if [ "$notes_file" = "whatsnew-en-US" ]; then
    notes_text='Internal testing build with the latest changes. Please try the app and share any issues or feedback with the team.'
  else
    notes_text='নতুন পরিবর্তনসহ অভ্যন্তরীণ পরীক্ষার বিল্ড। অ্যাপটি ব্যবহার করে কোনো সমস্যা বা মতামত থাকলে টিমকে জানান।'
  fi
  printf '%s\n' "$notes_text" > "$target"
  say "Seeded: distribution/whatsnew/$notes_file (edit it before each Play release)"
done

say "Done. Review and commit .github/workflows/; no git push or release was triggered."
if [ ! -d "$app_path/android" ]; then
  say "Note: android/ is missing; Android builds need an Android platform and signing configuration."
fi
say "Before AAB/release builds, configure Android signing secrets and replace any placeholder IDs."
