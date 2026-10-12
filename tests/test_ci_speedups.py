"""CI stays manual; web previews refresh automatically.

The CI caller stays manual-only so small changes can be batched. The web-preview
caller is the exception: it refreshes on relevant branch pushes, keeps a manual
dispatch, and skips documentation/workflow-only changes. These checks pin that
CI remains manual and the installer/example preview callers stay aligned.

The reusable `flutter-build.yml` still carries the `skip-draft-prs` guard, so a
caller that chooses to use pull requests keeps the old behaviour.

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
    """The shared workflow keeps the draft-PR guard for callers that use PRs."""

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
    """CI stays manual while the generated preview caller is automatic."""

    def setUp(self) -> None:
        self.installer = INSTALLER.read_text(encoding="utf-8")

    def ci_block(self, text: str) -> str:
        """The generated ci.yml heredoc inside the installer."""
        match = re.search(
            r"<<'YAML'\n(name: Flutter CI — Format, Analyze & Test\n.*?)\nYAML\n",
            text, re.S)
        self.assertIsNotNone(match, "ci.yml block not found in install.sh")
        return match.group(1)

    def assert_manual_only(self, text: str, where: str) -> None:
        self.assertIn("on:\n  workflow_dispatch:\n", text,
                      f"{where}: expected a manual-only trigger")
        self.assertNotIn("  push:", text, f"{where}: a push trigger is back")
        self.assertNotIn("  pull_request:", text,
                         f"{where}: a pull_request trigger is back")

    def assert_auto_preview(self, text: str, where: str) -> None:
        self.assertIn("on:\n  push:\n", text, f"{where}: push trigger is missing")
        self.assertIn("      - '!gh-pages'\n", text,
                      f"{where}: Pages writes must not trigger another build")
        self.assertIn("    paths-ignore:\n", text,
                      f"{where}: docs/workflow-only changes should be skipped")
        self.assertIn("      - 'distribution/**'\n", text,
                      f"{where}: release-note-only changes should be skipped")
        self.assertIn("  workflow_dispatch:\n  delete:\n", text,
                      f"{where}: manual run and deleted-branch cleanup must remain")
        self.assertNotIn("  pull_request:", text,
                         f"{where}: PR branch pushes already trigger the preview")

    def test_installer_generated_ci_is_manual_only(self) -> None:
        self.assert_manual_only(self.ci_block(self.installer),
                                "install.sh ci.yml")

    def test_example_ci_is_manual_only(self) -> None:
        self.assert_manual_only(EXAMPLE_CI.read_text(encoding="utf-8"),
                                "example ci.yml")

    def test_the_ci_caller_no_longer_needs_the_draft_guard(self) -> None:
        self.assertNotIn(GUARD, self.ci_block(self.installer))
        self.assertNotIn(GUARD, EXAMPLE_CI.read_text(encoding="utf-8"))

    def preview_block(self, text: str) -> str:
        """The generated web-preview.yml heredoc inside the installer."""
        match = re.search(
            r"<<'YAML'\n(name: Deploy Flutter Web Preview \(GitHub Pages\)\n.*?)\nYAML\n",
            text, re.S)
        self.assertIsNotNone(match, "web-preview block not found in install.sh")
        return match.group(1)

    def test_installer_generated_web_preview_is_automatic_for_relevant_pushes(self) -> None:
        self.assert_auto_preview(self.preview_block(self.installer),
                                 "install.sh web-preview.yml")

    def test_the_web_preview_example_keeps_automatic_push_and_cleanup(self) -> None:
        self.assert_auto_preview(EXAMPLE_PREVIEW.read_text(encoding="utf-8"),
                                 "example web-preview.yml")


if __name__ == "__main__":
    unittest.main()
