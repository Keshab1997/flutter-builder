"""Tests for the About -> Website link job in the reusable web preview workflow.

The decision step is extracted from the workflow and executed against stub `gh`
and `curl` binaries, so the rules below are checked without a network, a token or
a real repository: correctness here means "never throw away a real website" and
"never publish a dead link".
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "web-preview.yml"
INSTALLER = ROOT / "scripts" / "install.sh"
EXAMPLE = ROOT / "examples" / "project-workflows" / "web-preview.yml"
README = ROOT / "README.md"

STEP_NAME = "Point the About link at the preview"
TARGET = "https://example.github.io/app/preview/main/"

GH_STUB = """#!/usr/bin/env bash
# Minimal `gh api` stand-in: keeps the homepage in a state file.
echo "gh $*" >> "${STUB_LOG:?}"
state="${STUB_STATE:?}"
method=GET
homepage=""
shift || true
while [ "$#" -gt 0 ]; do
  case "$1" in
    --method) method="$2"; shift 2 ;;
    -X) method="$2"; shift 2 ;;
    -f|--raw-field|--field)
      case "$2" in
        homepage=*) homepage="${2#homepage=}" ;;
      esac
      shift 2 ;;
    --jq) shift 2 ;;
    *) shift ;;
  esac
done
if [ "$method" = "PATCH" ]; then
  [ "${STUB_IGNORE_PATCH:-}" = "1" ] && exit 0
  printf '%s' "$homepage" > "$state"
  exit 0
fi
cat "$state" 2>/dev/null || true
"""

CURL_STUB = """#!/usr/bin/env bash
# Prints the status code the script under test asks for with -w '%{http_code}'.
printf '%s' "${STUB_HTTP_CODE:-200}"
"""


def extract_step_script(step_name: str) -> str:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.strip() == f"- name: {step_name}"
    )
    run = next(
        i for i, line in enumerate(lines) if i > start and line.strip() == "run: |"
    )
    body: list[str] = []
    for line in lines[run + 1:]:
        if line.strip() and not line.startswith("          "):
            break
        body.append(line[10:] if line.strip() else "")
    return "\n".join(body) + "\n"


class AboutLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.util = self.dir / "bin"
        self.util.mkdir()
        for name, body in (("gh", GH_STUB), ("curl", CURL_STUB)):
            path = self.util / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        self.script = self.dir / "step.sh"
        self.script.write_text("#!/usr/bin/env bash\n" + extract_step_script(STEP_NAME))

    def run_step(
        self,
        current: str = "",
        target: str = TARGET,
        overwrite: str = "false",
        http_code: str = "200",
        ignore_patch: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], list[str], str]:
        state = self.dir / "homepage"
        state.write_text(current, encoding="utf-8")
        log = self.dir / "calls.log"
        log.write_text("", encoding="utf-8")
        output = self.dir / "output"
        output.write_text("", encoding="utf-8")
        summary = self.dir / "summary.md"
        summary.write_text("", encoding="utf-8")
        env = {
            "PATH": f"{self.util}:{os.environ['PATH']}",
            "REPOSITORY": "owner/app",
            "TARGET_URL": target,
            "OVERWRITE": overwrite,
            "GH_TOKEN": "stub",
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
            "STUB_STATE": str(state),
            "STUB_LOG": str(log),
            "STUB_HTTP_CODE": http_code,
            # keep the retry loop from actually waiting
            "ABOUT_LINK_ATTEMPTS": "2",
            "ABOUT_LINK_RETRY_SECONDS": "0",
        }
        if ignore_patch:
            env["STUB_IGNORE_PATCH"] = "1"
        proc = subprocess.run(
            ["bash", str(self.script)], env=env, capture_output=True, text=True
        )
        return proc, log.read_text(encoding="utf-8").splitlines(), state.read_text()

    def patched(self, calls: list[str]) -> list[str]:
        return [call for call in calls if "PATCH" in call]

    # ------------------------------------------------------------------ rules
    def test_empty_website_gets_the_preview_link(self) -> None:
        proc, calls, state = self.run_step(current="")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.patched(calls)), 1, calls)
        self.assertEqual(state, TARGET)
        self.assertIn("Updated from `empty`", (self.dir / "summary.md").read_text())

    def test_the_same_link_is_a_no_op(self) -> None:
        proc, calls, state = self.run_step(current=TARGET)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.patched(calls), [], calls)
        self.assertEqual(state, TARGET)
        self.assertIn("Already points at", (self.dir / "summary.md").read_text())

    def test_a_real_website_is_never_replaced_without_the_flag(self) -> None:
        proc, calls, state = self.run_step(current="https://keshab.dev")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.patched(calls), [], calls)
        self.assertEqual(state, "https://keshab.dev")
        self.assertIn("::warning::", proc.stdout)
        self.assertIn("Left `https://keshab.dev` alone", (self.dir / "summary.md").read_text())

    def test_overwrite_flag_replaces_it(self) -> None:
        proc, calls, state = self.run_step(current="https://keshab.dev", overwrite="true")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.patched(calls)), 1, calls)
        self.assertEqual(state, TARGET)

    def test_a_dead_preview_is_never_linked(self) -> None:
        proc, calls, state = self.run_step(current="", http_code="503")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.patched(calls), [], calls)
        self.assertEqual(state, "")
        self.assertIn("::warning::", proc.stdout)
        self.assertIn("is not live yet", (self.dir / "summary.md").read_text())

    def test_without_a_target_url_nothing_happens(self) -> None:
        proc, calls, state = self.run_step(current="", target="")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.patched(calls), [], calls)
        self.assertEqual(state, "")

    def test_a_patch_that_does_not_stick_fails_loudly(self) -> None:
        proc, calls, _ = self.run_step(current="", ignore_patch=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("::error::", proc.stdout)

    # ----------------------------------------------------------- wiring
    def test_job_is_opt_in_and_only_runs_for_the_default_branch(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("      set-about-link:\n", text)
        self.assertIn("        default: false\n", text)
        gate = re.search(
            r"inputs\.set-about-link &&\s*\n\s*github\.event_name == 'push' &&\s*\n"
            r"\s*github\.ref == format\('refs/heads/\{0\}', github\.event\.repository\.default_branch\)",
            text,
        )
        self.assertIsNotNone(gate, "the job must be gated on a default-branch push")
        self.assertIn("needs: preview", text)
        self.assertIn("needs.preview.outputs.preview-url", text)

    def test_the_admin_credential_is_never_github_token(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        # GITHUB_TOKEN has no administration permission: repository settings can
        # only be edited with an app installation token or a PAT.
        self.assertIn("actions/create-github-app-token@v2", text)
        self.assertIn("APP_PRIVATE_KEY", text)
        self.assertIn("ABOUT_LINK_TOKEN", text)
        self.assertIn(
            "GH_TOKEN: ${{ steps.credentials.outputs.source == 'app' && "
            "steps.app-token.outputs.token || secrets.ABOUT_LINK_TOKEN }}",
            text,
        )

    def test_installer_and_example_ask_for_it_with_the_same_pin(self) -> None:
        installer = INSTALLER.read_text(encoding="utf-8")
        example = EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("set-about-link: true", installer)
        self.assertIn("app-id: ${{ vars.APP_ID }}", installer)
        self.assertIn("set-about-link: true", example)
        self.assertIn("app-id: ${{ vars.APP_ID }}", example)
        pins = set(re.findall(r"web-preview\.yml@(v\S+)", installer + example))
        self.assertEqual(len(pins), 1, pins)

    def test_readme_documents_both_credentials(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("About → Website", text)
        self.assertIn("ABOUT_LINK_TOKEN", text)
        self.assertIn("APP_PRIVATE_KEY", text)
        self.assertIn("about-link-overwrite", text)


if __name__ == "__main__":
    unittest.main()
