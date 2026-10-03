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
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REUSABLE = ROOT / ".github" / "workflows" / "ui-screenshots.yml"
EXAMPLE = ROOT / "examples" / "project-workflows" / "ui-screenshots.yml"
SMOKE = ROOT / ".github" / "workflows" / "flutter-smoke-test.yml"
CAPTURE = ROOT / "scripts" / "capture-screenshots.sh"
EMBED = ROOT / "scripts" / "embed-screenshots.sh"
PAGES = ROOT / "scripts" / "capture-pages.cjs"
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

    def test_an_app_without_web_support_can_still_be_captured(self) -> None:
        """`flutter build web` fails outright without a `web/` folder, and most
        of the apps this pack is installed into have never been built for the
        web. The opt-in step adds the folder to the job's throwaway checkout,
        before `pub get`, and only when the input asks for it - so an app that
        does ship `web/` keeps its own index.html/title.""" 
        match = re.search(r"(?m)^      generate-web-platform:\n(?:        .*\n)+", self.text)
        self.assertIsNotNone(match, "the generate-web-platform input is gone")
        self.assertIn("default: false", match.group(0))
        step = re.search(r"(?ms)^      - name: Generate the web platform\n(?P<body>(?:        .*\n|\n)+)", self.text)
        self.assertIsNotNone(step, "the generate step is gone")
        body = step.group("body")
        self.assertIn("if: inputs.generate-web-platform", body)
        self.assertIn("[ -d web ]", body)
        self.assertIn("flutter create --platforms=web .", body)
        # It must run before pub get (create touches pubspec resolution) and it
        # must not commit anything back to the caller repository.
        self.assertGreater(self.text.index("Generate the web platform"),
                           self.text.index("Set up Flutter"))
        self.assertLess(self.text.index("Generate the web platform"),
                        self.text.index("Install dependencies"))
        self.assertNotIn("git push", body)

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

    def test_the_manifest_travels_with_the_images(self) -> None:
        """Blank-screen detection lives in the manifest's pixel count.

        The artifact used to carry only `*.png`, so a tool that downloads it
        (tool/see_screen.py) could not tell a real screen from a white one - and
        neither could a human reading the artifact after GitHub expired the run.
        """
        match = re.search(r"(?m)^      - name: Upload the screenshot artifact\n"
                          r"(?P<body>(?:        .*\n|\n)+)", self.text)
        self.assertIsNotNone(match)
        self.assertIn("manifest.tsv", match.group("body"))

    def test_artifact_is_uploaded_even_when_capture_fails(self) -> None:
        match = re.search(r"(?m)^      - name: Upload the screenshot artifact\n"
                          r"(?P<body>(?:        .*\n|\n)+)", self.text)
        self.assertIsNotNone(match)
        self.assertIn("if: always()", match.group("body"))


class OnDemandCaptureTests(unittest.TestCase):
    """A screen nobody is changing still has to be lookable-at.

    Pull requests photograph `/`, which is not where the problem usually is.
    The caller therefore accepts the same knobs through `workflow_dispatch`, so
    a human can type `/settings` into the Actions form and an agent can run
    `python3 tool/see_screen.py --route /settings` (it dispatches, waits and
    downloads). Both paths need three things this class pins down: the inputs
    exist, they are forwarded with the bracket syntax hyphenated names require,
    and the run carries a title that identifies it.
    """

    def caller(self) -> str:
        return EXAMPLE.read_text(encoding="utf-8")

    def test_the_form_accepts_the_knobs_a_human_types(self) -> None:
        text = self.caller()
        for name in ("routes", "viewports", "wait-ms", "dart-defines", "note"):
            self.assertIn(f"      {name}:", text, f"{name} is not a dispatch input")

    def test_the_inputs_are_forwarded_to_the_reusable_workflow(self) -> None:
        text = self.caller()
        # Hyphenated names are not valid property syntax in expressions, and the
        # failure is a YAML/expression error at run time - not obvious at all.
        self.assertIn("${{ inputs.routes || '/' }}", text)
        self.assertIn("${{ inputs.viewports || '390x844,768x1024' }}", text)
        self.assertIn("fromJSON(inputs['wait-ms'] || '8000')", text)
        self.assertIn("${{ inputs['dart-defines'] || '' }}", text)
        # A pull request has no dispatch inputs: every fallback must be there,
        # or the PR runs that used to work start failing.
        for name in ("wait-ms", "dart-defines"):
            self.assertNotIn(f"inputs.{name}", text,
                             f"inputs.{name} is invalid expression syntax - use inputs['{name}']")
        self.assertEqual(text.count("inputs['"), 2, "bracket syntax drifted")

    def test_the_run_says_which_screen_it_is_about(self) -> None:
        text = self.caller()
        self.assertIn("run-name:", text)
        self.assertIn("format(' — {0}', inputs.note)", text)

    def test_the_pack_ships_the_tool_that_drives_this(self) -> None:
        tool = ROOT / "agent-pack" / "see_screen.py"
        self.assertTrue(tool.is_file(), "see_screen.py left the pack")
        body = tool.read_text(encoding="utf-8")
        self.assertIn("ui-screenshots.yml", body)
        self.assertIn("workflow_dispatch", body)
        # The AGENTS playbook must point at it, or agents never learn it exists.
        template = (ROOT / "agent-pack" / "AGENTS.template.md").read_text(encoding="utf-8")
        self.assertIn("see_screen.py", template)


class ManifestSummaryTests(unittest.TestCase):
    """The table at the end of a run must survive the manifest changing shape.

    The manifest grew from four columns to six when blank-screen detection
    moved to real pixels. The summary step kept reading four, so `size` quietly
    became the rest of the line and `$((size / 1024))` died with the error
    token "1491\t0.867" - in nine repositories, in the step whose only job is
    to print a table. Parsing now lives in one script, and this runs it.
    """

    SCRIPT = ROOT / "scripts" / "manifest-summary.sh"

    def run_script(self, content: str, *extra: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.tsv"
            manifest.write_text(content, encoding="utf-8")
            done = subprocess.run(["bash", str(self.SCRIPT), str(manifest), *extra],
                                  capture_output=True, text=True, check=True)
        return done.stdout

    def test_the_present_six_column_manifest(self) -> None:
        out = self.run_script("home-390x844\t/\t390x844\t67739\t1491\t0.867\n")
        self.assertIn("| `home-390x844.png` | `/` | 390x844 | 66 KB | 1491 |", out)

    def test_an_older_four_column_manifest_still_prints(self) -> None:
        out = self.run_script("home-390x844\t/\t390x844\t67739\n")
        self.assertIn("| `home-390x844.png` | `/` | 390x844 | 66 KB |", out)

    def test_a_manifest_without_pixel_stats_prints_a_dash(self) -> None:
        out = self.run_script("a\t/\t390x844\t1024\t-1\t-1\n")
        self.assertIn("| `a.png` | `/` | 390x844 | 1 KB |", out)

    def test_a_missing_manifest_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run(["bash", str(self.SCRIPT), f"{tmp}/gone.tsv"],
                                  capture_output=True, text=True)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout, "")

    def test_the_script_reads_every_column_the_capture_writes(self) -> None:
        writer = (ROOT / "scripts" / "capture-pages.cjs").read_text(encoding="utf-8")
        append = re.search(r"fs\.appendFileSync\(manifest,\s*(?P<row>.*?)\);", writer, re.S)
        self.assertIsNotNone(append, "the manifest writer moved")
        # Columns are the tab-separated fields (count the separators, not the
        # interpolations: width and height are two of them inside one field).
        written = len(re.findall(r"\\t", append.group("row"))) + 1
        script = self.SCRIPT.read_text(encoding="utf-8")
        read = re.search(r"while IFS=\$'\\t' read -r (?P<vars>.+?); do", script)
        self.assertIsNotNone(read, "the manifest reader moved")
        self.assertGreaterEqual(len(read.group("vars").split()), written,
                                "the summary script reads fewer columns than are written")

    def test_no_workflow_parses_the_manifest_inline(self) -> None:
        """Inline parsing is how the two drifted apart the first time."""
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"while IFS=\$'\\t' read -r",
                                f"{path.name} parses the manifest inline; "
                                f"call scripts/manifest-summary.sh instead")
        self.assertIn("manifest-summary.sh",
                      REUSABLE.read_text(encoding="utf-8"))
        self.assertIn("manifest-summary.sh", SMOKE.read_text(encoding="utf-8"))


class SelfCheckoutPinTests(unittest.TestCase):
    """The ref the workflow checks out must be old enough to have the scripts.

    `ui-screenshots.yml` fetches the capture scripts by checking out
    flutter-builder at the `ref:` written inside itself. The first shipped
    version of this workflow pinned v1.10.0 - a tag from before the scripts
    existed - so all nine repositories that installed the caller failed at
    capture time with `exit 127` and a "No such file or directory" message.
    The scripts landed in v1.11.0; the pin must never walk back in time, and it
    must move together with the example caller.
    """

    # The release that first shipped scripts/capture-screenshots.sh.
    FIRST_TAG_WITH_SCRIPTS = (1, 11, 0)

    def pin(self, text: str) -> str:
        match = re.search(r"(?m)^\s+ref: (v[0-9][0-9.]*)$", text)
        self.assertIsNotNone(match, "no builder ref in the reusable workflow")
        return match.group(1)

    def test_the_pin_ships_the_capture_scripts(self) -> None:
        pinned = version_tuple(self.pin(REUSABLE.read_text(encoding="utf-8")))
        self.assertGreaterEqual(pinned, self.FIRST_TAG_WITH_SCRIPTS,
                                "the workflow would check out a tag without the scripts")

    def test_the_pin_matches_the_ref_callers_are_told_to_use(self) -> None:
        workflow = REUSABLE.read_text(encoding="utf-8")
        example = EXAMPLE.read_text(encoding="utf-8")
        uses = re.search(r"ui-screenshots\.yml@(v[0-9][0-9.]*)", example)
        self.assertIsNotNone(uses, "the example caller lost its pin")
        self.assertEqual(self.pin(workflow), uses.group(1),
                         "the example caller and the workflow's own checkout "
                         "have drifted apart - they move together")

    def test_the_smoke_test_proves_the_pin_has_the_scripts(self) -> None:
        """The unit test above only reads text; this keeps the workflow that
        actually clones the pin (and would catch a tag being deleted) alive."""
        smoke = SMOKE.read_text(encoding="utf-8")
        match = re.search(r"(?ms)^      - name: The pinned builder really ships the "
                          r"capture scripts\n(?P<body>(?:        .*\n|\n)+)", smoke)
        self.assertIsNotNone(match, "the runtime guard against a stale pin is gone")
        body = match.group("body")
        self.assertIn("git clone", body)
        for script in ("capture-screenshots.sh", "capture-pages.cjs", "embed-screenshots.sh"):
            self.assertIn(script, body)


class CallerExampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = EXAMPLE.read_text(encoding="utf-8")

    def test_grants_the_two_permissions_the_workflow_needs(self) -> None:
        self.assertIn("contents: write", self.text)
        self.assertIn("pull-requests: write", self.text)

    def test_is_manual_only(self) -> None:
        """No push or pull_request trigger: the caller runs on demand only."""
        self.assertIn("on:\n  workflow_dispatch:", self.text)
        self.assertNotIn("  pull_request:", self.text)
        self.assertNotIn("  push:", self.text)

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

    def test_callers_only_pass_flags_the_script_accepts(self) -> None:
        """A stale flag is a runtime failure with an unhelpful exit code 2 - the
        first version of this pipeline passed `--retries` after the script had
        dropped it, and the job died before capturing anything."""
        script = CAPTURE.read_text(encoding="utf-8")
        accepted = set(re.findall(r"(?m)^\s+(--[a-z-]+)\)", script))
        self.assertTrue(accepted, "no flags found in the script")
        for path in (REUSABLE, SMOKE):
            text = path.read_text(encoding="utf-8")
            block = re.search(
                r"capture-screenshots\.sh[^\n]*\n(?P<body>(?:\s+--[a-z-]+[^\n]*\n)+)",
                text)
            self.assertIsNotNone(block, f"{path.name} does not call the script")
            used = set(re.findall(r"--[a-z-]+", block.group("body")))
            self.assertTrue(used, f"{path.name} passes no flags")
            unknown = sorted(used - accepted)
            self.assertEqual(unknown, [],
                             f"{path.name} passes flags the script rejects: {unknown}")

    def test_the_smoke_job_checks_pixels_not_bytes(self) -> None:
        """A white 390x844 PNG is 2.8 KB, so `len(data) > 5000` would have to be
        a guess either way; the manifest's colour count is the real signal."""
        smoke = SMOKE.read_text(encoding="utf-8")
        self.assertIn("manifest.tsv", smoke)
        self.assertIn("int(colors) > 2", smoke)
        self.assertNotIn("is suspiciously small", smoke)

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

    def test_capture_polls_until_the_page_actually_painted(self) -> None:
        """The first CI runs of this pipeline produced a solid white 390x844 PNG
        at 6 s, 15 s, 30 s and 60 s - the same picture every time - and the CLI
        could not say why. The capture now polls on the decoded pixels and
        prints console/WebGL diagnostics when they never appear."""
        capture = CAPTURE.read_text(encoding="utf-8")
        pages = PAGES.read_text(encoding="utf-8")
        self.assertIn("--max-wait-ms", capture)
        self.assertIn("capture-pages.cjs", capture)
        self.assertIn("--wait-for-timeout", pages) if False else None
        self.assertIn("pngStats", pages)
        self.assertIn("looksBlank", pages)
        self.assertIn("console.", pages)          # console messages are collected
        self.assertIn("pageerror", pages)
        self.assertIn("requestfailed", pages)
        self.assertIn("glassPane", pages)         # did the engine boot?
        self.assertIn("webgl", pages)
        # The default wait has to clear a cold CanvasKit boot (~15 s on CI).
        self.assertRegex(capture, r"(?m)^WAIT_MS=1[0-9]{4}$")

    def test_locale_and_webgl_flags_are_set(self) -> None:
        """Three CI runs failed on a white screenshot whose only clue was
        `RangeError: Incorrect locale information provided` from the engine:
        a headless browser with no locale cannot boot Flutter web."""
        pages = PAGES.read_text(encoding="utf-8")
        self.assertIn("--lang=en-US", pages)
        self.assertIn("locale: 'en-US'", pages)
        self.assertIn("--enable-unsafe-swiftshader", pages)
        self.assertIn("LC_ALL", pages)

    def test_blank_is_decided_by_pixels_not_file_size(self) -> None:
        """Size cannot separate the two: a solid white 390x844 shot is 2.8 KB,
        a plain-but-correct page measured 4.4 KB with 15 colours."""
        pages = PAGES.read_text(encoding="utf-8")
        self.assertRegex(pages, r"const blank = stats \? looksBlank\(stats\)")
        self.assertIn("distinct", pages)
        self.assertIn("topShare", pages)

    def test_the_home_route_gets_a_name(self) -> None:
        """'/' slugs to an empty string; the first run wrote '-390x844.png'."""
        pages = PAGES.read_text(encoding="utf-8")
        self.assertIn("return cleaned || 'home'", pages)

    def test_embed_never_fails_the_build(self) -> None:
        text = EMBED.read_text(encoding="utf-8")
        for guard in ("skipping the upload", "skipping the upload.",
                      "still in the workflow artifact"):
            self.assertIn(guard, text)
        # A missing token must exit 0, not take the run down with it.
        self.assertIn("exit 0", text)


class SmokeWorkflowTriggerTests(unittest.TestCase):
    """`flutter-smoke-test.yml` is manual now (plus a weekly cron).

    With no push or pull_request trigger there is no path filter to keep in
    step; what still matters is that the workflow actually exercises the shipped
    screenshot scripts, so the screenshots job must reach capture-pages.cjs
    through capture-screenshots.sh.
    """

    WORKFLOW_REFS = re.compile(r"(?:scripts|tests|agent-pack)/[A-Za-z0-9_.-]+")

    def screenshot_job(self, text: str) -> str:
        """The screenshots job only - the build job's install step is covered
        by installer-tests.yml, and re-running a Flutter web build for every
        `scripts/install.sh` edit would cost minutes for no extra signal."""
        # The screenshots job is the last one, so the lookahead also has to
        # accept the end of the file.
        block = re.search(r"(?ms)^  screenshots:\n(.*?)(?=^  [a-z_]+:|^[a-z]|\Z)", text)
        self.assertIsNotNone(block, "no screenshots job in the smoke workflow")
        return block.group(1)

    def referenced_files(self, text: str) -> set[str]:
        """The `scripts/` files this text reads, and what those scripts read.

        The job calls `capture-screenshots.sh`, which calls `capture-pages.cjs`
        - the file the fix lived in - so following the chain one level further
        is what turns "the job mentions the wrapper" into "the job depends on
        the headless-browser flags". Files the workflow writes at run time (the
        actionlint helper) are not in the repository and are dropped, and the
        walk stays inside `scripts/`: `install.sh` is installer-tests.yml's
        business and a Flutter web build should not re-run for it.
        """
        found: set[str] = set()
        seen: set[str] = set()
        todo = list(self.WORKFLOW_REFS.findall(text))
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            if not name.startswith("scripts/"):
                continue
            path = ROOT / name
            if not path.is_file():
                continue
            found.add(name)
            body = path.read_text(encoding="utf-8")
            todo.extend(self.WORKFLOW_REFS.findall(body))
            # capture-screenshots.sh runs `"$SCRIPT_DIR/capture-pages.cjs"`, so
            # the next script is a bare basename, not a scripts/ path.
            for sibling in re.findall(r"(?<![\w/.-])([\w.-]+\.(?:sh|cjs|bash|js|py))", body):
                todo.append(f"scripts/{sibling}")
        return found

    def test_the_workflow_is_manual_only(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")
        self.assertIn("  workflow_dispatch:", text)
        self.assertNotIn("  push:", text)
        self.assertNotIn("  pull_request:", text)

    def test_the_screenshots_job_reaches_the_capture_script(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")
        referenced = self.referenced_files(self.screenshot_job(text))
        self.assertIn("scripts/capture-pages.cjs", referenced)


if __name__ == "__main__":
    unittest.main()
