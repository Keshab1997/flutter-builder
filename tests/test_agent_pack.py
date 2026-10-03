"""Tests for the agent pack: scripts/install-agent-pack.sh and its payload.

Two kinds of checks:
  * parity - the payload embedded in the curl-able installer must match the
    canonical files under agent-pack/ byte for byte, so the two cannot drift;
  * behaviour - the installer is run in throw-away repositories: fresh install,
    rerun, merge into an existing AGENTS.md, conflicts, --force, --dry-run,
    the piped path, symlink refusal, and the tools themselves.

No Flutter SDK, no network, no third-party modules.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-agent-pack.sh"
PACK = ROOT / "agent-pack"
VERSION = "v1.13.1"

PUBSPEC = """name: demo_app
version: 1.0.0+1
environment:
  sdk: '>=3.0.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
"""

HED = "<!-- flutter-builder:agent-pack:start"
TAIL = "<!-- flutter-builder:agent-pack:end -->"


def extract_payload(token: str) -> str:
    """Body of the quoted heredoc `<<'token'` ... `token` in the installer."""
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(rf"<<'{token}'\n(.*?)^{token}$", text, re.S | re.M)
    if not match:
        raise AssertionError(f"heredoc {token} not found in the installer")
    return match.group(1)


class PayloadParityTests(unittest.TestCase):
    def test_embedded_preflight_matches_agent_pack(self) -> None:
        self.assertEqual(
            extract_payload("AGENT_PACK_PREFLIGHT_PY_EOF"),
            (PACK / "preflight.py").read_text(encoding="utf-8"),
        )

    def test_embedded_ci_watch_matches_agent_pack(self) -> None:
        self.assertEqual(
            extract_payload("AGENT_PACK_CI_WATCH_PY_EOF"),
            (PACK / "ci_watch.py").read_text(encoding="utf-8"),
        )

    def test_embedded_agent_loop_matches_agent_pack(self) -> None:
        self.assertEqual(
            extract_payload("AGENT_PACK_AGENT_LOOP_PY_EOF"),
            (PACK / "agent_loop.py").read_text(encoding="utf-8"),
        )

    def test_embedded_see_screen_matches_agent_pack(self) -> None:
        self.assertEqual(
            extract_payload("AGENT_PACK_SEE_SCREEN_PY_EOF"),
            (PACK / "see_screen.py").read_text(encoding="utf-8"),
        )

    def test_embedded_agents_template_matches_agent_pack(self) -> None:
        self.assertEqual(
            extract_payload("AGENT_PACK_AGENTS_MD_EOF"),
            (PACK / "AGENTS.template.md").read_text(encoding="utf-8"),
        )

    def test_sync_helper_reports_the_payload_in_sync(self) -> None:
        """scripts/sync-agent-pack.py is the only supported way to edit the
        payload; if it reports drift the parity tests above are about to fail."""
        result = subprocess.run(
            ["python3", str(ROOT / "scripts" / "sync-agent-pack.py"), "--check"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("matches agent-pack/", result.stdout)

    def test_installer_carries_the_released_version(self) -> None:
        self.assertIn(f"PACK_VERSION={VERSION}", SCRIPT.read_text(encoding="utf-8"))

    def test_agents_template_has_both_markers_and_a_project_section(self) -> None:
        template = (PACK / "AGENTS.template.md").read_text(encoding="utf-8")
        self.assertEqual(template.count(HED), 1)
        self.assertEqual(template.count(TAIL), 1)
        self.assertIn(VERSION, template)
        self.assertLess(template.index(HED), template.index(TAIL))
        self.assertIn("{{APP_NAME}}", template)


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "project"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)

    def flutter_app(self) -> None:
        (self.repo / "pubspec.yaml").write_text(PUBSPEC, encoding="utf-8")

    def run_installer(
        self, *args: str, cwd: Path | None = None, piped: bool = False
    ) -> subprocess.CompletedProcess[str]:
        command = ["bash", "-s", "--", *args] if piped else ["bash", str(SCRIPT), *args]
        return subprocess.run(
            command,
            cwd=cwd or self.repo,
            input=SCRIPT.read_text(encoding="utf-8") if piped else None,
            text=True,
            capture_output=True,
            check=False,
        )

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def agents_md(self) -> str:
        return (self.repo / "AGENTS.md").read_text(encoding="utf-8")

    def test_fresh_install_installs_tools_and_playbook(self) -> None:
        self.flutter_app()
        result = self.run_installer()
        self.assert_success(result)
        self.assertEqual(
            (self.repo / "tool/preflight.py").read_text(encoding="utf-8"),
            (PACK / "preflight.py").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            (self.repo / "tool/ci_watch.py").read_text(encoding="utf-8"),
            (PACK / "ci_watch.py").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            (self.repo / "tool/agent_loop.py").read_text(encoding="utf-8"),
            (PACK / "agent_loop.py").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            (self.repo / "tool/see_screen.py").read_text(encoding="utf-8"),
            (PACK / "see_screen.py").read_text(encoding="utf-8"),
        )
        agents = self.agents_md()
        self.assertTrue(agents.startswith("# AGENTS.md — demo_app"), agents[:80])
        self.assertEqual(agents.count(HED), 1)
        self.assertEqual(agents.count(TAIL), 1)
        self.assertIn("Project notes", agents)
        self.assertNotIn("{{APP_NAME}}", agents)
        # The installed tools must at least start and be silent on an empty repo.
        preflight = subprocess.run(
            ["python3", "tool/preflight.py"], cwd=self.repo,
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
        helptext = subprocess.run(
            ["python3", "tool/ci_watch.py", "--help"], cwd=self.repo,
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(helptext.returncode, 0, helptext.stderr)
        self.assertIn("--token-file", helptext.stdout)
        loop_help = subprocess.run(
            ["python3", "tool/agent_loop.py", "--help"], cwd=self.repo,
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(loop_help.returncode, 0, loop_help.stderr)
        self.assertIn("--draft-pr", loop_help.stdout)
        see_help = subprocess.run(
            ["python3", "tool/see_screen.py", "--help"], cwd=self.repo,
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(see_help.returncode, 0, see_help.stderr)
        self.assertIn("--route", see_help.stdout)

    def test_rerun_is_idempotent_and_changes_nothing(self) -> None:
        self.flutter_app()
        self.assert_success(self.run_installer())
        before = {
            name: (self.repo / name).read_text(encoding="utf-8")
            for name in ("tool/preflight.py", "tool/ci_watch.py",
                         "tool/agent_loop.py", "AGENTS.md")
        }
        second = self.run_installer()
        self.assert_success(second)
        self.assertIn("already installed; nothing changed", second.stdout)
        after = {
            name: (self.repo / name).read_text(encoding="utf-8")
            for name in ("tool/preflight.py", "tool/ci_watch.py",
                         "tool/agent_loop.py", "AGENTS.md")
        }
        self.assertEqual(before, after)
        self.assertFalse((self.repo / ".agent-pack-backups").exists())

    def test_piped_bash_installs_the_same_files(self) -> None:
        self.flutter_app()
        result = self.run_installer(piped=True)
        self.assert_success(result)
        self.assertTrue((self.repo / "tool/preflight.py").is_file())
        self.assertTrue((self.repo / "tool/agent_loop.py").is_file())
        self.assertTrue((self.repo / "AGENTS.md").is_file())

    def test_existing_agents_md_keeps_its_content(self) -> None:
        self.flutter_app()
        existing = textwrap.dedent(
            """\
            # AGENTS.md — demo_app

            ## House rules (mine, keep them)

            - Never touch the payment module without review.
            """
        )
        (self.repo / "AGENTS.md").write_text(existing, encoding="utf-8")
        result = self.run_installer()
        self.assert_success(result)
        agents = self.agents_md()
        self.assertIn("Never touch the payment module without review.", agents)
        self.assertIn("House rules (mine, keep them)", agents)
        self.assertEqual(agents.count(HED), 1)
        # The managed block lands below the title, above the project's own text.
        self.assertLess(agents.index("# AGENTS.md — demo_app"), agents.index(HED))
        self.assertLess(agents.index(TAIL), agents.index("House rules"))
        rerun = self.run_installer()
        self.assert_success(rerun)
        self.assertIn("nothing changed", rerun.stdout)

    def test_existing_agents_md_without_a_title_gets_the_block_on_top(self) -> None:
        self.flutter_app()
        (self.repo / "AGENTS.md").write_text("Just a note.\n", encoding="utf-8")
        self.assert_success(self.run_installer())
        agents = self.agents_md()
        self.assertTrue(agents.index(HED) < agents.index("Just a note."))
        self.assertEqual(agents.count(HED), 1)

    def test_old_managed_block_is_replaced_in_place(self) -> None:
        self.flutter_app()
        self.assert_success(self.run_installer())
        stale = self.agents_md().replace(f"{HED} {VERSION}", f"{HED} v0.0.1")
        stale += "\n## My own notes\n\nKeep me.\n"
        (self.repo / "AGENTS.md").write_text(stale, encoding="utf-8")
        result = self.run_installer()
        self.assert_success(result)
        self.assertIn("Will update (managed block)", result.stdout)
        agents = self.agents_md()
        self.assertIn(f"{HED} {VERSION}", agents)
        self.assertNotIn("v0.0.1", agents)
        self.assertEqual(agents.count(HED), 1)
        self.assertEqual(agents.count(TAIL), 1)
        self.assertIn("Keep me.", agents)

    def test_dry_run_writes_nothing(self) -> None:
        self.flutter_app()
        result = self.run_installer("--dry-run")
        self.assert_success(result)
        self.assertIn("Will add: tool/preflight.py", result.stdout)
        self.assertIn("no files were changed", result.stdout)
        self.assertFalse((self.repo / "tool").exists())
        self.assertFalse((self.repo / "AGENTS.md").exists())

    def test_conflicting_tool_file_aborts_until_forced(self) -> None:
        self.flutter_app()
        tool = self.repo / "tool"
        tool.mkdir()
        (tool / "preflight.py").write_text("# my own checker\n", encoding="utf-8")
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CONFLICT", result.stdout)
        self.assertIn("nothing was changed", result.stderr)
        self.assertEqual((tool / "preflight.py").read_text(), "# my own checker\n")
        self.assertFalse((self.repo / "AGENTS.md").exists())
        self.assertFalse((tool / "ci_watch.py").exists())

        forced = self.run_installer("--force")
        self.assert_success(forced)
        self.assertEqual(
            (tool / "preflight.py").read_text(encoding="utf-8"),
            (PACK / "preflight.py").read_text(encoding="utf-8"),
        )
        backups = list((self.repo / ".agent-pack-backups").glob("*/preflight.py"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "# my own checker\n")

    def test_force_dry_run_does_not_back_up(self) -> None:
        self.flutter_app()
        tool = self.repo / "tool"
        tool.mkdir()
        (tool / "preflight.py").write_text("# mine\n", encoding="utf-8")
        result = self.run_installer("--force", "--dry-run")
        self.assert_success(result)
        self.assertFalse((self.repo / ".agent-pack-backups").exists())
        self.assertEqual((tool / "preflight.py").read_text(), "# mine\n")

    def test_symlinked_tool_directory_is_refused(self) -> None:
        self.flutter_app()
        outside = Path(self.temp.name) / "elsewhere"
        outside.mkdir()
        (self.repo / "tool").symlink_to(outside, target_is_directory=True)
        result = self.run_installer("--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_runs_from_a_subdirectory_and_uses_the_git_root(self) -> None:
        self.flutter_app()
        nested = self.repo / "lib" / "screens"
        nested.mkdir(parents=True)
        result = self.run_installer(cwd=nested)
        self.assert_success(result)
        self.assertTrue((self.repo / "tool/preflight.py").is_file())
        self.assertTrue((self.repo / "AGENTS.md").is_file())
        self.assertFalse((nested / "tool").exists())

    def test_app_name_falls_back_when_pubspec_is_missing(self) -> None:
        result = self.run_installer()
        self.assert_success(result)
        self.assertTrue(self.agents_md().startswith("# AGENTS.md — project"), self.agents_md()[:60])

    def test_help_works_anywhere(self) -> None:
        result = self.run_installer("--help", piped=True)
        self.assert_success(result)
        self.assertIn("--dry-run", result.stdout)
        self.assertFalse((self.repo / "tool").exists())


class PreflightToolTests(unittest.TestCase):
    """The shipped checker must catch the failure that motivated it."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "lib").mkdir()

    def run_preflight(self, source: str) -> subprocess.CompletedProcess[str]:
        (self.root / "lib" / "sample.dart").write_text(source, encoding="utf-8")
        return subprocess.run(
            ["python3", str(PACK / "preflight.py"), "lib"],
            cwd=self.root, text=True, capture_output=True, check=False,
        )

    def test_unused_optional_parameter_is_reported(self) -> None:
        result = self.run_preflight(textwrap.dedent(
            """\
            import 'package:flutter/material.dart';

            class Home extends StatelessWidget {
              const Home({super.key});
              @override
              Widget build(BuildContext context) => const _Tile(title: 'Hi');
            }

            class _Tile extends StatelessWidget {
              final String title;
              final Widget? footer;

              const _Tile({required this.title, this.footer});

              @override
              Widget build(BuildContext context) => Text(title);
            }
            """
        ))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("optional parameter 'footer' of _Tile is never passed", result.stdout)

    def test_removed_private_widget_is_reported(self) -> None:
        result = self.run_preflight(textwrap.dedent(
            """\
            class _Forgotten extends StatelessWidget {
              const _Forgotten();
            }
            """
        ))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("private class _Forgotten is never used", result.stdout)

    def test_unused_import_alias_is_reported(self) -> None:
        """Regression: the import checks used to run on text whose string
        literals had been blanked, so `import '…' as alias;` could never match
        and an unused alias was silently accepted."""
        result = self.run_preflight(textwrap.dedent(
            """\
            import 'package:flutter/material.dart' as mat;

            class A {
              void go() {}
            }
            """
        ))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("import alias 'mat' is unused", result.stdout)

    def test_print_in_lib_is_reported_but_not_in_test(self) -> None:
        lib = self.run_preflight(textwrap.dedent(
            """\
            class A {
              void go() {
                print('debugging');
              }
            }
            """
        ))
        self.assertEqual(lib.returncode, 1, lib.stdout)
        self.assertIn("avoid_print", lib.stdout)

        (self.root / "lib" / "sample.dart").unlink()
        test_dir = self.root / "test"
        test_dir.mkdir()
        (test_dir / "a_test.dart").write_text(
            "void main() {\n  print('a print in a test is normal');\n}\n",
            encoding="utf-8")
        quiet = subprocess.run(
            ["python3", str(PACK / "preflight.py"), "test"],
            cwd=self.root, text=True, capture_output=True, check=False,
        )
        self.assertEqual(quiet.returncode, 0, quiet.stdout + quiet.stderr)

    def test_unused_private_field_is_reported(self) -> None:
        result = self.run_preflight(textwrap.dedent(
            """\
            class Tile {
              final int _height = 40;
              const Tile();
            }
            """
        ))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("private member '_height' is declared but never used again",
                      result.stdout)

    def test_a_field_used_in_a_string_still_counts_as_used(self) -> None:
        result = self.run_preflight(textwrap.dedent(
            """\
            class Tile {
              final int _height = 40;
              const Tile();
              String label() => 'height: $_height';
            }
            """
        ))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_orphan_file_and_ambiguous_import_are_reported(self) -> None:
        (self.root / "lib" / "home.dart").write_text(textwrap.dedent(
            """\
            import 'package:demo_app/header_a.dart';
            import 'package:demo_app/header_b.dart';

            class Home {
              final Header header = Header();
            }
            """
        ), encoding="utf-8")
        (self.root / "lib" / "header_a.dart").write_text(
            "class Header {\n  const Header();\n}\n", encoding="utf-8")
        (self.root / "lib" / "header_b.dart").write_text(
            "class Header {\n  const Header();\n}\n", encoding="utf-8")
        (self.root / "lib" / "orphan.dart").write_text(
            "class OrphanCard {\n  const OrphanCard();\n}\n", encoding="utf-8")
        (self.root / "pubspec.yaml").write_text("name: demo_app\n", encoding="utf-8")
        result = subprocess.run(
            ["python3", str(PACK / "preflight.py")],
            cwd=self.root, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("orphan file", result.stdout)
        self.assertIn("ambiguous_import", result.stdout)

    def test_clean_file_passes(self) -> None:
        result = self.run_preflight(textwrap.dedent(
            """\
            // A comment mentioning _Tile must not count as a use.
            class Home {
              const Home({this.a = 1, this.b = 2});
              final int a;
              final int b;
            }

            int useIt() => const Home(a: 1).a;
            """
        ))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 issue(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
