# hub-and-embed — Worker C

**Repository:** `Keshab1997/flutter-builder` — continue in your existing attached Arena chat on `arena/e0563147-flutter-builder` (base `700e2e76d046b47c25cba0ce3467086ff6cff12a`).
**Goal and acceptance:** Prepare `scripts/preview-hub.sh` for deleted-branch cleanup refreshes, harden `scripts/embed-screenshots.sh`, and add offline behaviour tests:
1. `scripts/preview-hub.sh`: add `--remove NAME` (removes `NAME` from the listed directories even if the GitHub Contents API is briefly stale, and does **not** insert a deployed label) and `--refresh` (rebuilds `<preview-dir>/index.html` from the live directory listing without inserting a fallback label). When zero branch previews remain, still write `<preview-dir>/index.html` with a clear empty-state message (`No active branch previews.`) instead of an empty list, and omit `Latest:` when no active label applies. Reject empty, `.`, or `..` path segments in `--preview-dir`/`--branch-dir`, and URL-encode `pages_branch` in `?ref=`. Keep existing `--branch-dir` / `--preview-dir` / `--label` deploy behaviour unchanged and keep the exact single `call("PUT"` write invariant.
2. `scripts/embed-screenshots.sh`: make branch-slug sanitization locale-safe (`LC_ALL=C`) and portable across BSD/GNU `sed` (avoid GNU-only `\+` in basic `sed`); reject/sanitize degenerate slugs (empty, `.`, `..`) so `mkdir`/`rm` can never escape `$workdir`; clean up `comment_file` in the `EXIT` trap; escape `|` in route cells when rendering the Markdown table.
3. Add offline behaviour tests in `tests/test_preview_hub.py` (using a local loopback stub server or configurable API base URL env var defaulting to `https://api.github.com` to exercise deploy indexing, `--remove` dropping a stale deleted slug, `--refresh` with zero previews, HTTP 409 retry, HTML/URL escaping, and `..` path rejection) and in `tests/test_ui_screenshots.py` (exercising `embed-screenshots.sh` against a local bare git repo for `..`/punctuation branch names, pipe-containing route names, locale-safe slugging, and `--comment-out`). Full `python3 -m pytest -q tests` and `bash -n scripts/preview-hub.sh scripts/embed-screenshots.sh` must pass.

**Interface / exclusions:** Preserve every existing assertion in `tests/test_preview_hub.py` and `tests/test_ui_screenshots.py` (including single `call("PUT"`, `path = f"/contents/{...}"`, `PLAYWRIGHT_VERSION`, and all `@v1.16.1` pin checks). Keep both scripts bash-3.2 compatible under `set -euo pipefail`. Do not touch `.github/workflows/` (the Captain wires `preview-cleanup.yml` after this lands), version pins, or any file outside `allowed`.
**Scope and gate:** See [task.json](task.json) at this same commit. Do not edit it.
**Report:** Post on https://github.com/Keshab1997/flutter-builder/issues/10 mentioning `@Keshab1997` (or report in worker chat with `MENTION PENDING` if commenting is unavailable).

Use the current agent-bootstrap `captain/FASTLANE.md`. Keep the real `arena/*`
branch. After a verified `PUSHED`, include the brief link, checkpoint block
and commit link when reporting. If blocked, report the reason; do not change
branch, use a standalone clone, re-pair, run CI, or open/merge/close a PR.
