"""Guards for the web preview cleanup workflow.

The cleanup job has to find the directory that the preview deploy published to.
The two live in different workflow files, so the only thing stopping them from
silently drifting apart is the check below. No network, Flutter SDK or
third-party modules required.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
DEPLOY = WORKFLOWS / "web-preview.yml"
CLEANUP = WORKFLOWS / "preview-cleanup.yml"
EXAMPLE = ROOT / "examples" / "project-workflows" / "web-preview.yml"
INSTALLER = ROOT / "scripts" / "install.sh"

SED_EXPRESSION = re.compile(r"sed -E '([^']+)'")
USES_REFERENCE = re.compile(
    r"flutter-builder/\.github/workflows/([\w-]+\.yml)@(\S+)"
)
DEFAULT_REF = re.compile(r"^DEFAULT_REF=(\S+)$", re.MULTILINE)

# Branch name -> directory slug, exactly as web-preview.yml publishes them.
SLUG_CASES = {
    "main": "main",
    "fix/tool-correctness": "fix-tool-correctness",
    "Feature/New_Thing": "feature-new-thing",
    "release/1.8": "release-1-8",
    "--weird--/Ref--": "weird---ref",
    "user/ünicode": "user-nicode",
}

# Events / inputs the cleanup job must refuse to act on.
SKIP_CASES = (
    "the deleted ref was a $ref_type, not a branch",
    "no branch name in this event",
    "is the pages branch itself",
    "is listed in keep-branches",
)


def sed_expressions(path: Path) -> list[str]:
    return SED_EXPRESSION.findall(path.read_text(encoding="utf-8"))


def slug(expression: str, branch: str) -> str:
    """Run the workflow's own shell pipeline for one branch name."""
    script = (
        f"printf '%s' {shlex.quote(branch)}"
        f" | tr '[:upper:]' '[:lower:]'"
        f" | sed -E {shlex.quote(expression)}"
    )
    result = subprocess.run(
        ["bash", "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


class PreviewCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        for path in (DEPLOY, CLEANUP, EXAMPLE, INSTALLER):
            self.assertTrue(path.is_file(), f"missing {path}")
        self.cleanup = CLEANUP.read_text(encoding="utf-8")

    def test_cleanup_and_deploy_sanitise_branch_names_identically(self) -> None:
        deploy_expressions = sed_expressions(DEPLOY)
        cleanup_expressions = sed_expressions(CLEANUP)
        self.assertEqual(
            len(deploy_expressions),
            1,
            f"expected one sed expression in {DEPLOY.name}",
        )
        self.assertEqual(
            len(cleanup_expressions),
            1,
            f"expected one sed expression in {CLEANUP.name}",
        )
        self.assertEqual(
            deploy_expressions[0],
            cleanup_expressions[0],
            "preview deploy and preview cleanup sanitise branch names "
            "differently, so cleanup would look in the wrong directory",
        )

    def test_branch_names_slugify_to_the_published_directory(self) -> None:
        expression = sed_expressions(DEPLOY)[0]
        for branch, expected in SLUG_CASES.items():
            with self.subTest(branch=branch):
                self.assertEqual(slug(expression, branch), expected)

    def test_cleanup_never_removes_the_whole_pages_tree(self) -> None:
        self.assertIn("Refusing to remove", self.cleanup)
        guard = re.search(r"case \"\$directory\" in\n(.*?)\n\s*esac", self.cleanup, re.S)
        self.assertIsNotNone(guard, "the pages-root guard is missing")
        assert guard is not None
        # "." and ".." alone, an absolute path, and anything walking upwards.
        for pattern in ('"."', '".."', '"/"', '|/*|', '|../*|', '|*/../*'):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, guard.group(1))

    def test_cleanup_skips_the_paths_it_must_not_touch(self) -> None:
        for expected in SKIP_CASES:
            with self.subTest(reason=expected):
                self.assertIn(expected, self.cleanup)
        self.assertIn('default: "main,master"', self.cleanup)

    def test_cleanup_supports_dry_run_and_pages_branch_options(self) -> None:
        self.assertIn("dry-run", self.cleanup)
        self.assertIn("DRY_RUN: ${{ inputs.dry-run }}", self.cleanup)
        self.assertIn("pages-branch", self.cleanup)
        self.assertIn('default: gh-pages', self.cleanup)

    def test_example_caller_wires_the_cleanup_job(self) -> None:
        text = EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("  delete:", text)
        self.assertIn("github.event.ref_type == 'branch'", text)
        self.assertIn("if: github.event_name != 'delete'", text)
        self.assertIn("preview-cleanup.yml@", text)

    def test_every_reference_in_the_example_uses_one_pin(self) -> None:
        references = USES_REFERENCE.findall(EXAMPLE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(references), 2)
        refs = {ref for _, ref in references}
        self.assertEqual(
            len(refs),
            1,
            f"the example mixes reusable workflow pins: {sorted(refs)}",
        )

    def test_push_is_retried_when_a_preview_deploy_writes_at_the_same_time(self) -> None:
        """Merging a PR and deleting its branch fire a deploy and a cleanup together.

        The deploy publishes at the very end of its run, so a rejected push here
        must be replayed on top of the pages branch instead of failing the run.
        """
        text = CLEANUP.read_text(encoding="utf-8")
        self.assertIn("for attempt in 1 2 3 4 5; do", text)
        self.assertIn('git fetch --quiet origin "${PAGES_BRANCH}"', text)
        self.assertIn('git rebase --quiet "origin/${PAGES_BRANCH}"', text)
        self.assertIn("git rebase --abort", text)
        self.assertIn("::error::Could not push the removal", text)
        # A retry loop is pointless if the push still runs outside of it.
        self.assertEqual(text.count("git push --quiet"), 1)

    def test_every_preview_writer_shares_one_concurrency_lane(self) -> None:
        """One gh-pages branch means one writer at a time.

        Updating a branch that has an open pull request fires a push run and a
        pull_request run at once; both deploy the same folder and the deploy
        action pushes with a compare-and-swap, so the second push is rejected
        ("cannot lock ref"). Cancelling instead of queueing is no better: it
        dropped the deploy of the default branch when a branch was deleted.
        """
        for path in (EXAMPLE, INSTALLER):
            text = path.read_text(encoding="utf-8")
            self.assertIn("group: web-preview\n", text, path)
            self.assertIn("cancel-in-progress: false", text, path)
            self.assertNotIn("group: web-preview-${{", text, path)

    def test_installer_ships_the_cleanup_job_and_the_same_pin(self) -> None:
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("preview-cleanup.yml@%s", installer)
        self.assertIn("  delete:", installer)
        self.assertIn("github.event.ref_type == 'branch'", installer)
        self.assertIn("if: github.event_name != 'delete'", installer)

        default_ref = DEFAULT_REF.search(installer)
        self.assertIsNotNone(default_ref, "DEFAULT_REF is missing from the installer")
        assert default_ref is not None
        refs = {ref for _, ref in USES_REFERENCE.findall(EXAMPLE.read_text(encoding="utf-8"))}
        self.assertEqual(
            refs,
            {default_ref.group(1)},
            "the installer default ref and the documented example pin disagree",
        )


if __name__ == "__main__":
    unittest.main()
