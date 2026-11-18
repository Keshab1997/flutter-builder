#!/usr/bin/env python3
"""Unit tests for scripts/bump-pubspec-version.py.

Covers all five ``--bump`` modes, prerelease handling, the missing build
number error, no-op protection and GITHUB_OUTPUT wiring.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bump-pubspec-version.py"


def parsed(stdout: str) -> dict[str, str]:
    out = {}
    for line in stdout.splitlines():
        if "=" in line and not line.startswith(":"):
            key, _, value = line.partition("=")
            if key in ("name", "changed"):
                out[key] = value
    return out


class BumpTests(unittest.TestCase):
    def run_bump(self, version: str, bump: str, use_output: bool = False):
        with tempfile.TemporaryDirectory() as tmp:
            pubspec = Path(tmp) / "pubspec.yaml"
            pubspec.write_text(f"name: app\nversion: {version}\n", encoding="utf-8")
            env = dict(os.environ)
            go_path = None
            if use_output:
                go_path = Path(tmp) / "github-output"
                go_path.write_text("", encoding="utf-8")
                env["GITHUB_OUTPUT"] = str(go_path)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--pubspec", str(pubspec), "--bump", bump],
                capture_output=True,
                text=True,
                env=env,
            )
            output = go_path.read_text(encoding="utf-8") if go_path is not None else None
            untouched = pubspec.read_text(encoding="utf-8")
        return result, output, untouched

    # --- all five bump modes -------------------------------------------

    def test_major_strips_prerelease_and_advances_build(self) -> None:
        result, output, _ = self.run_bump("1.2.3-beta.1+4", "major")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parsed(result.stdout), {"name": "2.0.0+5", "changed": "true"})
        self.assertIn("::notice::", result.stdout)

    def test_minor_strips_prerelease_and_advances_build(self) -> None:
        result, output, _ = self.run_bump("1.2.3+4", "minor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parsed(result.stdout), {"name": "1.3.0+5", "changed": "true"})

    def test_patch_strips_prerelease_and_advances_build(self) -> None:
        result, output, _ = self.run_bump("1.2.3-rc.2+4", "patch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parsed(result.stdout), {"name": "1.2.4+5", "changed": "true"})

    def test_build_keeps_prerelease_and_advances_build(self) -> None:
        result, output, _ = self.run_bump("1.2.3-rc.2+4", "build")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parsed(result.stdout), {"name": "1.2.3-rc.2+5", "changed": "true"})

    def test_none_keeps_prerelease_and_build(self) -> None:
        result, output, _ = self.run_bump("1.2.3-beta.1+9", "none")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parsed(result.stdout), {"name": "1.2.3-beta.1+9", "changed": "false"})

    def test_major_works_without_a_build_number(self) -> None:
        result, output, _ = self.run_bump("1.2.3", "major")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parsed(result.stdout), {"name": "2.0.0", "changed": "true"})

    # --- GITHUB_OUTPUT ---------------------------------------------------

    def test_github_output_on_none(self) -> None:
        result, output, _ = self.run_bump("1.2.3-beta.1+9", "none", use_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, "name=1.2.3-beta.1+9\nchanged=false\n")

    def test_github_output_on_major(self) -> None:
        result, output, _ = self.run_bump("1.2.3+4", "major", use_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, "name=2.0.0+5\nchanged=true\n")

    def test_github_output_absent_is_fine(self) -> None:
        result, output, _ = self.run_bump("1.2.3+4", "major", use_output=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    # --- errors -----------------------------------------------------------

    def test_build_bump_requires_a_build_number(self) -> None:
        result, _, _ = self.run_bump("1.2.3", "build")
        self.assertEqual(result.returncode, 1)
        self.assertIn("needs a build number", result.stderr)

    def test_patch_bump_requires_a_build_number(self) -> None:
        result, _, _ = self.run_bump("1.2.3", "patch")
        self.assertEqual(result.returncode, 1)
        self.assertIn("needs a build number", result.stderr)

    def test_unparseable_pubspec_is_rejected(self) -> None:
        result, _, _ = self.run_bump("not-a-version", "patch")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no parseable", result.stderr)

    def test_missing_pubspec_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--pubspec", str(Path(tmp) / "pubspec.yaml"),
                 "--bump", "patch"],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot read", result.stderr)

    # --- no-op protection -------------------------------------------------

    def test_none_is_explicit_no_op(self) -> None:
        result, output, _ = self.run_bump("1.2.3+4", "none", use_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parsed(result.stdout), {"name": "1.2.3+4", "changed": "false"})
        if output is not None:
            self.assertEqual(output, "name=1.2.3+4\nchanged=false\n")

    def test_regular_bumps_are_not_no_ops(self) -> None:
        result, _, _ = self.run_bump("1.0.0+1", "patch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parsed(result.stdout), {"name": "1.0.1+2", "changed": "true"})

    # --- the pubspec file itself is never rewritten ----------------------

    def test_pubspec_file_is_never_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pubspec = Path(tmp) / "pubspec.yaml"
            pubspec.write_text("name: app\nversion: 1.2.3+4\n", encoding="utf-8")
            env = dict(os.environ)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--pubspec", str(pubspec), "--bump", "patch"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(pubspec.read_text(encoding="utf-8"), "name: app\nversion: 1.2.3+4\n")


if __name__ == "__main__":
    unittest.main()
