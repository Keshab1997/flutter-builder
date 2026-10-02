"""The UI screenshot pipeline: one capture script, three callers, one pin.

Pictures of the changed screens are the only way a human (or an agent that
cannot run the app) sees what a UI change did. The pipeline is only as good as
its wiring, so these checks hold the parts together:

  * the reusable workflow exposes the knobs it documents (routes, viewports,
    wait-ms, embed-in-pr) and calls both scripts;
  * the example caller, the reusable workflow and the smoke test all run the
    *same* `scripts/capture-screenshots.sh` - a second copy of the capture
    logic is how the two drift apart;
  * playwright is pinned; a silent upgrade would move every published image;
  * the `ui-screenshots.yml` workflow is newer than the rest of the pack, so
    its builder pin must never fall behind the released version (an older tag
    simply does not contain the file or the scripts);
  * the scripts are valid bash, and the comment step stays best-effort.

Text-level assertions, no Flutter SDK, no browser, no network.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REUSABLE = ROOT / ".github" / "workflows" / "ui-screenshots.yml"
EXAMPLE = ROOT / "examples" / "project-workflows" / "ui-screenshots.yml"
SMOKE = ROOT / ".github" / "workflows" / "flutter-smoke-test.yml"
CAPTURE = ROOT / "scripts" / "capture-screenshots.sh"
EMBED = ROOT / "scripts" / "embed-screenshots.sh"
INSTALLER = ROOT / "scripts" / "install-agent-pack.sh"


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.lstrip("v").split("."))


class WorkflowShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = REUSABLE.read_text(encoding="utf-8")

    def test_documents_every_knob_it_needs(self) -> None:
        for name, default in (("routes", "/"), ("viewports", "390x844"),
                              ("wait-ms", "8000"), ("embed-in-pr", "true"),
                              ("screenshots-branch", "ui-screenshots")):
            match = re.search(rf"(?m)^      {re.escape(name)}:\n(?:        .*\n)+", self.text)
            self.assertIsNotNone(match, f"input missing: {name}")
            # Quoting a YAML default is a style choice; the value is not.
            self.assertRegex(match.group(0), rf'(?m)^        default: "?{re.escape(default)}"?$',
                             f"{name} lost its previous-behaviour default")

    def test_calls_the_shipped_scripts(self) -> None:
        self.assertIn("scripts/capture-screenshots.sh", self.text)
        self.assertIn("scripts/embed-screenshots.sh", self.text)
        # The script is fetched from a tag, not re-implemented in YAML.
        self.assertIn("repository: Keshab1997/flutter-builder", self.text)
        self.assertIn("path: .flutter-builder", self.text)

    def test_drafts_and_forks_are_handled(self) -> None:
        self.assertIn("github.event.pull_request.draft == false", self.text)
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            self.text)
        self.assertIn("continue-on-error: true", self.text)

    def test_artifact_is_uploaded_even_when_capture_fails(self) -> None:
        match = re.search(r"(?m)^      - name: Upload the screenshot artifact\n"
                          r"(?P<body>(?:        .*\n|\n)+)", self.text)
        self.assertIsNotNone(match)
        self.assertIn("if: always()", match.group("body"))


class CallerExampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = EXAMPLE.read_text(encoding="utf-8")

    def test_grants_the_two_permissions_the_workflow_needs(self) -> None:
        self.assertIn("contents: write", self.text)
        self.assertIn("pull-requests: write", self.text)

    def test_skips_draft_pull_requests(self) -> None:
        self.assertIn("github.event.pull_request.draft == false", self.text)

    def test_pins_a_release_that_contains_the_workflow(self) -> None:
        match = re.search(r"ui-screenshots\.yml@(v[\d.]+)", self.text)
        self.assertIsNotNone(match, "the caller does not pin a tag")
        # Must be >= the pack version: older tags predate this workflow and the
        # scripts it calls, so the caller would fail at runtime.
        packed = re.search(r"^PACK_VERSION=(v[\d.]+)$",
                           INSTALLER.read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(packed)
        self.assertGreaterEqual(version_tuple(match.group(1)),
                                version_tuple(packed.group(1)))


class OneCaptureScriptTests(unittest.TestCase):
    """Both the workflow and the smoke test run the same script."""

    def test_both_callers_use_the_script_with_the_same_flags(self) -> None:
        workflow = REUSABLE.read_text(encoding="utf-8")
        smoke = SMOKE.read_text(encoding="utf-8")
        for text, where in ((workflow, "ui-screenshots.yml"), (smoke, "smoke test")):
            self.assertIn("capture-screenshots.sh", text, where)
            for flag in ("--build-dir", "--out", "--routes", "--viewports", "--wait-ms"):
                self.assertIn(flag, text, f"{where} does not pass {flag}")

    def test_nobody_reimplements_playwright_in_yaml(self) -> None:
        for path in (REUSABLE, SMOKE):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("playwright screenshot", text,
                             f"{path.name} duplicates the capture logic")
            self.assertNotIn("http-server", text,
                             f"{path.name} serves the build itself instead of "
                             f"calling the script")

    def test_playwright_is_pinned_in_one_place(self) -> None:
        text = CAPTURE.read_text(encoding="utf-8")
        match = re.search(r'PLAYWRIGHT_VERSION="\$\{PLAYWRIGHT_VERSION:-([\d.]+)\}"', text)
        self.assertIsNotNone(match, "the playwright version is not pinned")
        self.assertRegex(match.group(1), r"^\d+\.\d+\.\d+$")
        self.assertNotIn("@latest", text)
        self.assertNotIn("playwright@latest", CAPTURE.read_text(encoding="utf-8"))

    def test_scripts_are_valid_bash(self) -> None:
        for script in (CAPTURE, EMBED):
            result = subprocess.run(["bash", "-n", str(script)],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_capture_reports_a_blank_screen_instead_of_hiding_it(self) -> None:
        text = CAPTURE.read_text(encoding="utf-8")
        self.assertIn("possibly a blank screen", text)
        self.assertIn("--wait-for-timeout", text)

    def test_embed_never_fails_the_build(self) -> None:
        text = EMBED.read_text(encoding="utf-8")
        for guard in ("skipping the upload", "skipping the upload.",
                      "still in the workflow artifact"):
            self.assertIn(guard, text)
        # A missing token must exit 0, not take the run down with it.
        self.assertIn("exit 0", text)


if __name__ == "__main__":
    unittest.main()
