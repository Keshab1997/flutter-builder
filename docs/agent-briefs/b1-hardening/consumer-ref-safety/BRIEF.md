# consumer-ref-safety — Worker B

**Repository:** `Keshab1997/flutter-builder` — continue in your existing attached Arena chat on `arena/63d9ba0d-flutter-builder` (base `74bb9a8274e06a6eb8e1b8d6710bebfea4056173`).
**Goal and acceptance:** Guard superseded-PR cleanup against forks, add opt-in agent-pack syncing to `scripts/bump-consumers.sh`, and harden `scripts/bump-ref.sh`:
1. `scripts/bump-consumers.sh`:
   - In the stale-PR supersede query, restrict matches to same-repo PRs (`select(.head.repo.full_name == .base.repo.full_name)`) so a contributor fork PR named `chore/flutter-builder-*` on a public repository is never commented on or closed.
   - Add an opt-in `--with-agent-pack` flag (off by default; document it in `--help`). When `--with-agent-pack` is passed and a connected repository's root `AGENTS.md` already contains `<!-- flutter-builder:agent-pack:start `, invoke `bash "$SCRIPT_DIR/install-agent-pack.sh" --force` inside the clone (or `--dry-run` in `--dry-run` mode), remove any `.agent-pack-backups` directory created in the clone, and stage `AGENTS.md`, `tool`, and `.gitignore` (when modified) alongside `.github/workflows`. Open/refresh the bump PR even if workflow pins were already at `$ref` when the agent pack itself changed, and mention the agent-pack refresh in the PR body when pack files changed. Repositories without the marker keep workflow-only bumps.
2. `scripts/bump-ref.sh`: refuse symlinked `.github`, `.github/workflows`, or target workflow files before writing; create the temporary file inside `$workflows` (not `/tmp`) and remove any leftover temp file on `EXIT` so interrupted runs never leave debris and `mv` stays atomic on one filesystem.
3. Extend `tests/test_bump_consumers.py` (fork PR with `chore/flutter-builder-*` branch is never closed; `--with-agent-pack` upgrades an older managed `AGENTS.md` + `tool/` even when workflows are already current, skips repos without the marker, strips `.agent-pack-backups/`, and honours `--dry-run`) and `tests/test_bump_ref.py` (refusing symlinked `.github`, `.github/workflows`, and symlinked `*.yml` files without touching the symlink target). Full `python3 -m pytest -q tests` and `bash -n scripts/bump-consumers.sh scripts/bump-ref.sh` must pass.

**Interface / exclusions:** Preserve all existing assertions in `tests/test_bump_consumers.py` and `tests/test_bump_ref.py` (no `sed -E` in `bump-consumers.sh`, no `pr merge`/`--auto`, no bare `--force`, keep `DEFAULT_REF=v1.16.1` and `BRANCH_PREFIX='chore/flutter-builder-'`). Do NOT edit `scripts/install-agent-pack.sh` or `.github/workflows/`.
**Scope and gate:** See [task.json](task.json) at this same commit. Do not edit it.
**Report:** Post on https://github.com/Keshab1997/flutter-builder/issues/10 mentioning `@Keshab1997` (or report in worker chat with `MENTION PENDING` if commenting is unavailable).

Use the current agent-bootstrap `captain/FASTLANE.md`. Keep the real `arena/*`
branch. After a verified `PUSHED`, include the brief link, checkpoint block
and commit link when reporting. If blocked, report the reason; do not change
branch, use a standalone clone, re-pair, run CI, or open/merge/close a PR.
