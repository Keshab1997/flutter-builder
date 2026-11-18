"""Guards for shared .github/workflows/ security and runtime invariants."""
from __future__ import annotations

import importlib.util
import io
import re
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load_see_screen():
    spec = importlib.util.spec_from_file_location(
        "see_screen_wf_test", ROOT / "agent-pack" / "see_screen.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_block_expressions(path: Path) -> list[tuple[int, str]]:
    """Return [(line_no, expr)] for every ${{ ... }} inside a bash `run:` step."""
    hits: list[tuple[int, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    in_run = False
    run_indent = 0
    for lineno, line in enumerate(lines, 1):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        m = re.match(r"^(?:-\s+)?run:\s*(.*)$", stripped)
        if m:
            rest = m.group(1).strip()
            for expr in re.finditer(r"\$\{\{([^}]+)\}\}", rest):
                hits.append((lineno, expr.group(1).strip()))
            if rest in ("|", "|-", "|+", ">", ">-", ">+"):
                in_run = True
                run_indent = indent
            else:
                in_run = False
            continue
        if in_run:
            if stripped and indent <= run_indent:
                in_run = False
                continue
            for expr in re.finditer(r"\$\{\{([^}]+)\}\}", line):
                hits.append((lineno, expr.group(1).strip()))
    return hits


def _boolean_inputs(text: str) -> set[str]:
    """Input names declared with `type: boolean` in a workflow file."""
    names: set[str] = set()
    current: str | None = None
    for line in text.splitlines():
        key = re.match(r"^ {6}([a-zA-Z0-9_-]+):\s*$", line)
        if key:
            current = key.group(1)
            continue
        if current and re.match(r"^ {8}type:\s*boolean\s*$", line):
            names.add(current)
    return names


class WorkflowHardeningTests(unittest.TestCase):
    def test_all_workflows_parse_as_yaml_when_pyyaml_available(self) -> None:
        try:
            import yaml  # type: ignore
        except ImportError:
            self.skipTest("PyYAML not installed")
        for wf in sorted(WORKFLOWS.glob("*.yml")):
            with self.subTest(workflow=wf.name):
                data = yaml.safe_load(wf.read_text(encoding="utf-8"))
                self.assertIsInstance(data, dict)
                self.assertIn("jobs", data)

    def test_no_untrusted_or_string_input_expressions_in_run_blocks(self) -> None:
        """String inputs and branch/event refs must enter shell via `env:`."""
        unsafe_prefixes = (
            "github.event.",
            "github.head_ref",
            "github.base_ref",
            "github.ref_name",
        )
        violations: list[str] = []
        for wf in sorted(WORKFLOWS.glob("*.yml")):
            text = wf.read_text(encoding="utf-8")
            bool_inputs = _boolean_inputs(text)
            for lineno, expr in _run_block_expressions(wf):
                if expr.startswith("inputs."):
                    name = expr.split(".", 1)[1].strip()
                    if name not in bool_inputs:
                        violations.append(f"{wf.name}:{lineno}: ${{{{ {expr} }}}}")
                elif any(p in expr for p in unsafe_prefixes):
                    violations.append(f"{wf.name}:{lineno}: ${{{{ {expr} }}}}")
        self.assertEqual(violations, [], "Move to step env:\n" + "\n".join(violations))

    def test_preview_cleanup_refreshes_hub_with_remove_flag(self) -> None:
        cleanup = (WORKFLOWS / "preview-cleanup.yml").read_text(encoding="utf-8")
        preview = (WORKFLOWS / "web-preview.yml").read_text(encoding="utf-8")
        self.assertIn('echo "slug=$slug"', cleanup)
        self.assertIn("scripts/preview-hub.sh", cleanup)
        self.assertIn('--preview-dir "$PREVIEW_DIR"', cleanup)
        self.assertIn('--remove "$REMOVE_SLUG"', cleanup)
        cleanup_ref = re.search(
            r"repository:\s*Keshab1997/flutter-builder[\s\S]{0,240}?ref:\s*(v[0-9.]+)",
            cleanup,
        )
        preview_ref = re.search(
            r"repository:\s*Keshab1997/flutter-builder[\s\S]{0,240}?ref:\s*(v[0-9.]+)",
            preview,
        )
        self.assertIsNotNone(cleanup_ref)
        self.assertIsNotNone(preview_ref)
        self.assertEqual(cleanup_ref.group(1), preview_ref.group(1))

    def test_aab_gradle_fallback_preserves_obfuscation_and_symbols(self) -> None:
        build = (WORKFLOWS / "flutter-build.yml").read_text(encoding="utf-8")
        self.assertIn("OBFUSCATE: ${{ inputs.obfuscate }}", build)
        self.assertIn('"-Pextra-gen-snapshot-options=--obfuscate"', build)
        self.assertIn('"-Psplit-debug-info=$PWD/build/symbols"', build)
        fallback = re.search(
            r"\./gradlew bundleRelease[\s\S]{0,220}?gradle_extra_args",
            build,
        )
        self.assertIsNotNone(fallback)

    def test_ui_screenshots_wires_url_strategy_through_env(self) -> None:
        wf = (WORKFLOWS / "ui-screenshots.yml").read_text(encoding="utf-8")
        self.assertIn("url-strategy:", wf)
        self.assertIn("URL_STRATEGY: ${{ inputs.url-strategy }}", wf)
        self.assertIn('--url-strategy "$URL_STRATEGY"', wf)
        self.assertIn('--routes "$ROUTES"', wf)
        self.assertIn('--viewports "$VIEWPORTS"', wf)
        self.assertIn('--branch "$SCREENSHOTS_BRANCH"', wf)

    def test_installer_tests_workflow_runs_all_offline_gates(self) -> None:
        wf = (WORKFLOWS / "installer-tests.yml").read_text(encoding="utf-8")
        for expected in (
            "for script in scripts/*.sh",
            "shellcheck -S warning scripts/*.sh",
            "node --check scripts/capture-pages.cjs",
            "python3 scripts/sync-agent-pack.py --check",
            "python3 scripts/prepare-release.py --check",
            "python3 -m unittest discover -s tests -v",
        ):
            self.assertIn(expected, wf)

    def test_bump_consumers_workflow_exposes_with_agent_pack_opt_in(self) -> None:
        wf = (WORKFLOWS / "bump-consumers.yml").read_text(encoding="utf-8")
        self.assertIn("with-agent-pack:", wf)
        self.assertIn("WITH_AGENT_PACK: ${{ inputs.with-agent-pack }}", wf)
        self.assertIn("args+=(--with-agent-pack)", wf)

    def test_see_screen_prefers_numbered_ui_screenshots_artifact(self) -> None:
        see_screen = _load_see_screen()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("home-390x844.png", b"\x89PNG\r\n\x1a\nok")
        blob = buf.getvalue()

        def fake_api(method, path, token, payload=None, raw=False, timeout=60):
            if path.endswith("/artifacts"):
                return {
                    "artifacts": [
                        {"id": 10, "name": "coverage-report", "expired": False},
                        {"id": 20, "name": "ui-screenshots-42", "expired": False},
                    ]
                }
            self.assertEqual(path, "/repos/o/r/actions/artifacts/20/zip")
            return blob

        with TemporaryDirectory() as td, mock.patch.object(see_screen, "api", fake_api):
            images = see_screen.fetch_artifact("o/r", {"id": 9, "html_url": "u"}, Path(td), "t")
            self.assertEqual([p.name for p in images], ["home-390x844.png"])


if __name__ == "__main__":
    unittest.main()
