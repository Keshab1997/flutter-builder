# release-helper — Worker C

**Repository:** `Keshab1997/flutter-builder` — continue in your existing attached Arena chat on `arena/e0563147-flutter-builder` (base `053b89fe96bd7fa02732674fcdda20201c335e9f`).
**Goal and acceptance:** Replace manual 24-file release pin edits with one safe, offline, stdlib-only helper (`scripts/prepare-release.py`) and full unit tests (`tests/test_prepare_release.py`):
1. `scripts/prepare-release.py` (Python >= 3.8 stdlib only, `--root DIR` defaulting to repo root):
   - `--check`: read the current release version from `PACK_VERSION` in `scripts/install-agent-pack.sh` and verify every release-coupled pin matches it: `DEFAULT_REF` and help/usage tag examples in `scripts/install.sh` and `scripts/bump-ref.sh`, usage/comment tag examples in `scripts/bump-consumers.sh` and `scripts/install-agent-pack.sh`, `flutter-builder` workflow/checkout pins and tag examples in `.github/workflows/*.yml`, caller pins in `examples/project-workflows/*.yml`, `agent-pack/AGENTS.template.md` start marker, embedded installer parity (`scripts/sync-agent-pack.py --check`), current-pin references in `AGENTS.md`, `README.md`, and `docs/PLAY_INTERNAL_TESTING.md`, and any release-pin constants (e.g. `PIN = "v..."` / `PACK_VERSION = "v..."` / expected tag strings) in `tests/test_*.py`. Exit `0` when consistent (true on the current `v1.16.1` repo!), exit `1` listing every drifted file/location.
   - `--version vX.Y.Z` (strict `^v[0-9]+\.[0-9]+\.[0-9]+$` validation; reject invalid tags or downgrades unless `--allow-downgrade`): atomically rewrite all release-coupled occurrences from the current `PACK_VERSION` to the new version while leaving historical "introduced in" references (e.g. `v1.5.0`, `v1.6.0`, `v1.8.6`, `v1.10.0`, `v1.14.0`, `v1.15.2+`) untouched, then re-sync `scripts/install-agent-pack.sh` via `sync-agent-pack.py` so the embedded `AGENTS.template.md` marker matches too.
   - `--dry-run` (with `--version`): print every file that would change and exit `0` without writing anything.
   - Safety: never run `git commit`, `git tag`, `git push`, or `gh release`; print a short reminder at the end that committing, tagging, and releasing remain the human's deliberate step.
2. `tests/test_prepare_release.py` (offline): verify `--check` passes against the real repository at `v1.16.1`; copy the repo tree into a `TemporaryDirectory` and verify `--version v1.17.0 --dry-run` writes nothing; run `--version v1.17.0` on the temp copy and verify `--check` passes, `sync-agent-pack.py --check` passes, historical versions (`v1.6.0`, `v1.14.0`, `v1.15.2+`) stay intact, re-running `--version v1.17.0` is idempotent, introducing a single drifted pin fails `--check` with exit `1` naming the file, downgrades are refused without `--allow-downgrade`, and bad tag strings exit non-zero. Full `python3 -m pytest -q tests` must pass.

**Interface / exclusions:** Do **not** run `prepare-release.py --version ...` against the real repository checkout — keep `v1.16.1` untouched everywhere. Create only the two files in `allowed`; do not edit any existing file, workflow, pin, or tag.
**Scope and gate:** See [task.json](task.json) at this same commit. Do not edit it.
**Report:** Post on https://github.com/Keshab1997/flutter-builder/issues/10 mentioning `@Keshab1997` (or report in worker chat with `MENTION PENDING` if commenting is unavailable).

Use the current agent-bootstrap `captain/FASTLANE.md`. Keep the real `arena/*`
branch. After a verified `PUSHED`, include the brief link, checkpoint block
and commit link when reporting. If blocked, report the reason; do not change
branch, use a standalone clone, re-pair, run CI, or open/merge/close a PR.
