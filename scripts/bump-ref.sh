#!/usr/bin/env bash
# Move existing Keshab1997/flutter-builder caller workflows to a new pin.
#
# Unlike install.sh --force this rewrites ONLY the @ref on `uses:` lines, so a
# customised caller (extra jobs, comments, inputs, dispatch options) keeps every
# local change. Self-contained so it also works when streamed through curl | bash.
set -euo pipefail

DEFAULT_REF=v1.12.0
REUSABLE='Keshab1997/flutter-builder/.github/workflows/'
# sed pattern: literal repo path with dots escaped
SED_PREFIX='Keshab1997/flutter-builder/\.github/workflows/'

say() { printf '[bump-ref] %s\n' "$*"; }
fail() { printf '[bump-ref] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'HELP'
Bump Keshab1997/flutter-builder pins in an existing Flutter app repository.

Run from the project directory (or anywhere inside its Git repository):
  curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.12.0/scripts/bump-ref.sh | bash

Options when running a downloaded/local script:
  --ref REF   New pin: a version tag (e.g. v1.12.0) or a 40-character commit
              SHA (default: v1.12.0)
  --dry-run   Show what would change without writing files
  -h, --help  Show this help

Every `uses: Keshab1997/flutter-builder/.github/workflows/<file>.yml@<ref>` line
under .github/workflows/ is rewritten to the new pin and nothing else in the
file is touched, so custom jobs and comments survive. Pins to other
repositories (actions/checkout, ...) are ignored. Run it in each project after
a new flutter-builder release; see also install.sh --force, which replaces the
whole workflow files instead.
HELP
}

ref="$DEFAULT_REF"
dry_run=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --ref)
      [ "$#" -ge 2 ] && [ -n "$2" ] || fail "--ref requires a nonempty value."
      ref="$2"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1 (try --help)." ;;
  esac
done

# Same rule as install.sh: a version tag or a full commit SHA; no branch names
# or expressions can end up inside a workflow file.
if [[ ! "$ref" =~ ^v[0-9]+(\.[0-9]+){1,2}(-[A-Za-z0-9][A-Za-z0-9.-]*)?$ &&
      ! "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
  fail "Invalid --ref '$ref'. Use a version tag (e.g. v1.12.0) or a 40-character commit SHA."
fi

invoked_from="$(pwd -P)"
repo_root="$invoked_from"
if command -v git >/dev/null 2>&1 && git -C "$invoked_from" rev-parse --show-toplevel >/dev/null 2>&1; then
  repo_root="$(git -C "$invoked_from" rev-parse --show-toplevel)"
  repo_root="$(cd -- "$repo_root" && pwd -P)"
fi

workflows="$repo_root/.github/workflows"
[ -d "$workflows" ] || fail "No .github/workflows under $repo_root - run from a repository that already has flutter-builder callers."

pin_re="${SED_PREFIX}[A-Za-z0-9_.-]+\.ya?ml@[^[:space:]#\"']+"
changed=0
unchanged=0
total_pins=0

say "Repository: $repo_root"
say "Target pin: @$ref"
for file in "$workflows"/*.yml "$workflows"/*.yaml; do
  [ -e "$file" ] || continue
  grep -q "$REUSABLE" "$file" || continue
  pins=$(grep -oE "$pin_re" "$file" | wc -l | tr -d ' ' || true)
  total_pins=$((total_pins + pins))
  old_refs=$(grep -oE "$pin_re" "$file" | sed 's/.*@//' | sort -u | tr '\n' ' ' | sed 's/ $//' || true)
  name=".github/workflows/$(basename "$file")"

  tmp="$(mktemp)"
  sed -E "s#(${SED_PREFIX}[A-Za-z0-9_.-]+\.ya?ml)@[^[:space:]#\"']+#\1@${ref}#g" "$file" > "$tmp"
  if cmp -s "$file" "$tmp"; then
    rm -f -- "$tmp"
    unchanged=$((unchanged + 1))
    say "already current ($pins pins): $name"
    continue
  fi
  changed=$((changed + 1))
  if [ "$dry_run" = true ]; then
    rm -f -- "$tmp"
    say "would update ($pins pins: $old_refs -> $ref): $name"
    continue
  fi
  chmod 644 "$tmp"
  mv -f -- "$tmp" "$file"
  say "updated ($pins pins: $old_refs -> $ref): $name"
done

if [ "$total_pins" -eq 0 ]; then
  fail "No flutter-builder pins found under $workflows. Wrong directory, or not installed yet (see scripts/install.sh)."
fi

if [ "$dry_run" = true ]; then
  say "Dry run: $changed file(s) would change, $unchanged already current. No files were written."
else
  say "Done: $changed file(s) updated, $unchanged already current. Review with git diff and commit."
fi
