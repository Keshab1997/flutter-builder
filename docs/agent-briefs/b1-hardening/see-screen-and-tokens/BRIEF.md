# see-screen-and-tokens — Worker A

**Repository:** `Keshab1997/flutter-builder` — continue in your existing attached Arena chat on `arena/04999643-flutter-builder` (base `788a6ebd1d514860b5705e5a5b449d588086ce5b`).
**Goal and acceptance:** Harden `agent-pack/see_screen.py` and unify `agent-bootstrap` saved-token discovery across the four Python GitHub tools, keeping `scripts/install-agent-pack.sh` synced byte-for-byte:
1. `agent-pack/see_screen.py`:
   - Fix `_epoch()` to convert UTC timestamps with `calendar.timegm()` instead of `time.mktime(...) - time.timezone` (which shifts by an hour during DST) and handle missing/malformed timestamps cleanly.
   - Add `--workflow FILE` (default `WORKFLOW_FILE = "ui-screenshots.yml"`) and query workflow-scoped runs (`/repos/{repo}/actions/workflows/{workflow}/runs?event=workflow_dispatch&per_page=20`) in `find_run()` so a concurrent manual dispatch of another workflow is never mistaken for the screenshot run; include `"workflow"` in `--dry-run` output.
   - In `--json` mode, send status/progress messages (and failure diagnostics) to `sys.stderr` (or emit valid JSON on stdout) so `python3 tool/see_screen.py --json` leaves pure, parseable JSON on `stdout`.
   - In `fetch_artifact()`, skip `expired` artifacts, prefer an artifact named `ui-screenshots` when multiple exist, skip directory and zip-symlink members during extraction, verify `target.is_relative_to(out.resolve())`, and omit `"Content-Type": "application/json"` on bodyless `GET` requests while clearing both `headers` and `unredirected_hdrs` `Authorization` on cross-host redirects.
2. Token fallback across `agent-pack/see_screen.py`, `agent-pack/ci_watch.py`, `agent-pack/agent_loop.py`, and `scripts/preview_timing.py`:
   - Keep existing precedence (`--token-file`, then env vars `$GH_TOKEN`/`$GITHUB_TOKEN`, then `gh auth token`), and add a final fallback reading `Path.home() / "agent-bootstrap" / "secrets" / "gh_token.txt"` when that regular file exists and is non-empty (silently ignoring `OSError` / empty files, and never printing token values). Update any existing "no token" unit tests to isolate `HOME` (e.g. a temp directory) so tests pass even inside sandboxes that already have `~/agent-bootstrap/secrets/gh_token.txt`.
3. Run `python3 scripts/sync-agent-pack.py` so `scripts/install-agent-pack.sh` matches `agent-pack/` byte-for-byte. Extend `tests/test_see_screen.py`, `tests/test_ci_watch.py`, `tests/test_agent_loop.py`, and `tests/test_preview_timing.py` with offline unit tests covering every fix above. Full `python3 -m pytest -q tests`, `python3 scripts/sync-agent-pack.py --check`, and `bash -n scripts/install-agent-pack.sh` must pass.

**Interface / exclusions:** Keep `PACK_VERSION=v1.16.1` unchanged (no version bump or tag). Preserve all existing CLI flags, defaults, and exit codes. Do not touch `.github/workflows/`, `AGENTS.md`, or any file outside `allowed`.
**Scope and gate:** See [task.json](task.json) at this same commit. Do not edit it.
**Report:** Post on https://github.com/Keshab1997/flutter-builder/issues/10 mentioning `@Keshab1997` (or report in worker chat with `MENTION PENDING` if commenting is unavailable).

Use the current agent-bootstrap `captain/FASTLANE.md`. Keep the real `arena/*`
branch. After a verified `PUSHED`, include the brief link, checkpoint block
and commit link when reporting. If blocked, report the reason; do not change
branch, use a standalone clone, re-pair, run CI, or open/merge/close a PR.
