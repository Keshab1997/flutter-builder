#!/usr/bin/env bash
# Print the capture manifest as a markdown table.
#
#   bash scripts/manifest-summary.sh <manifest.tsv> [title]
#
# The manifest has one row per screenshot and lives next to the PNGs; the
# columns are
#
#   name  route  viewport  bytes  distinct-colours  top-colour-share
#
# and only the first four are guaranteed - a manifest written by an older
# capture script has just those (see pngStats() in capture-pages.cjs). This is
# the single place that parses it: the reusable workflow used to inline this
# loop with four columns, and when the manifest grew the blank-screen columns
# the step started dying on `$((size / 1024))` with the error token
# "1491\t0.867" - a failure in a step whose whole job is to print a table.
#
# Output goes to stdout so callers can append it to $GITHUB_STEP_SUMMARY:
#   bash scripts/manifest-summary.sh ui-screenshots/manifest.tsv >> "$GITHUB_STEP_SUMMARY"
set -euo pipefail

manifest="${1:-manifest.tsv}"
title="${2:-UI screenshots}"

[ -f "$manifest" ] || exit 0

printf '## %s\n\n' "$title"
printf '| file | route | viewport | size | colours |\n'
printf '|---|---|---|---|---|\n'
# Trailing columns are optional: the last variable on a `read` line absorbs
# whatever is left, so name/route/viewport/size stay correct either way.
while IFS=$'\t' read -r name route viewport size colours _share; do
  [ -n "$name" ] || continue
  if [ -n "${colours:-}" ] && [ "$colours" -ge 0 ] 2>/dev/null; then
    printf '| `%s.png` | `%s` | %s | %s KB | %s |\n' \
      "$name" "$route" "$viewport" "$((size / 1024))" "$colours"
  else
    printf '| `%s.png` | `%s` | %s | %s KB | |\n' \
      "$name" "$route" "$viewport" "$((size / 1024))"
  fi
done < "$manifest"
printf '\n'
