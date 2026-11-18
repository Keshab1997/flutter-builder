# consumer-bumps — Worker B

**Repository:** `Keshab1997/flutter-builder` — attach this repo in Arena Agent Mode.
**Goal and acceptance:** Stop consumer pin-bump PRs from piling up across releases, isolate git auth from global config, and fix/test the pubspec version helper:
1. `scripts/bump-consumers.sh`: after successfully opening or refreshing the PR for `chore/flutter-builder-<ref>`, list open PRs in that repo whose `headRefName` starts with `chore/flutter-builder-` and does not equal the current `$branch`, and close each superseded PR with a concise comment linking the new PR URL plus `--delete-branch` (best-effort: warn on close failure without marking the newly opened PR as failed, and never touch non-`chore/flutter-builder-*` PRs). Replace `git config --global ...` with a temporary `GIT_CONFIG_GLOBAL` file inside `$work` (`chmod 600`) so running the script never mutates the caller's `~/.gitconfig` or leaves a token on disk after exit.
2. `scripts/bump-pubspec-version.py`: strip any prerelease suffix (e.g. `-beta.1`) on `major`, `minor`, and `patch` bumps while retaining it on `build` and `none`; also write `name=<current>` and `changed=false` to `$GITHUB_OUTPUT` (when set) on `--bump none`; align the module docstring with `publish-release.yml` (it computes the next version without auto-committing via the API).
3. Add offline fake-`gh`/local-git end-to-end tests in `tests/test_bump_consumers.py` (superseding older `chore/flutter-builder-*` PRs, ignoring unrelated open PRs, leaving `$HOME/.gitconfig` untouched, and keeping `--dry-run` completely side-effect free) and comprehensive unit tests in `tests/test_bump_pubspec_version.py` (all 5 `--bump` modes, prerelease handling, missing build number error, no-op protection, and `GITHUB_OUTPUT`). Full `python3 -m pytest -q tests` and `bash -n scripts/bump-consumers.sh` must pass.

**Interface / exclusions:** Keep delegating pin rewrites to `scripts/bump-ref.sh` (do not add `sed -E` to `bump-consumers.sh`). Keep `BRANCH_PREFIX='chore/flutter-builder-'`, `--force-with-lease` (never bare `--force`), and never auto-merge (`pr merge` or `--auto`). Keep all existing CLI flags and workflow compatibility with `.github/workflows/bump-consumers.yml`. Do not touch `.github/workflows/`, `scripts/bump-ref.sh`, or any version pin/tag.
**Scope and gate:** See [task.json](task.json) at this same commit. Do not edit it.
**Report:** Post on https://github.com/Keshab1997/flutter-builder/issues/10 mentioning `@Keshab1997` (or report in worker chat with `MENTION PENDING` if commenting is unavailable).

Use the current agent-bootstrap `captain/FASTLANE.md`. Keep the real `arena/*`
branch. After a verified `PUSHED`, include the brief link, checkpoint block
and commit link when reporting. If blocked, report the reason; do not change
branch, use a standalone clone, re-pair, run CI, or open/merge/close a PR.
