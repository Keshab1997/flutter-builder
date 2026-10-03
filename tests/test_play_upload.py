"""Guards for the Google Play upload path in flutter-build.yml.

The upload itself cannot be tested here (it needs Play credentials), but the
two things that must happen *before* it can be: an AAB that reaches Play spends
its version code even when the rest of the step fails, so every precondition
has to be checked first, and the package name has to come from somewhere
trustworthy instead of a hand-typed input.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

BUILD = (
    Path(__file__).resolve().parents[1] / ".github/workflows/flutter-build.yml"
)
# The generated caller an app repository ends up with.
EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples/project-workflows/publish-release.yml"
)

UPLOAD_STEP = "Upload AAB to Google Play"
RESOLVE_STEP = "Resolve the Play package name"
NOTES_STEP = "Check the Play release-notes directory"


def step(text: str, name: str) -> str:
    """The YAML block of one step, exactly as the other tests read them."""
    marker = f"      - name: {name}\n"
    start = text.index(marker)
    rest = text[start + len(marker) :]
    end = rest.find("\n      - name:")
    return rest if end == -1 else rest[:end]


def run_block(body: str) -> str:
    """The shell of a step's `run: |`, dedented back to column zero."""
    match = re.search(r"^        run: \|\n((?:          .*\n|\n)+)", body, re.M)
    assert match is not None, "step has no run block"
    return textwrap.dedent(match.group(1))


class PlayUploadOrderTests(unittest.TestCase):
    """Order is the whole point: checks first, upload last."""

    def setUp(self) -> None:
        self.workflow = BUILD.read_text(encoding="utf-8")

    def index(self, name: str) -> int:
        return self.workflow.index(f"      - name: {name}\n")

    def test_package_name_is_resolved_before_the_upload(self) -> None:
        self.assertLess(self.index(RESOLVE_STEP), self.index(UPLOAD_STEP))

    def test_release_notes_are_checked_before_the_upload(self) -> None:
        self.assertLess(self.index(NOTES_STEP), self.index(UPLOAD_STEP))

    def test_the_upload_uses_the_resolved_package_name(self) -> None:
        upload = step(self.workflow, UPLOAD_STEP)
        self.assertIn(
            "packageName: ${{ steps.play-package.outputs.package_name }}", upload
        )
        # A hand-typed input must not reach the action directly any more.
        self.assertNotIn("packageName: ${{ inputs.play-package-name }}", upload)

    def test_both_checks_are_skipped_when_play_is_off(self) -> None:
        for name in (RESOLVE_STEP, NOTES_STEP):
            body = step(self.workflow, name)
            self.assertIn("if: inputs.play-track != ''", body)
            self.assertIn("inputs.build-aab", body)

    def test_notes_check_uses_the_same_path_as_the_upload(self) -> None:
        """A check that passes while the upload fails would be worthless."""
        notes = step(self.workflow, NOTES_STEP)
        upload = step(self.workflow, UPLOAD_STEP)
        joined = "format('{0}/{1}', inputs.working-directory, inputs.play-whats-new-directory)"
        self.assertIn(joined, notes)
        self.assertIn(joined, upload)


class PlayPackageNameTests(unittest.TestCase):
    """The resolution logic itself, run for real against fixture Gradle files."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / "resolve.sh"
        self.script.write_text(
            run_block(step(BUILD.read_text(encoding="utf-8"), RESOLVE_STEP)),
            encoding="utf-8",
        )
        self.output = self.root / "github_output"
        self.output.write_text("", encoding="utf-8")

    def resolve(
        self, override: str = "", app_dir: str = "flutter_app"
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        env = dict(os.environ)
        env.update(
            PLAY_PACKAGE_NAME_INPUT=override,
            APP_DIR=app_dir,
            GITHUB_OUTPUT=str(self.output),
        )
        result = subprocess.run(
            ["bash", str(self.script)],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        return result, self.output.read_text(encoding="utf-8")

    def write_gradle(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_reads_the_application_id_from_a_kotlin_build_file(self) -> None:
        self.write_gradle(
            "flutter_app/android/app/build.gradle.kts",
            'android {\n    namespace = "com.example.demo"\n'
            '    defaultConfig {\n        applicationId = "com.keshabstudios.keepit"\n    }\n}\n',
        )
        result, output = self.resolve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("package_name=com.keshabstudios.keepit", output)
        # The namespace is not the package name — that mix-up would upload to
        # the wrong app or to nothing at all.
        self.assertNotIn("com.example.demo", output)

    def test_reads_the_application_id_from_a_groovy_build_file(self) -> None:
        self.write_gradle(
            "flutter_app/android/app/build.gradle",
            "android {\n    defaultConfig {\n"
            '        applicationId "com.keshabstudios.groovy"\n    }\n}\n',
        )
        result, output = self.resolve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("package_name=com.keshabstudios.groovy", output)

    def test_an_input_still_wins(self) -> None:
        self.write_gradle(
            "flutter_app/android/app/build.gradle.kts",
            '        applicationId = "com.keshabstudios.keepit"\n',
        )
        result, output = self.resolve(override="com.other.app")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("package_name=com.other.app", output)
        self.assertNotIn("keepit", output)

    def test_an_unresolvable_name_fails_before_anything_is_uploaded(self) -> None:
        result, output = self.resolve()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.strip(), "")
        self.assertIn("::error::", result.stdout)
        self.assertIn("play-package-name input", result.stdout)

    def test_a_placeholder_name_is_warned_about(self) -> None:
        self.write_gradle(
            "flutter_app/android/app/build.gradle.kts",
            '        applicationId = "com.example.demo"\n',
        )
        result, output = self.resolve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("package_name=com.example.demo", output)
        self.assertIn("::warning::", result.stdout)

    def test_a_subdirectory_app_is_resolved_against_its_own_directory(self) -> None:
        self.write_gradle(
            "apps/mobile/android/app/build.gradle.kts",
            '        applicationId = "com.keshabstudios.mobile"\n',
        )
        result, output = self.resolve(app_dir="apps/mobile")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("package_name=com.keshabstudios.mobile", output)


class PlayNotesTests(unittest.TestCase):
    """The notes check fails loudly, and says which of the two fixes applies."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / "notes.sh"
        body = step(BUILD.read_text(encoding="utf-8"), NOTES_STEP)
        self.script.write_text(run_block(body), encoding="utf-8")
        self.working_directory = "flutter_app"

    def check(self, notes_dir: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        # The runner supplies all three; the script is written with `set -u`, so
        # a missing one aborts it — which is how the first version of this test
        # fooled itself into passing the failure branch for the wrong reason.
        env.update(
            NOTES_DIR=notes_dir,
            ROOT_RELATIVE_DIR="distribution/whatsnew",
            WORKING_DIR=self.working_directory,
        )
        return subprocess.run(
            ["bash", str(self.script)],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_a_missing_directory_fails_with_the_subdirectory_hint(self) -> None:
        (self.root / "distribution/whatsnew").mkdir(parents=True)
        result = self.check("flutter_app/distribution/whatsnew")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not exist", result.stdout)
        # The notes do exist — just not where the join looks — so the message
        # has to name the '../' fix instead of telling them to create files.
        self.assertIn("'../distribution/whatsnew'", result.stdout)
        self.assertIn("no version code was spent", result.stdout)

    def test_a_missing_directory_asks_for_the_files_when_nothing_exists(self) -> None:
        result = self.check("flutter_app/distribution/whatsnew")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("whatsnew-<locale>", result.stdout)
        self.assertNotIn("'../distribution/whatsnew'", result.stdout)

    def test_an_empty_directory_warns_but_passes(self) -> None:
        (self.root / "flutter_app/distribution/whatsnew").mkdir(parents=True)
        result = self.check("flutter_app/distribution/whatsnew")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("::warning::", result.stdout)

    def test_a_populated_directory_passes_and_lists_the_files(self) -> None:
        notes = self.root / "flutter_app/distribution/whatsnew"
        notes.mkdir(parents=True)
        (notes / "whatsnew-en-US").write_text("notes\n", encoding="utf-8")
        result = self.check("flutter_app/distribution/whatsnew")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("whatsnew-en-US", result.stdout)
        self.assertNotIn("::warning::", result.stdout)


class ExampleCallerTests(unittest.TestCase):
    """The copied example has to match what the builder now expects."""

    def test_example_offers_the_same_play_options(self) -> None:
        text = EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("upload_to_play_internal:", text)
        self.assertIn("play-track: ${{ inputs.upload_to_play_internal", text)
        self.assertIn("play-package-name: ${{ inputs.package_name }}", text)
        self.assertIn(
            "play-whats-new-directory: ${{ inputs.upload_to_play_internal"
            " && 'distribution/whatsnew' || '' }}",
            text,
        )

    def test_example_explains_the_subdirectory_notes_path(self) -> None:
        """The mix-up this documents: notes at the root, app in a subfolder.

        The path is joined with working-directory, so 'distribution/whatsnew'
        silently becomes '<app>/distribution/whatsnew' there and the release
        dies after the upload. The example has to name the '../' form.
        """
        self.assertIn("'../distribution/whatsnew'", EXAMPLE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
