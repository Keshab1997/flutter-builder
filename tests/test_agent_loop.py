"""Behaviour of the agent pack's one-command loop (tool/agent_loop.py).

The refusals matter more than the happy path: the tool exists so an agent
cannot push a guess, cannot pile "fix ci" commits on a branch, and cannot
commit a keystore by accident. Each refusal is checked in a throw-away git
repository with a local bare remote - no network, no GitHub, no Flutter SDK.

No third-party modules.
"""

from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOP = ROOT / "agent-pack" / "agent_loop.py"


class AgentLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "app"
        self.repo.mkdir()
        self.git("init", "-q")
        # `git init` may still default to master on old git; the default-branch
        # refusal is what this suite checks, so the branch name must be known.
        self.git("checkout", "-q", "-b", "main")
        self.git("config", "user.email", "agent@example.com")
        self.git("config", "user.name", "Agent")
        (self.repo / "README.md").write_text("demo\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "chore: initial")
        self.remote = Path(self.temp.name) / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)],
                       check=True, capture_output=True)

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.repo, text=True,
                              capture_output=True, check=True)

    def run_loop(self, *args: str):
        return subprocess.run(["python3", str(LOOP), *args], cwd=self.repo,
                              text=True, capture_output=True, check=False)

    def commits(self) -> list[str]:
        out = self.git("log", "--pretty=%s").stdout.splitlines()
        return [line for line in out if line]

    def branch(self, name: str) -> None:
        self.git("checkout", "-q", "-b", name)

    # -- refusals ----------------------------------------------------------
    def test_refuses_to_commit_on_the_default_branch(self) -> None:
        (self.repo / "x.txt").write_text("x\n", encoding="utf-8")
        result = self.run_loop("-m", "feat: x")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("default branch", result.stderr)
        self.assertEqual(self.commits(), ["chore: initial"])

    def test_allows_the_default_branch_only_with_the_flag(self) -> None:
        (self.repo / "x.txt").write_text("x\n", encoding="utf-8")
        result = self.run_loop("-m", "feat: x", "--allow-main", "--no-push")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.commits()[0], "feat: x")

    def test_refuses_credential_looking_files_before_committing(self) -> None:
        self.branch("feat/secrets")
        (self.repo / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
        (self.repo / "app.keystore").write_bytes(b"\x00binary")
        result = self.run_loop("-m", "chore: config", "--no-push")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("credentials", result.stderr)
        self.assertIn(".env", result.stderr)
        self.assertEqual(self.commits(), ["chore: initial"])

    def test_credentials_can_be_allowed_deliberately(self) -> None:
        self.branch("feat/secrets")
        (self.repo / "example.env").write_text("nothing secret\n", encoding="utf-8")
        result = self.run_loop("-m", "docs: sample env", "--no-push",
                               "--allow-secret-paths")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.commits()[0], "docs: sample env")

    def test_preflight_findings_stop_the_loop_before_the_commit(self) -> None:
        self.branch("feat/print")
        lib = self.repo / "lib"
        lib.mkdir()
        (lib / "debug.dart").write_text(textwrap.dedent(
            """\
            class Debug {
              void go() {
                print('left behind');
              }
            }
            """
        ), encoding="utf-8")
        result = self.run_loop("-m", "feat: debug helper", "--no-push")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("preflight", result.stderr)
        self.assertIn("avoid_print", result.stdout)
        self.assertEqual(self.commits(), ["chore: initial"])

    def test_no_preflight_is_the_escape_hatch(self) -> None:
        self.branch("feat/print")
        lib = self.repo / "lib"
        lib.mkdir()
        (lib / "debug.dart").write_text("void go() { print('x'); }\n", encoding="utf-8")
        result = self.run_loop("-m", "feat: debug helper", "--no-push",
                               "--no-preflight")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.commits()[0], "feat: debug helper")

    # -- the loop itself ---------------------------------------------------
    def test_commit_and_push_reach_the_remote(self) -> None:
        self.branch("feat/readme")
        self.git("remote", "add", "origin", str(self.remote))
        (self.repo / "README.md").write_text("demo, edited\n", encoding="utf-8")
        result = self.run_loop("-m", "docs: edit the readme", "--no-watch",
                               "--no-preflight")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Pushed", result.stdout)
        remote_log = subprocess.run(
            ["git", "--git-dir", str(self.remote), "log", "--pretty=%s",
             "refs/heads/feat/readme"],
            text=True, capture_output=True, check=True).stdout.splitlines()
        self.assertEqual(remote_log[0], "docs: edit the readme")

    def test_amend_rewrites_the_last_commit(self) -> None:
        self.branch("feat/amend")
        (self.repo / "a.txt").write_text("a\n", encoding="utf-8")
        self.run_loop("-m", "feat: first attempt", "--no-push", "--no-preflight")
        (self.repo / "a.txt").write_text("a, fixed\n", encoding="utf-8")
        result = self.run_loop("-m", "feat: fixed", "--amend", "--no-push",
                               "--no-preflight")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.commits()[0], "feat: fixed")
        self.assertEqual(len(self.commits()), 2)

    def test_nothing_staged_is_reported_not_committed(self) -> None:
        self.branch("feat/empty")
        result = self.run_loop("-m", "chore: nothing", "--no-push",
                               "--no-preflight")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("nothing staged", result.stdout)

    def test_message_is_required(self) -> None:
        result = self.run_loop("--no-push")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("--message", result.stderr)

    def test_help_works_anywhere(self) -> None:
        result = self.run_loop("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--allow-secret-paths", result.stdout)
        self.assertIn("--force-with-lease", result.stdout)


if __name__ == "__main__":
    unittest.main()
