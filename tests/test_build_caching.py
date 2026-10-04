"""The caches that make a Flutter build fast, and the knobs around them.

A removed cache step costs every project minutes per run and is invisible in
review - the workflow still works, it is just slow again. These checks pin the
behaviour so a refactor cannot quietly drop it:

  * Gradle dependency/wrapper cache (the Flutter SDK cache does not cover
    ~/.gradle), read-only on pull requests so a PR cannot evict main's entry;
  * the Gradle build cache / parallel / jvmargs keys, appended only when the
    project's own gradle.properties does not already set them;
  * the build_runner output cache, keyed on pubspec.lock plus sources;
  * `--no-pub` after the explicit `flutter pub get` (one resolve per run);
  * the opt-in knobs: format-paths, test-concurrency, build-mode,
    target-platform, test-matrix-on-pr - all defaulting to the previous
    behaviour, so existing callers are unaffected.

Text-level assertions on purpose: the installer tests in this repository run
with the standard library only, no PyYAML, no Flutter SDK and no network.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".github" / "workflows" / "flutter-build.yml"
AGENT_INSTALLER = ROOT / "scripts" / "install-agent-pack.sh"

ANDROID_GUARD = "if: inputs.build-apk || inputs.build-aab"


def step(text: str, name: str) -> str:
    """Body of the step called `name`, up to the next step at the same indent."""
    match = re.search(rf"(?m)^      - name: {re.escape(name)}\n(?P<body>.*?)"
                      rf"(?=^      - name: |\Z)", text, re.S)
    assert match, f"step not found: {name}"
    return match.group("body")


def input_block(text: str, name: str) -> str:
    """Body of the workflow_call input called `name`."""
    match = re.search(rf"(?m)^      {re.escape(name)}:\n(?P<body>(?:        .*\n)+)",
                      text)
    assert match, f"input not found: {name}"
    return match.group("body")


class GradleCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = BUILD.read_text(encoding="utf-8")

    def test_gradle_dependency_cache_guards_android_builds(self) -> None:
        body = step(self.text, "Set up Gradle (dependency and wrapper cache)")
        self.assertIn("uses: gradle/actions/setup-gradle@v4", body)
        self.assertIn("cache-read-only: ${{ github.event_name == 'pull_request' }}",
                      body)
        self.assertIn("description" if False else ANDROID_GUARD, body)

    def test_gradle_properties_step_only_appends_missing_keys(self) -> None:
        body = step(self.text, "Enable Gradle build cache")
        for key in ("org.gradle.caching true", "org.gradle.parallel true"):
            self.assertIn(key, body)
        self.assertIn("org.gradle.jvmargs", body)
        # Append-only: the project's own values must win.
        self.assertIn("grep -qE", body)
        self.assertNotIn("> android/gradle.properties", body)
        # configuration-cache still breaks plugin combinations; it stays an
        # opt-in in the project's file, never a default here.
        self.assertNotRegex(body, r"add org\.gradle\.configuration-cache")

    def test_build_runner_output_is_cached_when_codegen_runs(self) -> None:
        body = step(self.text, "Cache build_runner output")
        self.assertIn("uses: actions/cache@v4", body)
        self.assertIn("path: ${{ inputs.working-directory }}/.dart_tool/build", body)
        self.assertIn("hashFiles('**/pubspec.lock')", body)
        self.assertIn("hashFiles('**/lib/**/*.dart', '**/test/**/*.dart')", body)
        self.assertIn("inputs.codegen == 'build_runner' || inputs.codegen == 'both'",
                      body)


class OnePubGetPerRunTests(unittest.TestCase):
    """`flutter pub get` runs once per job; everything after it uses --no-pub."""

    def setUp(self) -> None:
        self.text = BUILD.read_text(encoding="utf-8")

    def test_each_job_resolves_dependencies_once(self) -> None:
        self.assertEqual(self.text.count("run: flutter pub get"), 2)
        self.assertEqual(self.text.count("flutter analyze --no-pub --fatal-infos"), 2)
        self.assertEqual(self.text.count("args=(--no-pub)"), 2)
        self.assertIn('flutter test --coverage "${args[@]}"', self.text)
        self.assertIn('flutter test "${args[@]}"', self.text)

    def test_builds_do_not_resolve_again(self) -> None:
        self.assertIn('flutter build apk --no-pub --"$mode"', self.text)
        self.assertIn("flutter build appbundle --no-pub --release", self.text)
        # Only real command lines count: the AAB step keeps the pre-workaround
        # one-line command in a comment for the day it can be reverted.
        commands = "\n".join(line for line in self.text.splitlines()
                             if not line.lstrip().startswith("#"))
        self.assertNotIn("flutter build apk --release", commands)
        self.assertNotIn("flutter build appbundle --release", commands)


class OptInKnobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = BUILD.read_text(encoding="utf-8")

    def test_format_paths_defaults_to_the_previous_behaviour(self) -> None:
        body = input_block(self.text, "format-paths")
        self.assertIn('default: "."', body)
        self.assertEqual(
            self.text.count("dart format --output=none --set-exit-if-changed "
                            "${{ inputs.format-paths }}"), 2)

    def test_test_concurrency_stays_off_by_default(self) -> None:
        self.assertIn("default: 0", input_block(self.text, "test-concurrency"))
        self.assertEqual(self.text.count('TEST_CONCURRENCY: ${{ inputs.test-concurrency }}'),
                         2)

    def test_apk_build_mode_defaults_to_release(self) -> None:
        self.assertIn("default: release", input_block(self.text, "build-mode"))
        self.assertIn('default: ""', input_block(self.text, "target-platform"))
        body = step(self.text, "Build release APK")
        self.assertIn('mode="${BUILD_MODE:-release}"', body)
        self.assertIn('--target-platform "$TARGET_PLATFORM"', body)
        # --obfuscate is release-only: a profile build must not be handed it.
        self.assertIn('if [ "$mode" = "release" ]', body)

    def test_matrix_stays_off_pull_requests_by_default(self) -> None:
        self.assertIn("default: false", input_block(self.text, "test-matrix-on-pr"))
        self.assertEqual(
            self.text.count("inputs.test-matrix-on-pr || github.event_name != 'pull_request'"),
            2)


class PinDriftTests(unittest.TestCase):
    def test_preflight_checkout_carries_the_pack_version(self) -> None:
        """The builder checkout that runs doctor.sh must not lag the release.

        It was pinned two tags behind (v1.7.0 while the pack shipped v1.9.1),
        which silently ran an old doctor. Keeping this in step with
        PACK_VERSION means the anti-drift check fires in the same commit that
        forgets to bump one of them.
        """
        installer = AGENT_INSTALLER.read_text(encoding="utf-8")
        packed = re.search(r"^PACK_VERSION=(v[\d.]+)$", installer, re.M)
        self.assertIsNotNone(packed, "PACK_VERSION missing from the installer")
        workflow = BUILD.read_text(encoding="utf-8")
        body = step(workflow, "Check out this builder (for the pre-flight script)")
        pinned = re.search(r"^          ref: (v[\d.]+)$", body, re.M)
        self.assertIsNotNone(pinned, "the builder checkout has no tag pin")
        self.assertEqual(pinned.group(1), packed.group(1),
                         "flutter-build.yml and install-agent-pack.sh pins differ")


class ImgBbWorkflowSecretTests(unittest.TestCase):
    """The optional API key reaches only Android builds and leaves no workspace file."""

    BUILD = ROOT / ".github" / "workflows" / "flutter-build.yml"
    PUBLISH = ROOT / ".github" / "workflows" / "publish-release.yml"
    MANUAL_EXAMPLE = ROOT / "examples" / "project-workflows" / "manual-build.yml"

    def setUp(self) -> None:
        self.workflow = self.BUILD.read_text(encoding="utf-8")

    @staticmethod
    def run_block(body: str) -> str:
        match = re.search(r"^        run: \|\n((?:          .*\n|\n)+)", body, re.M)
        if match is None:
            raise AssertionError("step has no run block")
        return textwrap.dedent(match.group(1))

    def run_step(self, name: str, root: Path, key: str) -> subprocess.CompletedProcess[str]:
        runner_temp = root / "runner-temp"
        runner_temp.mkdir(exist_ok=True)
        env = dict(os.environ)
        env.update(RUNNER_TEMP=str(runner_temp), IMGBB_API_KEY=key)
        script = self.run_block(step(self.workflow, name))
        return subprocess.run(
            ["bash", "-c", script], cwd=root, env=env,
            text=True, capture_output=True, check=False,
        )

    def test_secret_is_optional_and_injected_only_for_android_builds(self) -> None:
        secret_section = self.workflow.split("    secrets:\n", 1)[1].split("\njobs:\n", 1)[0]
        self.assertIn("      IMGBB_API_KEY:", secret_section)
        self.assertIn("        required: false", secret_section)
        inject = step(self.workflow, "Inject ImgBB API key for Android build")
        self.assertIn("if: inputs.build-apk || inputs.build-aab", inject)
        self.assertIn("IMGBB_API_KEY: ${{ secrets.IMGBB_API_KEY }}", inject)
        self.assertIn("path.write_text", inject)

    def test_injection_preserves_existing_settings_and_cleanup_restores_them(self) -> None:
        key = "test-imgbb-key-never-log"
        original = "# local config\nOTHER_SETTING=keep\nIMGBB_API_KEY=old-value\n"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dotenv = root / ".env"
            dotenv.write_text(original, encoding="utf-8")

            injected = self.run_step("Inject ImgBB API key for Android build", root, key)
            self.assertEqual(injected.returncode, 0, injected.stdout + injected.stderr)
            contents = dotenv.read_text(encoding="utf-8")
            self.assertIn("OTHER_SETTING=keep", contents)
            self.assertEqual(contents.count("IMGBB_API_KEY="), 1)
            self.assertIn(f"IMGBB_API_KEY={key}", contents)
            self.assertNotIn(key, injected.stdout + injected.stderr)

            restored = self.run_step("Restore .env after Android build", root, key)
            self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
            self.assertEqual(dotenv.read_text(encoding="utf-8"), original)
            self.assertNotIn(key, restored.stdout + restored.stderr)

    def test_cleanup_removes_a_temporary_env_file_created_for_the_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            injected = self.run_step("Inject ImgBB API key for Android build", root, "test-key")
            self.assertEqual(injected.returncode, 0, injected.stdout + injected.stderr)
            self.assertTrue((root / ".env").is_file())

            restored = self.run_step("Restore .env after Android build", root, "test-key")
            self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
            self.assertFalse((root / ".env").exists())

    def test_missing_key_does_not_change_the_app_env(self) -> None:
        original = "OTHER_SETTING=keep\n"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dotenv = root / ".env"
            dotenv.write_text(original, encoding="utf-8")

            result = self.run_step("Inject ImgBB API key for Android build", root, "")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(dotenv.read_text(encoding="utf-8"), original)
            self.assertIn("IMGBB_API_KEY is not configured", result.stdout)
            self.assertNotIn("test-key", result.stdout + result.stderr)

    def test_release_wrapper_and_manual_example_forward_the_optional_secret(self) -> None:
        publish = self.PUBLISH.read_text(encoding="utf-8")
        self.assertIn("      IMGBB_API_KEY:", publish)
        self.assertIn("IMGBB_API_KEY: ${{ secrets.IMGBB_API_KEY }}", publish)
        self.assertIn("flutter-build.yml@v1.14.1", publish)
        manual = self.MANUAL_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("IMGBB_API_KEY: ${{ secrets.IMGBB_API_KEY }}", manual)

    def test_cleanup_runs_even_when_an_android_build_fails(self) -> None:
        cleanup = step(self.workflow, "Restore .env after Android build")
        self.assertIn("if: always() && (inputs.build-apk || inputs.build-aab)", cleanup)



if __name__ == "__main__":
    unittest.main()
