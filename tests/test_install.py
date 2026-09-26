"""End-to-end installer tests; no Flutter SDK, network, or third-party modules."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"
FILES = (
    "ci.yml",
    "manual-build.yml",
    "publish-release.yml",
    "release.yml",
    "web-preview.yml",
)
PUBSPEC = """name: demo_app
version: 1.0.0+1
environment:
  sdk: '>=3.0.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
"""


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "project"
        self.repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(self.repo)], check=True
        )

    def flutter_app(self, relative: str = ".") -> Path:
        app = self.repo / relative
        app.mkdir(parents=True, exist_ok=True)
        (app / "pubspec.yaml").write_text(PUBSPEC, encoding="utf-8")
        return app

    def run_installer(
        self, *args: str, cwd: Path | None = None, piped: bool = False
    ) -> subprocess.CompletedProcess[str]:
        command = ["bash", "-s", "--", *args] if piped else ["bash", str(SCRIPT), *args]
        return subprocess.run(
            command,
            cwd=cwd or self.repo,
            input=SCRIPT.read_text() if piped else None,
            text=True,
            capture_output=True,
            check=False,
        )

    def installed(self, name: str) -> str:
        return (self.repo / ".github" / "workflows" / name).read_text(
            encoding="utf-8"
        )

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_root_installation_and_rerun_is_idempotent(self) -> None:
        self.flutter_app()
        first = self.run_installer()
        self.assert_success(first)
        before = {name: self.installed(name) for name in FILES}
        for content in before.values():
            self.assertIn("@v1.8.0", content)
            self.assertIn('working-directory: "."', content)
        self.assertIn("code-coverage: true", before["ci.yml"])
        self.assertIn("secrets: inherit", before["publish-release.yml"])
        self.assertNotIn("app-name:", before["publish-release.yml"])
        self.assertIn("publish-release.yml@v1.8.0", before["publish-release.yml"])
        self.assertIn('tags:\n      - "v*"', before["release.yml"])
        self.assertIn("web-preview.yml@v1.8.0", before["web-preview.yml"])
        self.assertIn("secrets: inherit", before["web-preview.yml"])
        self.assertIn('group: web-preview-${{ github.ref }}', before["web-preview.yml"])

        second = self.run_installer()
        self.assert_success(second)
        self.assertIn("nothing changed", second.stdout)
        self.assertEqual(before, {name: self.installed(name) for name in FILES})
        self.assertFalse((self.repo / ".github/flutter-builder-backups").exists())

    def test_auto_detect_nested_project_from_git_root(self) -> None:
        self.flutter_app("apps/mobile")
        result = self.run_installer()
        self.assert_success(result)
        for name in FILES:
            self.assertIn('working-directory: "apps/mobile"', self.installed(name))
        self.assertFalse((self.repo / "apps/mobile/.github").exists())

    def test_piped_bash_from_inside_flutter_app(self) -> None:
        app = self.flutter_app("flutter_app")
        self.flutter_app("apps/other")
        result = self.run_installer("--app-name", "Alice's App", cwd=app, piped=True)
        self.assert_success(result)
        self.assertIn('working-directory: "flutter_app"', self.installed("ci.yml"))
        self.assertIn('app-name: "Alice\'s App"', self.installed("publish-release.yml"))

    def test_multiple_projects_require_explicit_selection(self) -> None:
        self.flutter_app("apps/mobile")
        self.flutter_app("apps/desktop")
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Multiple Flutter projects", result.stderr)
        self.assertIn("--app-dir", result.stderr)
        self.assertFalse((self.repo / ".github").exists())
        chosen = self.run_installer("--app-dir", "apps/mobile")
        self.assert_success(chosen)
        self.assertIn('working-directory: "apps/mobile"', self.installed("ci.yml"))

    def test_root_project_takes_priority_over_nested_flutter_examples(self) -> None:
        self.flutter_app()
        self.flutter_app("example")
        self.assert_success(self.run_installer())
        self.assertIn('working-directory: "."', self.installed("ci.yml"))

    def test_pure_dart_project_rejected_without_writes(self) -> None:
        (self.repo / "pubspec.yaml").write_text("name: pure_dart\n", encoding="utf-8")
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No Flutter pubspec.yaml", result.stderr)
        self.assertFalse((self.repo / ".github").exists())

    def test_dry_run_never_creates_files(self) -> None:
        self.flutter_app()
        result = self.run_installer("--dry-run")
        self.assert_success(result)
        self.assertIn("Will add", result.stdout)
        self.assertIn("no files were changed", result.stdout)
        self.assertFalse((self.repo / ".github").exists())

    def test_existing_different_file_aborts_entire_install(self) -> None:
        self.flutter_app()
        target = self.repo / ".github/workflows/ci.yml"
        target.parent.mkdir(parents=True)
        target.write_text("# Custom CI, keep it\n", encoding="utf-8")
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CONFLICT", result.stdout)
        self.assertIn("nothing was changed", result.stderr)
        self.assertEqual(target.read_text(), "# Custom CI, keep it\n")
        for name in FILES[1:]:
            self.assertFalse((target.parent / name).exists())

    def test_force_backs_up_existing_before_replacing(self) -> None:
        self.flutter_app()
        target = self.repo / ".github/workflows/ci.yml"
        target.parent.mkdir(parents=True)
        target.write_text("# Custom CI, keep it\n", encoding="utf-8")
        result = self.run_installer("--force")
        self.assert_success(result)
        self.assertIn("@v1.8.0", self.installed("ci.yml"))
        backups = list((self.repo / ".github/flutter-builder-backups").glob("*/ci.yml"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "# Custom CI, keep it\n")
        for name in FILES:
            self.assertTrue((target.parent / name).is_file())

    def test_force_dry_run_does_not_make_backups(self) -> None:
        self.flutter_app()
        target = self.repo / ".github/workflows/ci.yml"
        target.parent.mkdir(parents=True)
        target.write_text("keep original\n", encoding="utf-8")
        result = self.run_installer("--force", "--dry-run")
        self.assert_success(result)
        self.assertEqual(target.read_text(), "keep original\n")
        self.assertFalse((self.repo / ".github/flutter-builder-backups").exists())
        self.assertFalse((target.parent / "manual-build.yml").exists())

    def test_symlink_or_escape_is_rejected(self) -> None:
        self.flutter_app()
        outside = Path(self.temp.name) / "elsewhere"
        outside.mkdir()
        (self.repo / ".github").symlink_to(outside, target_is_directory=True)
        result = self.run_installer("--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)
        self.assertEqual(list(outside.iterdir()), [])
        (self.repo / ".github").unlink()
        (outside / "pubspec.yaml").write_text(PUBSPEC)
        result = self.run_installer("--app-dir", "../elsewhere")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside the Git repository", result.stderr)
        self.assertFalse((self.repo / ".github").exists())

    def test_ref_and_display_name_quoted_safely(self) -> None:
        self.flutter_app("my app")
        result = self.run_installer(
            "--app-dir", "my app", "--app-name", 'A "Quoted" \\ App', "--ref", "v1.4.0"
        )
        self.assert_success(result)
        self.assertIn('working-directory: "my app"', self.installed("ci.yml"))
        self.assertIn('app-name: "A \\"Quoted\\" \\\\ App"', self.installed("publish-release.yml"))
        for name in FILES:
            self.assertIn("@v1.4.0", self.installed(name))

    def test_invalid_ref_and_expression_rejected(self) -> None:
        self.flutter_app()
        for args in (("--ref", "main"), ("--ref", "v1.5.0\nnext:"),
                     ("--app-name", "${{ secrets.KEY_PASSWORD }}")):
            with self.subTest(args=args):
                result = self.run_installer(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.repo / ".github").exists())

    def test_no_git_repo_uses_current_directory(self) -> None:
        plain = Path(self.temp.name) / "not-a-git-repo"
        plain.mkdir()
        (plain / "pubspec.yaml").write_text(PUBSPEC, encoding="utf-8")
        result = self.run_installer(cwd=plain)
        self.assert_success(result)
        self.assertTrue((plain / ".github/workflows/ci.yml").is_file())
        self.assertFalse((self.repo / ".github").exists())

    def test_symlink_workflow_cannot_be_replaced(self) -> None:
        self.flutter_app()
        target = self.repo / ".github/workflows/ci.yml"
        target.parent.mkdir(parents=True)
        outside = Path(self.temp.name) / "other.yml"
        outside.write_text("Do not touch me\n", encoding="utf-8")
        target.symlink_to(outside)
        result = self.run_installer("--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)
        self.assertEqual(outside.read_text(), "Do not touch me\n")
        self.assertFalse((target.parent / "manual-build.yml").exists())

    def test_help_works_without_flutter_project(self) -> None:
        result = self.run_installer("--help", piped=True)
        self.assert_success(result)
        self.assertIn("--app-dir", result.stdout)
        self.assertFalse((self.repo / ".github").exists())


if __name__ == "__main__":
    unittest.main()
