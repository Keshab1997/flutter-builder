"""Shape and shell-syntax checks for the reusable widget-test diagnostics lane."""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "flutter-widget-tests.yml"
EXAMPLE = ROOT / "examples" / "project-workflows" / "widget-tests.yml"
README = ROOT / "README.md"


def run_block(text: str, step_name: str) -> str:
    start = text.index(f"      - name: {step_name}")
    marker = "        run: |\n"
    body_start = text.index(marker, start) + len(marker)
    next_step = text.find("\n      - name:", body_start)
    body = text[body_start:next_step if next_step >= 0 else len(text)]
    return "\n".join(
        line[10:] if line.startswith("          ") else ""
        for line in body.splitlines()
    ) + "\n"


class ReusableWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_is_reusable_and_read_only(self) -> None:
        header = self.text.split("jobs:", 1)[0]
        self.assertRegex(header, r"(?m)^  workflow_call:")
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertNotIn("pull_request:", header)
        self.assertNotIn("push:", header)

    def test_runs_flutter_tests_in_debug_without_an_emulator(self) -> None:
        self.assertIn("flutter test \"${args[@]}\" \"$TEST_TARGET\"", self.text)
        self.assertIn("args=(--no-pub --reporter expanded)", self.text)
        self.assertNotIn("flutter build apk", self.text)
        self.assertNotIn("adb ", self.text)
        self.assertIn("flutter test runs in debug mode", self.text)

    def test_captures_exit_status_and_full_test_output(self) -> None:
        self.assertIn("| tee \"$log\"", self.text)
        self.assertIn('status="${PIPESTATUS[0]}"', self.text)
        self.assertIn("echo \"exit_code=$status\" >> \"$GITHUB_OUTPUT\"", self.text)
        self.assertIn("name: flutter-widget-test-log", self.text)
        artifact = re.search(
            r"(?ms)^      - name: Upload full test log\n(?P<body>(?:        .*\n|\n)+)",
            self.text,
        )
        self.assertIsNotNone(artifact)
        self.assertIn("if: always()", artifact.group("body"))
        self.assertIn("retention-days: ${{ inputs.artifact-retention-days }}", artifact.group("body"))

    def test_summary_calls_out_common_layout_errors(self) -> None:
        for signature in (
            "RenderFlex overflowed",
            "EXCEPTION CAUGHT BY RENDERING LIBRARY",
            "Unhandled exception",
        ):
            self.assertIn(signature, self.text)
        summary = re.search(
            r"(?ms)^      - name: Summarize diagnostics\n(?P<body>(?:        .*\n|\n)+)",
            self.text,
        )
        self.assertIsNotNone(summary)
        self.assertIn("if: always()", summary.group("body"))
        self.assertIn("$GITHUB_STEP_SUMMARY", summary.group("body"))

    def test_all_inline_bash_blocks_parse(self) -> None:
        for step in (
            "Verify the Flutter project and test target",
            "Run code generation",
            "Run widget and unit tests",
            "Summarize diagnostics",
        ):
            with self.subTest(step=step):
                script = run_block(self.text, step)
                result = subprocess.run(
                    ["bash", "-n"], input=script, text=True, capture_output=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)


class ExampleWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = EXAMPLE.read_text(encoding="utf-8")

    def test_is_manual_and_calls_the_local_runner(self) -> None:
        header = self.text.split("jobs:", 1)[0]
        self.assertRegex(header, r"(?m)^  workflow_dispatch:")
        self.assertNotIn("pull_request:", header)
        self.assertNotIn("push:", header)
        self.assertIn(
            "uses: Keshab1997/flutter-builder/.github/workflows/flutter-widget-tests.yml@v1.15.0",
            self.text,
        )

    def test_forwards_debug_run_inputs(self) -> None:
        for expression in (
            "inputs['working-directory']",
            "inputs['flutter-channel']",
            "inputs['test-target']",
            "inputs.codegen",
            "inputs['test-concurrency']",
        ):
            self.assertIn(expression, self.text)
        self.assertIn("Copy this file into the app repository's .github/workflows/ directory.", self.text)

    def test_readme_explains_screen_specific_tests(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("Flutter widget-test diagnostics", text)
        self.assertIn("phone-sized viewport", text)


if __name__ == "__main__":
    unittest.main()
