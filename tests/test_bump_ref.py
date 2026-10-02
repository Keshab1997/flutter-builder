"""Tests for scripts/bump-ref.sh; no network, git, or third-party modules."""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bump-ref.sh"
# The pin the tool writes when no --ref is given. Read from the script so a
# version bump never breaks these tests.
PIN = re.search(r"^DEFAULT_REF=(\S+)$", SCRIPT.read_text(encoding="utf-8"), re.M).group(1)

CUSTOM_CI = """name: Custom CI

on:
  push:

jobs:
  whatsnew-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - run: echo "keep me"
  ci:
    uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.8.6
    with:
      working-directory: "."
      # a precious local comment
      run-tests: true
    secrets: inherit
"""

MIXED = """name: Mixed pins
jobs:
  a:
    uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.8.6
  b:
    uses: Keshab1997/flutter-builder/.github/workflows/publish-release.yml@main
  c:
    uses: Keshab1997/flutter-builder/.github/workflows/web-preview.yml@1234567890abcdef1234567890abcdef12345678  # trailing note
  d:
    uses: Keshab1997/flutter-builder/.github/workflows/preview-cleanup.yml@v1.8.7
"""

COMMENT_ONLY = """name: Comment mentions the repo
# see Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.8.6 for docs
jobs:
  x:
    uses: actions/checkout@v5
"""


class BumpRefTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "project"
        (self.repo / ".github" / "workflows").mkdir(parents=True)

    def write(self, name: str, content: str) -> Path:
        path = self.repo / ".github" / "workflows" / name
        path.write_text(content, encoding="utf-8")
        return path

    def run_tool(self, *args: str, piped: bool = False) -> subprocess.CompletedProcess[str]:
        command = ["bash", "-s", "--", *args] if piped else ["bash", str(SCRIPT), *args]
        return subprocess.run(
            command,
            cwd=self.repo,
            input=SCRIPT.read_text() if piped else None,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_bumps_every_pin_and_keeps_custom_content(self) -> None:
        ci = self.write("ci.yml", CUSTOM_CI)
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = ci.read_text()
        self.assertIn(f"flutter-build.yml@{PIN}", text)
        self.assertIn("actions/checkout@v5", text)
        self.assertIn("whatsnew-check", text)
        self.assertIn("# a precious local comment", text)
        self.assertIn('working-directory: "."', text)
        self.assertIn("1 file(s) updated", result.stdout)

    def test_mixed_refs_converge_including_yaml_extension(self) -> None:
        mixed = self.write("release.yaml", MIXED)
        other = self.write("keep.yml", "# nothing here\n")
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = mixed.read_text()
        self.assertEqual(text.count(f"@{PIN}"), 4)
        self.assertNotIn("@main", text)
        self.assertNotIn("@v1.8.6", text)
        self.assertNotIn("@v1.8.7", text)
        self.assertNotIn("1234567890abcdef", text)
        self.assertIn(f"web-preview.yml@{PIN}  # trailing note", text)
        self.assertEqual(other.read_text(), "# nothing here\n")

    def test_dry_run_changes_nothing(self) -> None:
        ci = self.write("ci.yml", CUSTOM_CI)
        before = ci.read_text()
        result = self.run_tool("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("would update", result.stdout)
        self.assertIn("No files were written", result.stdout)
        self.assertEqual(ci.read_text(), before)

    def test_rerun_is_idempotent(self) -> None:
        self.write("ci.yml", CUSTOM_CI)
        first = self.run_tool()
        self.assertEqual(first.returncode, 0)
        second = self.run_tool()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("already current", second.stdout)
        self.assertIn("0 file(s) updated", second.stdout)

    def test_comment_only_match_still_counts_and_updates(self) -> None:
        path = self.write("notes.yml", COMMENT_ONLY)
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"flutter-build.yml@{PIN}", path.read_text())
        self.assertIn("actions/checkout@v5", path.read_text())

    def test_ref_override_and_piped_bash(self) -> None:
        ci = self.write("ci.yml", CUSTOM_CI)
        result = self.run_tool("--ref", "v1.4.0", piped=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("flutter-build.yml@v1.4.0", ci.read_text())

    def test_invalid_ref_rejected(self) -> None:
        self.write("ci.yml", CUSTOM_CI)
        for args in (("--ref", "main"), ("--ref", "v1.5.0\nnext:"), ("--ref", "")):
            with self.subTest(args=args):
                result = self.run_tool(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR", result.stderr)

    def test_no_pins_is_an_error(self) -> None:
        self.write("unrelated.yml", "name: No builder here\njobs:\n  x:\n    uses: actions/checkout@v5\n")
        result = self.run_tool()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No flutter-builder pins", result.stderr)

    def test_prose_without_pin_does_not_crash_counting(self) -> None:
        path = self.write(
            "prose.yml",
            "name: Prose\n# built with Keshab1997/flutter-builder/.github/workflows/ reusable files\n"
            "jobs:\n  x:\n    uses: Keshab1997/flutter-builder/.github/workflows/ci.yml@v1.8.7\n",
        )
        result = self.run_tool("--ref", "v2.0.0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ci.yml@v2.0.0", path.read_text())

    def test_missing_workflows_dir_fails(self) -> None:
        empty = Path(self.temp.name) / "empty"
        empty.mkdir()
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=empty,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No .github/workflows", result.stderr)

    def test_help_works_anywhere(self) -> None:
        result = self.run_tool("--help", piped=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--dry-run", result.stdout)

    def test_unknown_option_rejected(self) -> None:
        result = self.run_tool("--nope")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown option", result.stderr)


if __name__ == "__main__":
    unittest.main()
