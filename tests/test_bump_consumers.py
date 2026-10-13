"""The tag -> pull-request fan-out.

A pushed tag is a release every consumer feels at once, so this workflow is the
one place that reaches *into other repositories*. These checks hold the shape
that makes that safe: one shared token, a PR per project (never a push to a
default branch), a pinning rule identical to `bump-ref.sh`, and a dry run that
cannot write. Nothing here needs Flutter, network access or the GitHub CLI.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bump-consumers.sh"
BUMP_REF = ROOT / "scripts" / "bump-ref.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "bump-consumers.yml"


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


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

    def test_a_missing_token_stops_before_any_github_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "gh-was-called"
            gh = Path(tmp) / "gh"
            gh.write_text(f"#!/usr/bin/env bash\ntouch {marker}\nexit 0\n")
            gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
            env = {k: v for k, v in os.environ.items()
                   if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
            env["PATH"] = f"{tmp}:{env['PATH']}"
            result = run("--ref", "v1.15.0", env=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("GH_TOKEN", result.stderr)
            self.assertFalse(marker.exists(),
                             "the token guard must run before any gh call")


if __name__ == "__main__":
    unittest.main()
