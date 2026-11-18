"""Offline tests for scripts/prepare-release.py.

The real repository is only ever read (--check, which is read-only); every
write path runs against a copy of the release-coupled files in a
TemporaryDirectory, so this suite never touches a pin in the checkout and
never needs the network.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "prepare-release.py"


def load_helper():
    """Import the helper as a module so the tests use its own file list."""
    spec = importlib.util.spec_from_file_location(
        "prepare_release_under_test", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPER_MODULE = load_helper()


def run_helper(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), "--root", str(root), *args],
        capture_output=True, text=True, check=False, timeout=300)


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def make_tree(dst: Path) -> Path:
    """Copy everything a release touches (plus what sync-agent-pack needs)."""
    for path in HELPER_MODULE.coupled_files(ROOT):
        if path.is_file():
            rel = path.relative_to(ROOT)
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dst / rel)
    (dst / "agent-pack").mkdir(parents=True, exist_ok=True)
    for path in (ROOT / "agent-pack").iterdir():
        if path.is_file():
            shutil.copy2(path, dst / "agent-pack" / path.name)
    shutil.copy2(ROOT / "scripts" / "sync-agent-pack.py",
                 dst / "scripts" / "sync-agent-pack.py")
    return dst


def installer_version(root: Path) -> str:
    import re
    text = (root / "scripts" / "install-agent-pack.sh").read_text(encoding="utf-8")
    match = re.search(r"^PACK_VERSION=(v[0-9]+\.[0-9]+\.[0-9]+)$", text, re.M)
    assert match, "PACK_VERSION missing from the installer"
    return match.group(1)


class CheckOnRealRepoTests(unittest.TestCase):
    """--check is read-only, so it runs against the actual checkout."""

    def test_check_passes_on_the_real_repository(self) -> None:
        # Deliberately no --root: the default (the repo containing the
        # script) must work.
        done = subprocess.run(
            [sys.executable, str(HELPER), "--check"],
            capture_output=True, text=True, check=False, timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        current = installer_version(ROOT)
        self.assertIn(current, done.stdout)
        self.assertIn("all release pins", done.stdout)


class VersionBumpTests(unittest.TestCase):
    """Every write path runs on a temp copy of the release-coupled files."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = make_tree(Path(temp.name))
        self.before = snapshot(self.root)

    def run_prep(self, *args: str) -> subprocess.CompletedProcess[str]:
        return run_helper(self.root, *args)

    def test_dry_run_writes_nothing(self) -> None:
        done = self.run_prep("--version", "v1.17.0", "--dry-run")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("dry run", done.stdout)
        self.assertIn("scripts/install.sh", done.stdout)
        self.assertIn(".github/workflows/flutter-build.yml", done.stdout)
        self.assertEqual(snapshot(self.root), self.before)

    def test_bump_to_v1_17_0(self) -> None:
        done = self.run_prep("--version", "v1.17.0")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

        check = self.run_prep("--check")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

        sync = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "sync-agent-pack.py"),
             "--check"],
            capture_output=True, text=True, check=False, timeout=300)
        self.assertEqual(sync.returncode, 0, sync.stdout + sync.stderr)

        installer = (self.root / "scripts" / "install-agent-pack.sh") \
            .read_text(encoding="utf-8")
        self.assertIn("PACK_VERSION=v1.17.0", installer)
        self.assertIn("agent-pack:start v1.17.0", installer)  # embedded marker
        self.assertEqual(installer.count("v1.16.1"), 0)
        template = (self.root / "agent-pack" / "AGENTS.template.md") \
            .read_text(encoding="utf-8")
        self.assertIn("agent-pack:start v1.17.0", template)
        self.assertEqual(template.count("v1.16.1"), 0)

        install = (self.root / "scripts" / "install.sh").read_text(encoding="utf-8")
        self.assertIn("DEFAULT_REF=v1.17.0", install)
        self.assertIn("v1.5.0", install)          # historical example untouched
        self.assertEqual(install.count("v1.16.1"), 0)

        # Historical "introduced in" references stay exactly where they were.
        self.assertIn("v1.6.0", (self.root / ".github/workflows" /
                                 "publish-release.yml").read_text(encoding="utf-8"))
        self.assertIn("v1.10.0", (self.root / ".github/workflows" /
                                  "flutter-smoke-test.yml").read_text(encoding="utf-8"))
        smoke = (self.root / ".github/workflows" / "ui-screenshots.yml") \
            .read_text(encoding="utf-8")
        self.assertIn("v1.14.0", smoke)           # historical comment
        self.assertIn("ref: v1.17.0", smoke)      # live pin moved
        play = (self.root / "docs" / "PLAY_INTERNAL_TESTING.md") \
            .read_text(encoding="utf-8")
        self.assertIn("v1.15.2+", play)
        self.assertIn("v1.14.0", play)
        self.assertIn("v1.8.6", play)

        example = (self.root / "examples/project-workflows" / "ci.yml") \
            .read_text(encoding="utf-8")
        self.assertIn("flutter-build.yml@v1.17.0", example)

    def test_rerun_is_idempotent(self) -> None:
        self.assertEqual(self.run_prep("--version", "v1.17.0").returncode, 0)
        mid = snapshot(self.root)
        done = self.run_prep("--version", "v1.17.0")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("nothing to do", done.stdout)
        self.assertEqual(snapshot(self.root), mid)

    def test_drifted_pin_fails_check_and_names_the_file(self) -> None:
        install = self.root / "scripts" / "install.sh"
        text = install.read_text(encoding="utf-8")
        install.write_text(
            text.replace("DEFAULT_REF=v1.16.1", "DEFAULT_REF=v1.99.9"),
            encoding="utf-8")
        done = self.run_prep("--check")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("scripts/install.sh", done.stdout)
        self.assertIn("v1.99.9", done.stdout)

    def test_downgrade_refused_without_flag(self) -> None:
        done = self.run_prep("--version", "v1.16.0")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("downgrade", done.stdout)
        self.assertIn("--allow-downgrade", done.stdout)
        self.assertEqual(snapshot(self.root), self.before)

    def test_downgrade_with_flag(self) -> None:
        done = self.run_prep("--version", "v1.16.0", "--allow-downgrade")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(installer_version(self.root), "v1.16.0")
        self.assertIn("DEFAULT_REF=v1.16.0",
                      (self.root / "scripts" / "install.sh").read_text(
                          encoding="utf-8"))

    def test_bad_tag_strings_rejected(self) -> None:
        for tag in ("1.17.0", "v1.17", "v1.17.0-beta", "V1.17.0", "v1.17.0 ",
                    "v1..17", "v1.17.0.0"):
            with self.subTest(tag=tag):
                done = self.run_prep("--version", tag)
                self.assertNotEqual(done.returncode, 0,
                                    done.stdout + done.stderr)
        self.assertEqual(snapshot(self.root), self.before)


if __name__ == "__main__":
    unittest.main()
