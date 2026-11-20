"""Offline tests for scripts/doctor.sh; no Flutter SDK, network, or real gh."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "doctor.sh"

PUBSPEC = """name: demo_app
version: 1.0.0+1
environment:
  sdk: '>=3.0.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
  cupertino_icons: ^1.0.8
"""

PUBSPEC_FIREBASE = PUBSPEC + """  firebase_core: ^3.6.0
  firebase_auth: ^5.1.0
"""

PUBSPEC_ADMOB = PUBSPEC + """  google_mobile_ads: ^6.0.0
"""

GRADLE_KTS = """plugins {
  id("com.android.application")
  id("kotlin-android")
}

android {
  namespace = "com.demo.app"
  defaultConfig {
    applicationId = "com.demo.app"
  }
}
"""

KEYPROPS = (
    "storePassword=sp\nkeyPassword=kp\nkeyAlias=ka\nstoreFile=release.jks\n"
)

GSE_JSON = (
    '{"project_info": {"project_id": "demo-project"}, '
    '"client": [{"client_info": {"android_client_info": '
    '{"package_name": "com.demo.app"}}}]}'
)

CI_WORKFLOW = """name: Flutter CI
on:
  workflow_dispatch:
jobs:
  ci:
    uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.18.9
    with:
      flutter-channel: stable
      working-directory: "."
      run-format-check: true
      run-analyze: true
      run-tests: true
      build-apk: false
      build-aab: false
"""

# Test double for gh: serves secret/variable names from files next to itself
# and always reports authenticated, so section 5 runs deterministically.
FAKE_GH = """#!/usr/bin/env bash
dir="$(cd "$(dirname "$0")" && pwd)"
case "${1:-}" in
  auth)     exit 0 ;;
  repo)     printf 'owner/demo\\n' ;;
  secret)   cat "$dir/secrets.txt" 2>/dev/null || true ;;
  variable) cat "$dir/variables.txt" 2>/dev/null || true ;;
  *)        exit 0 ;;
esac
"""

SIGNING_SECRETS = (
    "ANDROID_KEYSTORE_BASE64\nKEYSTORE_PASSWORD\nKEY_ALIAS\nKEY_PASSWORD\n"
)
ADMOB_VARIABLES = (
    "ADMOB_APP_ID\nADMOB_BANNER_ID\nADMOB_INTERSTITIAL_ID\nADMOB_REWARDED_ID\n"
)


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self._git("init", "-q", "-b", "main", str(self.repo))
        self._git("config", "user.email", "dev@test.invalid")
        self._git("config", "user.name", "Test")
        self.fake_bin = Path(self.temp.name) / "fakebin"
        self.fake_bin.mkdir()
        gh = self.fake_bin / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)
        self.write_secrets("", "")

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def write_secrets(self, secrets: str, variables: str) -> None:
        (self.fake_bin / "secrets.txt").write_text(secrets, encoding="utf-8")
        (self.fake_bin / "variables.txt").write_text(variables, encoding="utf-8")

    def make_app(
        self,
        rel: str = ".",
        pubspec: str = PUBSPEC,
        gse: bool = True,
        keyprops: bool = True,
        workflow: str = CI_WORKFLOW,
        lib: str = "void main() {}\n",
    ) -> Path:
        """A minimal Flutter app under `rel`; secret files are git-ignored."""
        app = self.repo / rel
        (app / "android" / "app").mkdir(parents=True, exist_ok=True)
        (app / "lib").mkdir(parents=True, exist_ok=True)
        (app / "pubspec.yaml").write_text(pubspec, encoding="utf-8")
        (app / "android" / "app" / "build.gradle.kts").write_text(
            GRADLE_KTS, encoding="utf-8"
        )
        (app / "lib" / "main.dart").write_text(lib, encoding="utf-8")
        (app / ".gitignore").write_text(
            "android/key.properties\nandroid/*.jks\n"
            "android/app/google-services.json\n",
            encoding="utf-8",
        )
        if keyprops:
            (app / "android" / "key.properties").write_text(KEYPROPS, encoding="utf-8")
            (app / "android" / "release.jks").write_bytes(b"\x0e\x01\x06\x00jks")
        if gse:
            (app / "android" / "app" / "google-services.json").write_text(
                GSE_JSON, encoding="utf-8"
            )
        if workflow is not None:
            wf_dir = self.repo / ".github" / "workflows"
            wf_dir.mkdir(parents=True, exist_ok=True)
            (wf_dir / "ci.yml").write_text(workflow, encoding="utf-8")
        return app

    def commit(self) -> None:
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "fixture")

    def run_doctor(
        self,
        *args: str,
        piped: bool = False,
        env_extra: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.pop("DOCTOR_REQUIRE_FIREBASE", None)
        env.pop("DOCTOR_CI", None)
        if env_extra:
            env.update(env_extra)
        env["PATH"] = f"{self.fake_bin}{os.pathsep}{env['PATH']}"
        command = ["bash", "-s", "--", *args] if piped else ["bash", str(SCRIPT), *args]
        return subprocess.run(
            command,
            cwd=cwd or self.repo,
            input=SCRIPT.read_text() if piped else None,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # -- help ----------------------------------------------------------------

    def test_piped_help_works_without_script_path(self) -> None:
        """`curl ... | bash -s -- --help` has no $0 to sed from."""
        result = self.run_doctor("--help", piped=True)
        self.assert_success(result)
        for needle in (
            "flutter-builder doctor",
            "--app-dir DIR",
            "--ci",
            "--repo OWNER/NAME",
            "DOCTOR_REQUIRE_FIREBASE",
            "Exit status: 0 = nothing broken, 1 = at least one FAIL.",
        ):
            self.assertIn(needle, result.stdout)

    # -- clean / failing app ---------------------------------------------------

    def test_clean_app_passes(self) -> None:
        self.write_secrets(SIGNING_SECRETS, "")
        self.make_app()
        self.commit()
        result = self.run_doctor()
        self.assert_success(result)
        for needle in (
            "Android module: android/app",
            "key.properties found: android/key.properties",
            "keystore exists",
            "key.properties is not tracked by git",
            "package matches applicationId (com.demo.app)",
            "every required secret is present",
            "GOOGLE_SERVICES_JSON_BASE64 not required",
            "ADMOB_* variables not required",
            "flutter-builder pinned to >= v1.6.0",
            "no ${{ secrets.* }} inside with: blocks",
            "GOOGLE_SERVICES_JSON_BASE64 forwarded by every build workflow",
            "no Google test ad IDs under lib/",
            "no secrets/config tracked by git",
            "0 failures",
        ):
            self.assertIn(needle, result.stdout)

    def test_failing_app_reports_missing_signing_secrets(self) -> None:
        self.write_secrets("", "")
        self.make_app()
        self.commit()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1)
        for name in (
            "ANDROID_KEYSTORE_BASE64",
            "KEYSTORE_PASSWORD",
            "KEY_ALIAS",
            "KEY_PASSWORD",
        ):
            self.assertIn(f"MISSING secret: {name}", result.stdout)
        self.assertIn("4 failures", result.stdout)

    # -- --app-dir -------------------------------------------------------------

    def test_app_dir_scopes_a_monorepo(self) -> None:
        self.write_secrets(SIGNING_SECRETS, "")
        self.make_app(rel="apps/mobile")
        # A noisy sibling project outside the app directory: a Google test ad
        # ID in source and a keystore that IS tracked by git.
        sibling = self.repo / "webapp"
        (sibling / "lib").mkdir(parents=True)
        (sibling / "lib" / "ads.dart").write_text(
            "const String adUnit = 'ca-app-pub-3940256099942544';\n",
            encoding="utf-8",
        )
        (sibling / "android" / "app").mkdir(parents=True)
        (sibling / "android" / "app" / "build.gradle.kts").write_text(
            GRADLE_KTS, encoding="utf-8"
        )
        (sibling / "android" / "leak.keystore").write_bytes(b"junk")
        self.commit()
        # Without the flag the tracked keystore outside the app fails doctor...
        bare = self.run_doctor()
        self.assertEqual(bare.returncode, 1)
        self.assertIn("SECRET FILES STILL TRACKED BY GIT", bare.stdout)
        # ...and --app-dir scopes signing, hygiene and tracked-secret checks
        # to the app, so the sibling's problems do not surface.
        result = self.run_doctor("--app-dir", "apps/mobile")
        self.assert_success(result)
        self.assertIn("Android module: apps/mobile/android/app", result.stdout)
        self.assertIn("key.properties found: apps/mobile/android/key.properties", result.stdout)
        self.assertIn("no Google test ad IDs under apps/mobile/lib/", result.stdout)
        self.assertIn("no secrets/config tracked by git", result.stdout)
        self.assertNotIn("GOOGLE TEST AD ID", result.stdout)
        # The = form of the flag works too.
        self.assert_success(self.run_doctor("--app-dir=apps/mobile"))
        # A nonexistent directory fails fast with a clear message.
        bad = self.run_doctor("--app-dir", "nope")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("no such directory: nope", bad.stdout)

    # -- CI mode + DOCTOR_REQUIRE_FIREBASE --------------------------------------

    def test_ci_requires_firebase_json_when_env_set(self) -> None:
        self.make_app(gse=False)
        self.commit()
        result = self.run_doctor("--ci", env_extra={"DOCTOR_REQUIRE_FIREBASE": "1"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("google-services.json ABSENT after injection", result.stdout)
        self.assertIn("1 failures", result.stdout)

    def test_ci_without_require_firebase_passes(self) -> None:
        self.make_app(gse=False)
        self.commit()
        result = self.run_doctor("--ci")
        self.assert_success(result)
        self.assertIn("google-services.json not present locally", result.stdout)
        self.assertIn("skipped in CI", result.stdout)
        self.assertIn("0 failures", result.stdout)

    # -- conditional Firebase / AdMob secret checks -----------------------------

    def test_firebase_dependency_requires_the_secret(self) -> None:
        self.write_secrets(SIGNING_SECRETS, "")
        self.make_app(pubspec=PUBSPEC_FIREBASE)
        self.commit()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("MISSING secret: GOOGLE_SERVICES_JSON_BASE64", result.stdout)
        self.assertNotIn("GOOGLE_SERVICES_JSON_BASE64 not required", result.stdout)
        # With the secret present the app is clean again.
        self.write_secrets(SIGNING_SECRETS + "GOOGLE_SERVICES_JSON_BASE64\n", "")
        self.assert_success(self.run_doctor())

    def test_doctor_require_firebase_env_requires_secret_without_dependency(self) -> None:
        self.write_secrets(SIGNING_SECRETS, "")
        self.make_app()
        self.commit()
        result = self.run_doctor(env_extra={"DOCTOR_REQUIRE_FIREBASE": "1"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("MISSING secret: GOOGLE_SERVICES_JSON_BASE64", result.stdout)
        self.write_secrets(SIGNING_SECRETS + "GOOGLE_SERVICES_JSON_BASE64\n", "")
        self.assert_success(self.run_doctor(env_extra={"DOCTOR_REQUIRE_FIREBASE": "1"}))

    def test_admob_dependency_requires_the_variables(self) -> None:
        self.write_secrets(SIGNING_SECRETS, "")
        self.make_app(pubspec=PUBSPEC_ADMOB)
        self.commit()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1)
        for name in (
            "ADMOB_APP_ID",
            "ADMOB_BANNER_ID",
            "ADMOB_INTERSTITIAL_ID",
            "ADMOB_REWARDED_ID",
        ):
            self.assertIn(f"MISSING variable: {name}", result.stdout)
        self.assertNotIn("ADMOB_* variables not required", result.stdout)
        # All four present -> clean.
        self.write_secrets(SIGNING_SECRETS, ADMOB_VARIABLES)
        self.assert_success(self.run_doctor())

    # -- tracked secrets / test ad ID -------------------------------------------

    def test_tracked_secrets_fail(self) -> None:
        self.write_secrets(SIGNING_SECRETS, "")
        self.make_app()
        # Remove the gitignore entries and commit the secret files.
        (self.repo / ".gitignore").write_text("", encoding="utf-8")
        self.commit()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("android/key.properties IS TRACKED BY GIT", result.stdout)
        self.assertIn("google-services.json IS TRACKED BY GIT", result.stdout)
        self.assertIn("SECRET FILES STILL TRACKED BY GIT", result.stdout)

    def test_test_ad_unit_id_in_gradle_is_not_flagged_production(self) -> None:
        """The documented safe fallback: Google's test ID in a Gradle file."""
        self.write_secrets(SIGNING_SECRETS, "")
        self.make_app()
        gradle = self.repo / "android" / "app" / "build.gradle.kts"
        gradle.write_text(
            GRADLE_KTS
            + '\ndefaultConfig {\n'
            + '  manifestPlaceholders = ["adUnitId": "ca-app-pub-3940256099942544~1033173712"]\n'
            + "}\n",
            encoding="utf-8",
        )
        self.commit()
        result = self.run_doctor()
        self.assert_success(result)
        self.assertIn("no production AdMob app ID hardcoded in source", result.stdout)

    def test_google_test_ad_id_fails(self) -> None:
        self.write_secrets(SIGNING_SECRETS, "")
        self.make_app(
            lib="const String adUnit = 'ca-app-pub-3940256099942544';\nvoid main() {}\n"
        )
        self.commit()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("GOOGLE TEST AD ID IN SOURCE", result.stdout)
        self.assertIn("lib/main.dart", result.stdout)

    # -- section 6: workflow wiring ----------------------------------------------

    def test_secrets_expression_in_with_block_fails(self) -> None:
        self.write_secrets(SIGNING_SECRETS, "")
        self.make_app()
        (self.repo / ".github/workflows/build.yml").write_text(
            "name: Build\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  build:\n"
            "    uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.18.9\n"
            "    with:\n"
            "      flutter-channel: ${{ secrets.CHANNEL }}\n"
            "      build-apk: true\n"
            "    secrets: inherit\n",
            encoding="utf-8",
        )
        self.commit()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("USED INSIDE with:", result.stdout)
        self.assertIn("build.yml line", result.stdout)

    def test_yaml_caller_and_expression_build_callers(self) -> None:
        """`.yaml` callers, names with spaces and `build-apk: ${{ ... }}`."""
        self.write_secrets(SIGNING_SECRETS, "")
        self.make_app()
        wf_dir = self.repo / ".github/workflows"
        body = (
            "name: Nightly\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "    inputs:\n"
            "      format:\n"
            "        type: choice\n"
            "        options:\n"
            "          - apk\n"
            "          - aab\n"
            "jobs:\n"
            "  build:\n"
            "    uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.18.9\n"
            "    with:\n"
            "      build-apk: ${{ inputs.format == 'apk' }}\n"
            "      build-aab: ${{ inputs.format == 'aab' }}\n"
        )
        forwarded = body + "    secrets: inherit\n"
        (wf_dir / "nightly build.yaml").write_text(forwarded, encoding="utf-8")
        self.commit()
        result = self.run_doctor()
        self.assert_success(result)
        self.assertIn("workflows found", result.stdout)
        self.assertIn(
            "GOOGLE_SERVICES_JSON_BASE64 forwarded by every build workflow",
            result.stdout,
        )
        # Drop the forwarding: expression callers still build, so the secret
        # must be forwarded — doctor warns (does not fail) about it.
        (wf_dir / "nightly build.yaml").write_text(body, encoding="utf-8")
        result = self.run_doctor()
        self.assert_success(result)
        self.assertIn(
            ".github/workflows/nightly build.yaml builds an artifact but does "
            "not forward GOOGLE_SERVICES_JSON_BASE64",
            result.stdout,
        )

    def test_outdated_pin_fails(self) -> None:
        self.write_secrets(SIGNING_SECRETS, "")
        self.make_app(workflow=CI_WORKFLOW.replace("@v1.18.9", "@v1.2.0"))
        self.commit()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("OUTDATED builder", result.stdout)
        self.assertIn(".github/workflows/ci.yml pins @1.2.0", result.stdout)


if __name__ == "__main__":
    unittest.main()
