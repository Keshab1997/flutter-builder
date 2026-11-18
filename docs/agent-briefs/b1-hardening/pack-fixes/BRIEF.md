# pack-fixes — Worker A

**Repository:** `Keshab1997/flutter-builder` — attach this repo in Arena Agent Mode.
**Goal and acceptance:** Fix four concrete agent-pack bugs and keep the embedded installer payload byte-for-byte in sync:
1. `agent-pack/local_screenshots.py`: change the missing-Flutter install command to `https://raw.githubusercontent.com/Keshab1997/flutter-bootstrap/main/setup.sh --quiet --json` (not `flutter-builder/main/scripts/install.sh`), and parse both single- and double-quoted `name:` literals in `known_shots()`.
2. `agent-pack/preflight.py`: ignore optional `super.<name>` constructor parameters (e.g. `super.key`) so private widgets do not false-positive on `unused_element_parameter`; match both single- and double-quoted `import`/`export` statements (including `hide` before `show`); detect unused private arrow functions (`=>`) as well as block/generator functions (`async*`/`sync*`); safely blank Dart raw (`r'...'`, `r"..."`) and triple-quoted (`'''`, `"""`) strings while preserving line counts.
3. `agent-pack/agent_loop.py`: refuse staging `.agent-screens/`, `.agent-pack-backups/`, and `.flutter-builder-backups/` artifacts unless `--allow-secret-paths` is passed; unstage newly added forbidden paths before returning exit code `2` so a refused run does not leave credentials/screenshots staged; allow dots inside GitHub repository names in `github_repo()` (while still stripping a trailing `.git`).
4. `scripts/install-agent-pack.sh`: idempotently ensure `.agent-screens/` and `.agent-pack-backups/` are listed in `.gitignore` on install (refuse a symlinked `.gitignore`, do not write during `--dry-run`, and stay silent/idempotent on rerun); fix the top comment that falsely claims `agent_loop.py` refuses commits on the default branch; run `python3 scripts/sync-agent-pack.py` so every embedded heredoc matches `agent-pack/` byte-for-byte.
5. Add offline regression tests in `tests/test_agent_pack.py` and `tests/test_agent_loop.py` covering every fix above. Full `python3 -m pytest -q tests`, `python3 scripts/sync-agent-pack.py --check`, and `bash -n scripts/install-agent-pack.sh` must pass.

**Interface / exclusions:** Keep `PACK_VERSION=v1.16.1` and all release pins unchanged (no version bump or tag). Preserve all existing CLI flags and exit codes. Keep `scripts/install-agent-pack.sh` bash-3.2 compatible under `set -euo pipefail`. Do not touch `.github/workflows/`, `AGENTS.md`, `agent-pack/*.dart`, `agent-pack/AGENTS.template.md`, or any file outside `allowed`.
**Scope and gate:** See [task.json](task.json) at this same commit. Do not edit it.
**Report:** Post on https://github.com/Keshab1997/flutter-builder/issues/10 mentioning `@Keshab1997` (or report in worker chat with `MENTION PENDING` if commenting is unavailable).

Use the current agent-bootstrap `captain/FASTLANE.md`. Keep the real `arena/*`
branch. After a verified `PUSHED`, include the brief link, checkpoint block
and commit link when reporting. If blocked, report the reason; do not change
branch, use a standalone clone, re-pair, run CI, or open/merge/close a PR.
