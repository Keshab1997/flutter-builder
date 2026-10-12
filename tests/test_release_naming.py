"""Guards for the release naming in flutter-build.yml's prepare-release step.

A GitHub Release wearing a template placeholder ("My Flutter App") is the
visible bug this guards against: the release must carry the app's own name,
resolved the same way on every project. The resolution logic itself is run
for real here against fixture projects — the same trick the Play-package
tests use, so a broken fallback never waits for a manual release to fail.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

BUILD = (
    Path(__file__).resolve().parents[1] / ".github/workflows/flutter-build.yml"
)
PREPARE_STEP = "Prepare GitHub Release and English release notes"

PUBSPEC = """name: demo_app
version: 1.0.0+1
environment:
  sdk: '>=3.0.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
"""


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


def heredoc_python(shell: str) -> str:
    """The Python inside the step's `python3 - <<'PYTHON'` heredoc."""
    lines = shell.splitlines()
    assert lines and lines[0].startswith("python3 - <<'PYTHON'"), "no heredoc"
    assert lines[-1].strip() == "PYTHON", "heredoc does not terminate"
    return "\n".join(lines[1:-1]) + "\n"


class ReleaseNamingTests(unittest.TestCase):
    """The prepare-release logic itself, run for real against fixtures."""

    @classmethod
    def setUpClass(cls) -> None:
        shell = run_block(step(BUILD.read_text(encoding="utf-8"), PREPARE_STEP))
        cls.code = heredoc_python(shell)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "flutter_app"
        self.project.mkdir()
        (self.project / "pubspec.yaml").write_text(PUBSPEC, encoding="utf-8")
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(self.project)], check=True
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "--allow-empty",
                "-q",
                "-m",
                "feat: initial",
            ],
            cwd=self.project,
            check=True,
        )
        # The step copies these before renaming them for the release.
        for relative in (
            "build/app/outputs/flutter-apk/app-release.apk",
            "build/app/outputs/bundle/release/app-release.aab",
        ):
            path = self.project / relative
            path.parent.mkdir(parents=True)
            path.write_bytes(b"payload")

    def write(self, relative: str, content: str) -> None:
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def prepare(self, name_input: str = "") -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        output = self.root / "github_output"
        output.write_text("", encoding="utf-8")
        runner_temp = self.root / "runner_temp"
        runner_temp.mkdir(exist_ok=True)
        env = dict(os.environ)
        env.update(
            RELEASE_NAME_INPUT=name_input,
            RELEASE_TAG_INPUT="",
            BUILD_APK="true",
            BUILD_AAB="true",
            GITHUB_REPOSITORY="acme/example",
            GITHUB_SERVER_URL="https://github.com",
            GITHUB_SHA="a" * 40,
            GITHUB_OUTPUT=str(output),
            RUNNER_TEMP=str(runner_temp),
        )
        result = subprocess.run(
            [sys.executable, "-c", self.code],
            cwd=self.project,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        parsed = {}
        for line in output.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                parsed[key] = value
        return result, parsed

    def test_the_manifest_label_names_the_release(self) -> None:
        self.write(
            "android/app/src/main/AndroidManifest.xml",
            '<manifest><application android:label="Calculator"/></manifest>\n',
        )
        result, outputs = self.prepare()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["title"], "Calculator v1.0.0")
        asset_dir = Path(outputs["asset-dir"])
        self.assertEqual(
            sorted(p.name for p in asset_dir.iterdir()),
            [
                "Calculator-v1.0.0.aab",
                "Calculator-v1.0.0.apk",
                "SHA256SUMS.txt",
                "release-notes.md",
            ],
        )
        self.assertIn(
            "build of **Calculator**",
            Path(outputs["notes-file"]).read_text(encoding="utf-8"),
        )
        self.assertIn("source: android:label", result.stdout)

    def test_a_string_resource_label_is_resolved(self) -> None:
        self.write(
            "android/app/src/main/AndroidManifest.xml",
            '<manifest><application android:label="@string/app_name"/></manifest>\n',
        )
        # values/ is canonical; a values-bn/ variant must not win the race.
        self.write(
            "android/app/src/main/res/values/strings.xml",
            '<resources><string name="app_name">Quiz Baaz</string></resources>\n',
        )
        self.write(
            "android/app/src/main/res/values-bn/strings.xml",
            '<resources><string name="app_name">ভিন্ন নাম</string></resources>\n',
        )
        result, outputs = self.prepare()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["title"], "Quiz Baaz v1.0.0")

    def test_values_dir_beats_localized_variants(self) -> None:
        """sorted() puts 'values-bn/' before 'values/' — plain glob order is a bug."""
        self.write(
            "android/app/src/main/AndroidManifest.xml",
            '<manifest><application android:label="@string/app_name"/></manifest>\n',
        )
        self.write(
            "android/app/src/main/res/values-bn/strings.xml",
            '<resources><string name="app_name">Bangla Name</string></resources>\n',
        )
        self.write(
            "android/app/src/main/res/values/strings.xml",
            '<resources><string name="app_name">Default Name</string></resources>\n',
        )
        _, outputs = self.prepare()
        self.assertEqual(outputs["title"], "Default Name v1.0.0")

    def test_an_escaped_resource_label_is_unescaped(self) -> None:
        self.write(
            "android/app/src/main/AndroidManifest.xml",
            '<manifest><application android:label="@string/app_name"/></manifest>\n',
        )
        self.write(
            "android/app/src/main/res/values/strings.xml",
            "<resources><string name=\"app_name\">Keshab\\'s App</string></resources>\n",
        )
        result, outputs = self.prepare()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["title"], "Keshab's App v1.0.0")
        self.assertTrue(
            (Path(outputs["asset-dir"]) / "Keshab-s-App-v1.0.0.apk").is_file()
        )

    def test_without_a_manifest_the_pubspec_name_is_used(self) -> None:
        result, outputs = self.prepare()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["title"], "Demo App v1.0.0")
        self.assertIn("source: pubspec name", result.stdout)

    def test_an_unresolvable_string_label_falls_back_to_the_pubspec(self) -> None:
        self.write(
            "android/app/src/main/AndroidManifest.xml",
            '<manifest><application android:label="@string/app_name"/></manifest>\n',
        )
        _, outputs = self.prepare()  # no res/values*/strings.xml exists
        self.assertEqual(outputs["title"], "Demo App v1.0.0")

    def test_the_name_input_still_wins(self) -> None:
        self.write(
            "android/app/src/main/AndroidManifest.xml",
            '<manifest><application android:label="Calculator"/></manifest>\n',
        )
        result, outputs = self.prepare(name_input="SpeakEasy")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["title"], "SpeakEasy v1.0.0")
        self.assertIn("source: release-name input", result.stdout)


class NoPlaceholderTests(unittest.TestCase):
    """No shipped surface may suggest the template placeholder again."""

    def test_the_example_caller_has_no_placeholder_name(self) -> None:
        example = (
            Path(__file__).resolve().parents[1]
            / "examples/project-workflows/publish-release.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("app-name: My Flutter App", example)
        self.assertNotIn("My-Flutter-App", example)
        # And the auto-detect default has to be documented where it is chosen.
        self.assertIn("android:label", example)


if __name__ == "__main__":
    unittest.main()
