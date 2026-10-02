"""One push must not validate the same commit twice.

A feature branch with an open pull request used to start the caller's CI twice
(the `push` and `pull_request` events build different concurrency groups) and
the web-preview lane - which is serialised on purpose - queued a second deploy
behind the first. These checks pin the behaviour that stops that:

  * the caller's push trigger is main-only, so a PR branch runs one event;
  * drafts are skipped entirely (the reusable workflow's `skip-draft-prs`);
  * prose-only changes (`**.md`, `docs/**`, `distribution/**`) start nothing;
  * the installer, the examples and the reusable workflow agree on all three.

No Flutter SDK, no network, no third-party modules.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".github" / "workflows" / "flutter-build.yml"
INSTALLER = ROOT / "scripts" / "install.sh"
EXAMPLE_CI = ROOT / "examples" / "project-workflows" / "ci.yml"
EXAMPLE_PREVIEW = ROOT / "examples" / "project-workflows" / "web-preview.yml"

GUARD = ("github.event_name != 'pull_request' || "
         "github.event.pull_request.draft == false")


class ReusableWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = BUILD.read_text(encoding="utf-8")

    def test_skip_draft_prs_input_exists_and_defaults_to_true(self) -> None:
        match = re.search(
            r"      skip-draft-prs:\n(?:.*\n)*?        default: (\w+)\n",
            self.text)
        self.assertIsNotNone(match, "skip-draft-prs input is missing")
        self.assertEqual(match.group(1), "true")

    def test_every_job_honours_the_guard(self) -> None:
        for job in ("validate-and-build", "prepare-matrix", "matrix-validate"):
            head = re.search(rf"^  {job}:\n(?P<body>(?:    .*\n|\n)*)",
                             self.text, re.M).group("body")
            self.assertIn(GUARD, head, f"{job} does not skip draft PRs")
            self.assertIn("inputs.skip-draft-prs == false", head,
                          f"{job} ignores an explicit skip-draft-prs: false")

    def test_matrix_jobs_keep_their_own_condition(self) -> None:
        for job in ("prepare-matrix", "matrix-validate"):
            head = re.search(rf"^  {job}:\n(?P<body>(?:    .*\n|\n)*)",
                             self.text, re.M).group("body")
            self.assertIn("inputs.test-matrix != ''", head)


class GeneratedCallerTests(unittest.TestCase):
    """The installer's payload and the examples must stay in step."""

    def setUp(self) -> None:
        self.installer = INSTALLER.read_text(encoding="utf-8")

    def assert_main_only_push(self, text: str, where: str) -> None:
        self.assertIn("  push:\n    branches: [main]\n", text,
                      f"{where}: push is not restricted to main")
        self.assertIn("  pull_request:", text,
                      f"{where}: pull_request trigger disappeared")

    def test_installer_generated_callers_are_main_only(self) -> None:
        self.assert_main_only_push(self.installer, "install.sh")

    def test_examples_are_main_only(self) -> None:
        self.assert_main_only_push(EXAMPLE_CI.read_text(encoding="utf-8"), "example ci.yml")
        self.assert_main_only_push(EXAMPLE_PREVIEW.read_text(encoding="utf-8"),
                                   "example web-preview.yml")

    def test_every_caller_ignores_prose_only_changes(self) -> None:
        for path in (INSTALLER, EXAMPLE_CI, EXAMPLE_PREVIEW):
            text = path.read_text(encoding="utf-8")
            self.assertIn("paths-ignore:", text, str(path))
            for pattern in ('"**.md"', '"docs/**"', '"distribution/**"'):
                self.assertIn(pattern, text, f"{path} misses {pattern}")

    def test_the_ci_caller_skips_drafts(self) -> None:
        self.assertIn(GUARD, EXAMPLE_CI.read_text(encoding="utf-8"))
        self.assertIn(GUARD, self.installer)

    def test_the_preview_caller_keeps_the_delete_cleanup(self) -> None:
        text = EXAMPLE_PREVIEW.read_text(encoding="utf-8")
        self.assertIn("  delete:", text)
        self.assertIn("github.event.ref_type == 'branch'", text)


if __name__ == "__main__":
    unittest.main()
