# consumer-pack-fix — Worker B

**Repository:** `Keshab1997/flutter-builder` — continue in your existing attached Arena chat on `arena/63d9ba0d-flutter-builder` (base `554e438fcaf9479802a5f5ad2548efe454cb508b`).
**Goal and acceptance:** Fix four Captain-review findings on `--with-agent-pack` in `scripts/bump-consumers.sh` (from `554e438f`) and add regression tests in `tests/test_bump_consumers.py`:
1. **`--dry-run --with-agent-pack` with outdated `tool/*.py`:** Currently `agent_args=(--dry-run)` omits `--force`, so `install-agent-pack.sh` exits 1 with `CONFLICT` before inspecting `AGENTS.md`/`.gitignore`, and even with `--force` it prints `Will replace (backup first): ...` which `grep -qE 'Will (add|update)'` misses. Pass `--force --dry-run` on dry-run and match `Will (add|update|replace)`.
2. **Untracked pack files missed by `git diff --quiet`:** When `install-agent-pack.sh --force` adds new untracked files (e.g. `tool/local_screenshots.py`, `tool/screenshots/shot_framework.dart`, or a brand-new `.gitignore`) while existing tracked files match, `git -C "$clone" diff --quiet -- ...` exits 0 and skips the repo. Detect changes with `git -C "$clone" status --porcelain -- AGENTS.md tool .gitignore` instead, and only `git add --` those pack paths when `pack_changed=true`.
3. **Pack install errors and backup cleanup:** Do not silently ignore a non-zero exit from `install-agent-pack.sh` — log a warning (or mark `failed` and continue without committing a half-updated pack), and guard backup cleanup against a symlink (`[ ! -L "$clone/.agent-pack-backups" ] && rm -rf -- "$clone/.agent-pack-backups"`).
4. **Changed-file summary line:** In `--dry-run`, `git -C "$clone" diff --name-only` is empty (printing `<name>:  -> @<ref>`); only compute/print the concrete file list in non-dry-run mode (including untracked pack files via `git status --porcelain` or after `git add` via `git diff --cached --name-only`), and print a clean dry-run summary line in `--dry-run`.
5. **Regression tests in `tests/test_bump_consumers.py`:** Cover (a) `--dry-run --with-agent-pack` when an existing `tool/preflight.py` is outdated (reports `would open a PR`, writes nothing), (b) `--with-agent-pack` when workflow pins & `AGENTS.md` are already current but a pack tool file (e.g. `tool/local_screenshots.py` or `.gitignore`) was missing/untracked (detects change, stages and commits the new file, leaves no `.agent-pack-backups`), and (c) `install-agent-pack.sh` failing (e.g. symlinked `AGENTS.md`) logs failure and does not open a broken PR.

**Interface / exclusions:** `bump-ref.sh` and same-repo PR guard in `554e438f` already passed review — keep them intact. Never touch live GitHub repos, `.github/workflows/**`, or release pins.
**Scope and gate:** See [task.json](task.json) at this same commit. Do not edit it.
**Report:** Post on https://github.com/Keshab1997/flutter-builder/issues/10 mentioning `@Keshab1997` (or report in worker chat with `MENTION PENDING` if commenting is unavailable).

Use the current agent-bootstrap `captain/FASTLANE.md`. Keep the real `arena/*`
branch. After a verified `PUSHED`, include the brief link, checkpoint block
and commit link when reporting. If blocked, report the reason; do not change
branch, use a standalone clone, re-pair, run CI, or open/merge/close a PR.
