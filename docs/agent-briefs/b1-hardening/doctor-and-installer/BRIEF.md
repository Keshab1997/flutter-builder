# doctor-and-installer — Worker C

**Repository:** `Keshab1997/flutter-builder` — attach this repo in Arena Agent Mode.
**Goal and acceptance:** Harden and test `scripts/doctor.sh`, add optional caller flags to `scripts/install.sh`, and fix two small doc omissions:
1. `scripts/doctor.sh`: add `--app-dir DIR` (and `--app-dir=DIR`) for monorepo apps; replace `sed -n '2,22p' "$0"` with a self-contained `usage()` heredoc so `curl ... | bash -s -- --help` works; handle `.yaml` caller extensions and expression-based Android build callers (e.g. `build-apk: ${{ inputs.format == 'apk' }}`) in section 6 (avoid unquoted word-splitting over workflow filenames); in section 5, always require the 4 Android signing secrets, require `GOOGLE_SERVICES_JSON_BASE64` only when `DOCTOR_REQUIRE_FIREBASE` is non-empty or the app's `pubspec.yaml` depends on a `firebase_` package (else report `info`), and require the 4 `ADMOB_*` variables only when `pubspec.yaml` depends on `google_mobile_ads` (else report `info`).
2. `scripts/install.sh`: keep default behaviour (installing the same 4 workflows) unchanged, and add opt-in `--with-screenshots` and `--with-widget-tests` flags that also stage/install `ui-screenshots.yml` and `widget-tests.yml` (matching `examples/project-workflows/` semantics, pinned to `$ref`, using the resolved `working-directory`, and participating in the same `--dry-run`, conflict check, and `--force` backup flow).
3. `README.md` & `docs/PLAY_INTERNAL_TESTING.md`: add `tool/see_screen.py` to the bilingual Agent tools table and mention `--with-screenshots` / `--with-widget-tests` concisely in Quick start; update `docs/PLAY_INTERNAL_TESTING.md`'s 500-character limit version note from `v1.16.0+` to `v1.15.2+`.
4. Add offline `tests/test_doctor.py` (piped `--help`, clean/failing app fixtures, `--app-dir`, `--ci` with and without `DOCTOR_REQUIRE_FIREBASE`, conditional Firebase/AdMob secret checks via fake `gh`, tracked secrets, Google test ad ID, and `${{ secrets.* }}` inside `with:`) and extend `tests/test_install.py` for `--with-screenshots` and `--with-widget-tests` (including `--app-dir`, `--dry-run`, `--force`, and idempotent rerun). Full `python3 -m pytest -q tests` and `bash -n scripts/doctor.sh scripts/install.sh` must pass.

**Interface / exclusions:** Keep `DEFAULT_REF=v1.16.1` and all existing `@v1.16.1` pins unchanged (no version bump or tag). Preserve `--ci`, `--repo`, and `DOCTOR_REQUIRE_FIREBASE` behaviour invoked by `.github/workflows/flutter-build.yml`. Keep default `scripts/install.sh` (without new flags) installing the exact same 4 workflows and stay bash-3.2 compatible under `set -euo pipefail`. Do not touch `.github/workflows/`, `examples/`, `AGENTS.md`, or any file outside `allowed`.
**Scope and gate:** See [task.json](task.json) at this same commit. Do not edit it.
**Report:** Post on https://github.com/Keshab1997/flutter-builder/issues/10 mentioning `@Keshab1997` (or report in worker chat with `MENTION PENDING` if commenting is unavailable).

Use the current agent-bootstrap `captain/FASTLANE.md`. Keep the real `arena/*`
branch. After a verified `PUSHED`, include the brief link, checkpoint block
and commit link when reporting. If blocked, report the reason; do not change
branch, use a standalone clone, re-pair, run CI, or open/merge/close a PR.
