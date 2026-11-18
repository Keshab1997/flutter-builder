# capture-hardening — Worker C

**Repository:** `Keshab1997/flutter-builder` — continue in your existing attached Arena chat on `arena/e0563147-flutter-builder` (base `6efb8b1b8e4e8318e2cff779946003cb7a812cb4`).
**Goal and acceptance:** Fix screenshot polling/decoding edge cases in the UI capture scripts and add fast offline tests (no browser launch, no network):
1. `scripts/capture-pages.cjs`:
   - In the screenshot poll loop, run `pngStats(shot)` on each newly captured buffer: immediately keep and stop on a non-blank shot even if its PNG byte size is smaller than an earlier blank frame, and while still blank compare `shot.length` against `best.length` (not the previous iteration's `bytes`) and keep `bytes`/`stats` matched to `best`.
   - When navigation/screenshot fails and no PNG was written, do **not** append a phantom row to `manifest.tsv` for the missing file (still record the failure in `results` and console diagnostics).
   - Disambiguate colliding route slugs within a run (e.g. `/a/b` and `/a-b` must not silently overwrite the same `<slug>-<WxH>.png`).
   - Harden `pngStats()` so truncated PNG chunks (`pos + 12 + length > buffer.length`), short `IHDR` (`data.length < 13`), corrupt zlib `IDAT` streams, truncated inflated buffers, or unknown PNG filter types return `null` cleanly instead of throwing.
   - Validate numeric `--wait-ms` (>= 0), `--max-wait-ms` (>= 0), `--min-bytes` (>= 0) and every `WxH` viewport (positive integers) before launching Chromium; add `--url-strategy` (`hash` default, `path` opt-in so path-routed Flutter web apps visit `<base><route>` instead of `<base>/#<route>`); always close `browser` in a `finally` block; export pure helpers (`parseArgs`, `pngStats`, `looksBlank`, `slug`, `fragment`, URL/filename builders) when `require()`d and only run `main()` when `require.main === module`.
2. `scripts/capture-screenshots.sh`: add `--url-strategy hash|path` (default `hash`, forwarded to `capture-pages.cjs`) and validate `--wait-ms`, `--max-wait-ms`, `--min-kb`, `--port`, and `--url-strategy` up front with exit code `2` on bad values.
3. `scripts/manifest-summary.sh`: escape `|` in `name` and `route` cells so routes containing pipes never break `$GITHUB_STEP_SUMMARY` tables, and guard non-numeric `size` values instead of crashing under bash arithmetic.
4. Add offline `tests/test_capture_pages.py` running `node` unit checks on `capture-pages.cjs` (valid solid vs multi-colour PNGs, all PNG filter types, truncated/corrupt PNGs returning `null`, `parseArgs` validation, `hash` vs `path` URL building, colliding route slug disambiguation, poll frame selection helper) plus subprocess tests for `manifest-summary.sh` (4-col, 6-col, pipe-in-route, non-numeric size, missing file) and `capture-screenshots.sh` argument validation. Full `python3 -m pytest -q tests` and `bash -n scripts/capture-screenshots.sh scripts/manifest-summary.sh` must pass.

**Interface / exclusions:** Preserve every existing assertion in `tests/test_ui_screenshots.py` (keep `PLAYWRIGHT_VERSION="${PLAYWRIGHT_VERSION:-1.49.0}"`, `--lang=en-US`, `--enable-unsafe-swiftshader`, `locale: 'en-US'`, `Accept-Language`, `flutter-view`, `flt-glass-pane`, 6-column `manifest.tsv` format, and all existing CLI flags/defaults). Keep shell scripts bash-3.2 compatible under `set -euo pipefail`. Do not run `npm install` or download Playwright; do not touch `.github/workflows/` or any file outside `allowed`.
**Scope and gate:** See [task.json](task.json) at this same commit. Do not edit it.
**Report:** Post on https://github.com/Keshab1997/flutter-builder/issues/10 mentioning `@Keshab1997` (or report in worker chat with `MENTION PENDING` if commenting is unavailable).

Use the current agent-bootstrap `captain/FASTLANE.md`. Keep the real `arena/*`
branch. After a verified `PUSHED`, include the brief link, checkpoint block
and commit link when reporting. If blocked, report the reason; do not change
branch, use a standalone clone, re-pair, run CI, or open/merge/close a PR.
