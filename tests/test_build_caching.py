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

import re
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


if __name__ == "__main__":
    unittest.main()
