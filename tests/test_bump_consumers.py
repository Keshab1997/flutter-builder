"""The tag -> pull-request fan-out.

A pushed tag is a release every consumer feels at once, so this workflow is the
one place that reaches *into other repositories*. These checks hold the shape
that makes that safe: one shared token, a PR per project (never a push to a
default branch), a pinning rule identical to `bump-ref.sh`, and a dry run that
cannot write. Nothing here needs Flutter, network access or the GitHub CLI.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bump-consumers.sh"
BUMP_REF = ROOT / "scripts" / "bump-ref.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "bump-consumers.yml"

REAL_GIT = shutil.which("git") or "/usr/bin/git"
OWNER = "testorg"

# ---------------------------------------------------------------------------
# Offline fakes
#
# FAKE_GH is a scriptable `gh` stand-in: it serves repo discovery, the default
# branch, workflow contents, the open-PR list, PR creation, PR comments and PR
# closes from a JSON state file, so the E2E tests below need no network and no
# real GitHub. FAKE_GIT copies a local fixture repo on `git clone` and makes
# push/fetch no-ops, delegating everything else to real git.
# ---------------------------------------------------------------------------

FAKE_GH = r'''#!/usr/bin/env python3
"""Scriptable fake gh CLI for the bump-consumers end-to-end tests."""

import json
import os
import sys


STATE_PATH = os.environ["FAKE_GH_STATE"]
FIXTURES = os.environ["FAKE_GH_FIXTURES"]


def load():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"repos": [], "open_prs": [], "comments": [], "created": [], "closed": []}


def save(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE_PATH)


def flag_value(args, flag):
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
    return None


def run(state, args):
    if not args:
        return
    cmd = args[0]
    if cmd == "repo":
        # gh repo list <owner> --limit 500 --json name,isArchived --jq ...
        names = state.get("repos", [])
        sys.stdout.write(("\n".join(names) + "\n") if names else "")
        return
    if cmd == "api":
        path = next((a for a in args[1:] if a.startswith("repos/")), None)
        if path is None:
            return
        base = path.split("?", 1)[0]
        parts = base.split("/")
        if len(parts) < 3:
            return
        owner, name = parts[1], parts[2]
        repo = f"{owner}/{name}"
        jq = flag_value(args, "--jq")
        if base == f"repos/{owner}/{name}":
            if jq == ".default_branch":
                sys.stdout.write("main\n")
            else:
                sys.stdout.write(json.dumps({"default_branch": "main"}) + "\n")
            return
        if base == f"repos/{owner}/{name}/contents/.github/workflows":
            wf = os.path.join(FIXTURES, name, ".github", "workflows")
            for fn in sorted(os.listdir(wf)) if os.path.isdir(wf) else []:
                if fn.endswith((".yml", ".yaml")):
                    sys.stdout.write(fn + "\n")
            return
        if base.startswith(f"repos/{owner}/{name}/contents/"):
            filename = base.rsplit("/", 1)[-1]
            fp = os.path.join(FIXTURES, name, ".github", "workflows", filename)
            if os.path.isfile(fp):
                sys.stdout.write(open(fp, encoding="utf-8").read())
            return
        segs = base.split("/")
        if len(segs) >= 5 and segs[3] == "issues" and "-X" in args and "POST" in args:
            # gh api -X POST repos/owner/name/issues/<n>/comments -f body=...
            number = int(segs[4])
            body = next((a[len("body="):] for a in args if a.startswith("body=")), "")
            state.setdefault("comments", []).append({"pr": number, "body": body, "repo": repo})
            return
        if base == f"repos/{owner}/{name}/pulls":
            # Mirror the script's jq: same-repo PRs only (forks are never
            # commented on or closed), emitted as number/url/head-ref TSV.
            tab = chr(9)
            nl = chr(10)
            prs = [
                p
                for p in state.get("open_prs", [])
                if p.get("repo") == repo
                and p.get("head", {}).get("repo", {}).get("full_name")
                == p.get("base", {}).get("repo", {}).get("full_name")
            ]
            for p in prs:
                sys.stdout.write(
                    str(p["number"])
                    + tab
                    + p["html_url"]
                    + tab
                    + str(p.get("head", {}).get("ref", ""))
                    + nl
                )
            return
        return
    if cmd == "pr":
        sub = args[1] if len(args) > 1 else ''
        if sub == "list":
            repo = flag_value(args, "--repo")
            head = flag_value(args, "--head")
            for pr in state.get("open_prs", []):
                if pr.get("repo") == repo and pr.get("head", {}).get("ref") == head:
                    sys.stdout.write(pr["html_url"] + "\n")
                    return
            sys.stdout.write("\n")
            return
        if sub == "create":
            repo = flag_value(args, "--repo")
            head = flag_value(args, "--head")
            body = flag_value(args, "--body")
            nums = [p["number"] for p in state.get("open_prs", [])] + \
                   [c["number"] for c in state.get("closed", [])]
            number = (max(nums) + 1) if nums else 1
            url = f"https://github.com/{repo}/pull/{number}"
            entry = {
                "number": number,
                "html_url": url,
                "head": {"ref": head, "repo": {"full_name": repo}},
                "base": {"repo": {"full_name": repo}},
                "repo": repo,
            }
            state.setdefault("open_prs", []).append(entry)
            state.setdefault("created", []).append({**entry, "body": body})
            sys.stdout.write(url + "\n")
            return
        if sub == "comment":
            number = int(args[2])
            body = flag_value(args, "--body")
            state.setdefault("comments", []).append({"pr": number, "body": body, "repo": flag_value(args, "--repo")})
            return
        if sub == "close":
            number = int(args[2])
            repo = flag_value(args, "--repo")
            delete = "--delete-branch" in args
            state["open_prs"] = [
                p for p in state.get("open_prs", [])
                if not (p["number"] == number and p.get("repo") == repo)
            ]
            state.setdefault("closed", []).append(
                {"number": number, "repo": repo, "delete_branch": delete}
            )
            return
    # Anything the script doesn't depend on is a silent no-op.


def main():
    state = load()
    try:
        run(state, sys.argv[1:])
    finally:
        save(state)


if __name__ == "__main__":
    main()
'''


FAKE_GIT = r'''#!/usr/bin/env bash
# Offline fake `git`: `clone` copies a local fixture repo; push/fetch are
# no-ops; everything else delegates to real git.
case "$1" in
  clone)
    shift
    dest="${@: -1}"
    name="$(basename -- "$dest")"
    cp -r -- "$FAKE_GH_FIXTURES/$name" "$dest"
    echo "git clone $dest" >> "$GIT_LOG"
    exit 0
    ;;
esac
for arg in "$@"; do
  case "$arg" in
    push|fetch)
      echo "git $arg" >> "$GIT_LOG"
      exit 0
      ;;
  esac
done
echo "git $*" >> "$GIT_LOG"
exec "$REAL_GIT_PATH" "$@"
'''


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


class E2EHarness:
    """Runs bump-consumers.sh against the fake gh/git in a temp directory."""

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="bump-consumers-e2e-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.fixtures = self.tmp / "fixtures"
        self.fixtures.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "gh").write_text(FAKE_GH, encoding="utf-8")
        (self.bin / "gh").chmod(0o755)
        (self.bin / "git").write_text(FAKE_GIT, encoding="utf-8")
        (self.bin / "git").chmod(0o755)
        self.state_path = self.tmp / "state.json"
        self.state_path.write_text("{}", encoding="utf-8")
        self.git_log = self.tmp / "git.log"
        self.git_log.write_text("", encoding="utf-8")
        self.env = {
            "GH_TOKEN": "dummy-token",
            "HOME": str(self.home),
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_GH_STATE": str(self.state_path),
            "FAKE_GH_FIXTURES": str(self.fixtures),
            "REAL_GIT_PATH": REAL_GIT,
            "GIT_LOG": str(self.git_log),
        }

    def seed(self, name: str, workflows: dict[str, str], branch: str = "main") -> None:
        """Create (or refresh) a local fixture repo with the given workflow files."""
        repo = self.fixtures / name
        repo.mkdir(parents=True, exist_ok=True)
        (repo / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        for filename, content in workflows.items():
            (repo / ".github" / "workflows" / filename).write_text(content, encoding="utf-8")
        git = [REAL_GIT, "-C", str(repo)]
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["config", "user.email", "t@t"], check=True)
        subprocess.run(git + ["config", "user.name", "t"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "init"], check=False)
        subprocess.run(git + ["branch", "-m", branch], check=True)

    def write_state(self, repos: list[str], open_prs: list[dict]) -> None:
        self.state_path.write_text(
            json.dumps(
                {"repos": repos, "open_prs": open_prs, "comments": [], "created": [], "closed": []},
                indent=1,
            ),
            encoding="utf-8",
        )

    def run_script(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            capture_output=True,
            text=True,
            check=False,
            env=self.env,
        )

    def state(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))


class SupersedeTests(unittest.TestCase):
    """End-to-end: stale chore/flutter-builder-* PRs get superseded."""

    WORKFLOWS_A = {
        "ci.yml": "uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.0.0\n",
        "other.yml": "uses: actions/checkout@v5\n",
    }
    WORKFLOWS_CURRENT = {
        "ci.yml": "uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v2.0.0\n",
        "other.yml": "uses: actions/checkout@v5\n",
    }
    AGENTS_OLD = """# app-a

<!-- flutter-builder:agent-pack:start v1.0.0 -->
old managed block
<!-- flutter-builder:agent-pack:end -->

Project notes.
"""

    def setUp(self) -> None:
        self.harness = E2EHarness()
        self.h = self.harness
        self.h.seed("app-a", self.WORKFLOWS_A)
        self.h.seed("app-b", {"ci.yml": "uses: actions/checkout@v5\n"})  # not connected
        self.h.write_state(
            ["app-a", "app-b"],
            [
                {"number": 7, "html_url": "https://github.com/testorg/app-a/pull/7",
                 "head": {"ref": "fix/unrelated", "repo": {"full_name": "testorg/app-a"}},
                 "base": {"repo": {"full_name": "testorg/app-a"}},
                 "repo": "testorg/app-a"},
                {"number": 9, "html_url": "https://github.com/testorg/app-a/pull/9",
                 "head": {"ref": "chore/flutter-builder-v1.0.0", "repo": {"full_name": "testorg/app-a"}},
                 "base": {"repo": {"full_name": "testorg/app-a"}},
                 "repo": "testorg/app-a"},
            ],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.harness.tmp, ignore_errors=True)

    def test_supersedes_stale_prs_ignores_unrelated(self) -> None:
        result = self.h.run_script("--ref", "v2.0.0", "--owner", OWNER, "--repos", "app-a,app-b")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.h.state()

        # A new PR was opened for the connected project.
        created = state["created"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["head"]["ref"], "chore/flutter-builder-v2.0.0")
        self.assertEqual(created[0]["repo"], "testorg/app-a")
        new_url = created[0]["html_url"]

        # The stale same-repo chore/flutter-builder-* PR was commented and
        # closed with --delete-branch; the unrelated PR and other repos were
        # untouched.
        self.assertEqual(
            state["closed"],
            [{"number": 9, "repo": "testorg/app-a", "delete_branch": True}],
        )
        self.assertEqual(len(state["comments"]), 1)
        self.assertEqual(state["comments"][0]["pr"], 9)
        self.assertIn(new_url, state["comments"][0]["body"])
        open_heads = {pr["head"]["ref"] for pr in state["open_prs"]}
        self.assertIn("fix/unrelated", open_heads)
        self.assertIn("chore/flutter-builder-v2.0.0", open_heads)
        self.assertNotIn("chore/flutter-builder-v1.0.0", open_heads)
        self.assertTrue(all(c["repo"] == "testorg/app-a" for c in created))

        # ~/.gitconfig is never touched: HOME is fresh and has no git config.
        self.assertFalse((self.h.home / ".gitconfig").exists())
        self.assertIn("git push", self.h.git_log.read_text(encoding="utf-8"))

    def test_refresh_path_skips_its_own_pr(self) -> None:
        self.h.write_state(
            ["app-a"],
            [{"number": 3, "html_url": "https://github.com/testorg/app-a/pull/3",
              "head": {"ref": "chore/flutter-builder-v2.0.0", "repo": {"full_name": "testorg/app-a"}},
              "base": {"repo": {"full_name": "testorg/app-a"}},
              "repo": "testorg/app-a"}],
        )
        result = self.h.run_script("--ref", "v2.0.0", "--owner", OWNER, "--repos", "app-a")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.h.state()
        # The existing PR on the same branch is refreshed, not duplicated or closed.
        self.assertEqual(state["created"], [])
        self.assertEqual(state["closed"], [])
        self.assertEqual(state["comments"], [])
        self.assertEqual({pr["number"] for pr in state["open_prs"]}, {3})

    def test_dry_run_is_side_effect_free(self) -> None:
        result = self.h.run_script("--ref", "v2.0.0", "--owner", OWNER,
                                   "--repos", "app-a,app-b", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run: 1 project(s) would get a PR", result.stdout)
        state = self.h.state()
        self.assertEqual(state["created"], [])
        self.assertEqual(state["closed"], [])
        self.assertEqual(state["comments"], [])
        self.assertNotIn("push", self.h.git_log.read_text(encoding="utf-8"))
        self.assertFalse((self.h.home / ".gitconfig").exists())

    def test_fork_pr_with_bump_branch_is_never_touched(self) -> None:
        self.h.seed("app-a", self.WORKFLOWS_A)
        self.h.write_state(
            ["app-a"],
            [
                {"number": 7, "html_url": "https://github.com/testorg/app-a/pull/7",
                 "head": {"ref": "fix/unrelated", "repo": {"full_name": "testorg/app-a"}},
                 "base": {"repo": {"full_name": "testorg/app-a"}}, "repo": "testorg/app-a"},
                {"number": 9, "html_url": "https://github.com/testorg/app-a/pull/9",
                 "head": {"ref": "chore/flutter-builder-v1.0.0", "repo": {"full_name": "testorg/app-a"}},
                 "base": {"repo": {"full_name": "testorg/app-a"}}, "repo": "testorg/app-a"},
                {"number": 11, "html_url": "https://github.com/testorg/app-a/pull/11",
                 "head": {"ref": "chore/flutter-builder-v1.0.0", "repo": {"full_name": "forker/app-a"}},
                 "base": {"repo": {"full_name": "testorg/app-a"}}, "repo": "testorg/app-a"},
            ],
        )
        result = self.h.run_script("--ref", "v2.0.0", "--owner", OWNER, "--repos", "app-a")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.h.state()

        # The same-repo stale PR is superseded; the fork PR (same head branch
        # name, different head repo) is never commented on or closed.
        created = state["created"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["head"]["ref"], "chore/flutter-builder-v2.0.0")
        new_url = created[0]["html_url"]
        self.assertEqual(
            state["closed"],
            [{"number": 9, "repo": "testorg/app-a", "delete_branch": True}],
        )
        self.assertEqual([c["pr"] for c in state["comments"]], [9])
        self.assertIn(new_url, state["comments"][0]["body"])
        open_heads = {(pr["number"], pr["head"]["ref"]) for pr in state["open_prs"]}
        self.assertIn((7, "fix/unrelated"), open_heads)
        self.assertIn((11, "chore/flutter-builder-v1.0.0"), open_heads)
        self.assertIn((created[0]["number"], "chore/flutter-builder-v2.0.0"), open_heads)

    def test_with_agent_pack_upgrades_when_workflows_current(self) -> None:
        self.h.seed("app-a", self.WORKFLOWS_CURRENT)
        app_a = self.h.fixtures / "app-a"
        (app_a / "AGENTS.md").write_text(self.AGENTS_OLD, encoding="utf-8")
        git = [REAL_GIT, "-C", str(app_a)]
        subprocess.run(git + ["add", "AGENTS.md"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "add AGENTS.md"], check=True)
        self.h.write_state(["app-a"], [])
        result = self.h.run_script("--ref", "v2.0.0", "--owner", OWNER,
                                   "--repos", "app-a", "--with-agent-pack")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Done: 1 project(s) updated", result.stdout)
        state = self.h.state()
        self.assertEqual(len(state["created"]), 1)
        self.assertIn("agent pack", state["created"][0]["body"].lower())
        self.assertEqual(state["closed"], [])
        self.assertIn("git push", self.h.git_log.read_text(encoding="utf-8"))

    def test_with_agent_pack_skips_repos_without_marker(self) -> None:
        self.h.seed("app-a", self.WORKFLOWS_CURRENT)
        self.h.write_state(["app-a"], [])
        result = self.h.run_script("--ref", "v2.0.0", "--owner", OWNER,
                                   "--repos", "app-a", "--with-agent-pack")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skip app-a (already at v2.0.0)", result.stdout)
        state = self.h.state()
        self.assertEqual(state["created"], [])
        self.assertEqual(state["closed"], [])

    def test_with_agent_pack_dry_run_is_side_effect_free(self) -> None:
        self.h.seed("app-a", self.WORKFLOWS_CURRENT)
        app_a = self.h.fixtures / "app-a"
        (app_a / "AGENTS.md").write_text(self.AGENTS_OLD, encoding="utf-8")
        git = [REAL_GIT, "-C", str(app_a)]
        subprocess.run(git + ["add", "AGENTS.md"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "add AGENTS.md"], check=True)
        self.h.write_state(["app-a"], [])
        result = self.h.run_script("--ref", "v2.0.0", "--owner", OWNER,
                                   "--repos", "app-a", "--with-agent-pack", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("would open a PR", result.stdout)
        state = self.h.state()
        self.assertEqual(state["created"], [])
        self.assertEqual(state["closed"], [])
        self.assertEqual(state["comments"], [])
        self.assertNotIn("git push", self.h.git_log.read_text(encoding="utf-8"))

    def test_with_agent_pack_dry_run_detects_outdated_tool_file(self) -> None:
        self.h.seed("app-a", self.WORKFLOWS_CURRENT)
        app_a = self.h.fixtures / "app-a"
        pack_installer = ROOT / "scripts" / "install-agent-pack.sh"
        subprocess.run(["bash", str(pack_installer)], cwd=app_a, check=True,
                       capture_output=True, text=True)
        (app_a / "tool" / "preflight.py").write_text("# stale copy\n",
                                                     encoding="utf-8")
        git = [REAL_GIT, "-C", str(app_a)]
        subprocess.run(git + ["add", "AGENTS.md", "tool", ".gitignore"],
                       check=True)
        subprocess.run(git + ["commit", "-q", "-m", "pack with stale tool"],
                       check=True)
        self.h.write_state(["app-a"], [])
        result = self.h.run_script("--ref", "v2.0.0", "--owner", OWNER,
                                   "--repos", "app-a", "--with-agent-pack",
                                   "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("app-a: would open a PR (agent pack -> @v2.0.0)",
                      result.stdout)
        self.assertEqual(self.h.state()["created"], [])

    def test_with_agent_pack_stages_newly_added_untracked_tool_file(self) -> None:
        self.h.seed("app-a", self.WORKFLOWS_CURRENT)
        app_a = self.h.fixtures / "app-a"
        pack_installer = ROOT / "scripts" / "install-agent-pack.sh"
        subprocess.run(["bash", str(pack_installer)], cwd=app_a, check=True,
                       capture_output=True, text=True)
        (app_a / "tool" / "local_screenshots.py").unlink()
        git = [REAL_GIT, "-C", str(app_a)]
        subprocess.run(git + ["add", "AGENTS.md", "tool", ".gitignore"],
                       check=True)
        subprocess.run(git + ["commit", "-q", "-m", "pack missing one file"],
                       check=True)
        self.h.write_state(["app-a"], [])
        result = self.h.run_script("--ref", "v2.0.0", "--owner", OWNER,
                                   "--repos", "app-a", "--with-agent-pack")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("tool/local_screenshots.py", result.stdout)
        self.assertEqual(len(self.h.state()["created"]), 1)

    def test_with_agent_pack_installer_error_fails_cleanly_without_pr(self) -> None:
        self.h.seed("app-a", self.WORKFLOWS_CURRENT)
        app_a = self.h.fixtures / "app-a"
        (app_a / "real-agents.md").write_text(self.AGENTS_OLD, encoding="utf-8")
        (app_a / "AGENTS.md").symlink_to("real-agents.md")
        git = [REAL_GIT, "-C", str(app_a)]
        subprocess.run(git + ["add", "real-agents.md", "AGENTS.md"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "symlink AGENTS.md"],
                       check=True)
        self.h.write_state(["app-a"], [])
        result = self.h.run_script("--ref", "v2.0.0", "--owner", OWNER,
                                   "--repos", "app-a", "--with-agent-pack")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("agent-pack sync failed", result.stdout)
        self.assertEqual(self.h.state()["created"], [])


class ScriptShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SCRIPT.is_file(), f"missing {SCRIPT}")
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_script_is_valid_bash(self) -> None:
        result = subprocess.run(["bash", "-n", str(SCRIPT)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_it_reuses_bump_ref_instead_of_reimplementing_the_rewrite(self) -> None:
        """Two copies of the pin regex is exactly how deploy and cleanup drifted."""
        self.assertIn("bump-ref.sh", self.text)
        self.assertNotIn("sed -E", self.text,
                         "bump-consumers.sh must delegate the rewrite to bump-ref.sh")

    def test_it_accepts_the_same_ref_rule_as_bump_ref(self) -> None:
        bump = BUMP_REF.read_text(encoding="utf-8")
        for fragment in ("^v[0-9]+", "40-character commit SHA"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)
                self.assertIn(fragment, bump)

    def test_it_requires_a_token_that_can_write(self) -> None:
        self.assertIn("GH_TOKEN", self.text)
        self.assertIn("open pull requests", self.text)

    def test_discovery_is_automatic_but_overridable(self) -> None:
        self.assertIn("gh repo list", self.text)
        self.assertIn("--repos", self.text)
        self.assertIn("REUSABLE_PREFIX", self.text)

    def test_one_pull_request_per_project_never_a_push_to_its_branch(self) -> None:
        self.assertIn("gh pr create", self.text)
        self.assertIn("gh pr list", self.text)
        self.assertNotIn("pr merge", self.text)
        self.assertNotIn("--auto", self.text)

    def test_it_never_force_pushes_without_a_lease(self) -> None:
        self.assertIn("--force-with-lease", self.text)
        self.assertNotRegex(
            self.text, r"push[^\n]*--force(?!-with-lease)",
            "a bare --force can drop a consumer's own commits",
        )

    def test_the_branch_name_is_derived_from_the_ref(self) -> None:
        self.assertIn("BRANCH_PREFIX", self.text)
        self.assertRegex(self.text, r'BRANCH_PREFIX\$ref|BRANCH_PREFIX.*\$ref')

    def test_dry_run_returns_before_it_can_push(self) -> None:
        self.assertIn("--dry-run", self.text)
        self.assertRegex(
            self.text,
            r'if \[ "\$dry_run" = true \]; then[\s\S]*?\n\s*continue',
            "the dry-run branch must not fall through into push/PR code",
        )

    def test_it_isolates_git_auth_from_the_caller(self) -> None:
        "GIT_CONFIG_GLOBAL inside $work, chmod 600, never ~/.gitconfig."
        self.assertIn("GIT_CONFIG_GLOBAL", self.text)
        self.assertIn("chmod 600", self.text)
        self.assertNotRegex(self.text, r"git config --global[^\n]*\$HOME",
                            "git auth must not write into $HOME/.gitconfig")

    def test_it_supersedes_stale_pin_bump_prs(self) -> None:
        self.assertIn("gh pr close", self.text)
        self.assertIn("--delete-branch", self.text)
        self.assertIn("BRANCH_PREFIX", self.text)
        self.assertIn("warn", self.text)

    def test_it_protects_fork_prs_in_the_supersede_query(self) -> None:
        "A contributor fork PR named chore/flutter-builder-* is never closed."
        self.assertIn("head.repo.full_name == .base.repo.full_name", self.text)

    def test_it_offers_opt_in_agent_pack_sync(self) -> None:
        "--with-agent-pack is off by default and drives install-agent-pack.sh."
        self.assertIn("--with-agent-pack", self.text)
        self.assertIn("install-agent-pack.sh", self.text)
        self.assertIn(".agent-pack-backups", self.text)
        self.assertIn("AGENTS.md", self.text)


class WorkflowShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(WORKFLOW.is_file(), f"missing {WORKFLOW}")
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_it_fires_on_a_release_tag_and_by_hand(self) -> None:
        self.assertRegex(self.text, r'(?m)^  push:\n    tags:\n      - "v\*"$')
        self.assertIn("  workflow_dispatch:", self.text)

    def test_the_tag_can_be_given_by_hand_to_backfill_a_release(self) -> None:
        self.assertRegex(self.text, r"(?m)^      ref:\n")
        self.assertIn("EVENT_TAG", self.text)
        self.assertIn("INPUT_REF", self.text)

    def test_it_runs_the_script_with_one_shared_token(self) -> None:
        self.assertIn("bump-consumers.sh", self.text)
        self.assertIn("GH_TOKEN: ${{ secrets.CONSUMER_TOKEN }}", self.text)

    def test_it_checks_out_this_repository_so_the_script_exists(self) -> None:
        # No `ref:` override: the workflow's own code comes from the tag that
        # fired it (or the branch dispatched), which is where the script lives.
        self.assertIn("uses: actions/checkout@v5", self.text)
        self.assertNotRegex(self.text, r"(?m)^\s+ref: v[0-9]")

    def test_permissions_stay_minimal_on_this_repository(self) -> None:
        self.assertIn("contents: read", self.text)
        self.assertNotIn("contents: write", self.text)

    def test_the_workflow_does_not_reach_into_consumers_itself(self) -> None:
        """Pushing/PR-ing is the script's job; keeping it out of YAML keeps one
        copy of the logic and one place to test it."""
        self.assertNotIn("git push", self.text)

    def test_two_releases_do_not_race(self) -> None:
        self.assertIn("group: bump-consumers", self.text)
        self.assertIn("cancel-in-progress: false", self.text)


class InvocationTests(unittest.TestCase):
    """Only the paths that stop before any network call are exercised."""

    def test_help_exits_zero(self) -> None:
        result = run("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GH_TOKEN", result.stdout)

    def test_missing_ref_is_rejected(self) -> None:
        result = run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("--ref is required", result.stderr)

    def test_a_branch_name_is_not_a_valid_ref(self) -> None:
        result = run("--ref", "main")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid --ref", result.stderr)

    def test_unknown_option_is_rejected(self) -> None:
        result = run("--nope")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Unknown option", result.stderr)

    def test_a_missing_token_stops_before_any_gh_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "gh-was-called"
            gh = Path(tmp) / "gh"
            gh.write_text(f"#!/usr/bin/env bash\ntouch {marker}\nexit 0\n")
            gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
            env = {k: v for k, v in os.environ.items()
                   if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
            env["PATH"] = f"{tmp}:{env['PATH']}"
            result = run("--ref", "v1.18.3", env=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("GH_TOKEN", result.stderr)
            self.assertFalse(marker.exists(),
                             "the token guard must run before any gh call")


if __name__ == "__main__":
    unittest.main()
