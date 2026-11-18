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
  # A pipe in a route (or name) would open a phantom column in the table.
  name_cell="${name//|/\\|}"
  route_cell="${route//|/\\|}"
  # A non-numeric size (a hand-edited or foreign manifest) must not take the
  # step down under bash arithmetic; print it verbatim instead.
  if [[ "$size" =~ ^[0-9]+$ ]]; then
    size_cell="$((size / 1024)) KB"
  else
    size_cell="$size"
  fi
  if [ -n "${colours:-}" ] && [ "$colours" -ge 0 ] 2>/dev/null; then
    printf '| `%s.png` | `%s` | %s | %s | %s |\n' \
      "$name_cell" "$route_cell" "$viewport" "$size_cell" "$colours"
  else
    printf '| `%s.png` | `%s` | %s | %s | |\n' \
      "$name_cell" "$route_cell" "$viewport" "$size_cell"
  fi
done < "$manifest"
printf '\n'
