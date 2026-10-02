"""The preview hub: one index page that makes every preview findable.

The problem it solves is not technical. Branch previews existed and worked, but
the URL was printed into an Actions run summary - so the person who needs it
could not find it, and asked whether the previews were even there. The hub is a
single bookmarkable page (…/<repo>/preview/) listing every branch.

These checks hold the safety properties that make it acceptable to run against
somebody's gh-pages branch:

  * it writes exactly one file, <preview-dir>/index.html - a repository whose
    gh-pages root serves its own website must not lose it;
  * links are relative, so the page works under any Pages path;
  * a lost race (two deploys at once) is retried, not fatal;
  * the workflow marks the step continue-on-error: a missing index must never
    fail a deploy that already published a preview;
  * a custom destination-dir means a custom layout, where a hub is meaningless -
    the step must be skipped there;
  * the builder checkout that provides the script is pinned to a tag that
    actually contains it.

Text-level assertions; no network, no Flutter SDK.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / "scripts" / "preview-hub.sh"
PREVIEW = ROOT / ".github" / "workflows" / "web-preview.yml"
INSTALLER = ROOT / "scripts" / "install-agent-pack.sh"


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.lstrip("v").split("."))


class HubScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = HUB.read_text(encoding="utf-8")

    def test_it_writes_exactly_one_file(self) -> None:
        """Everything else on gh-pages belongs to somebody else."""
        # Exactly one write in the whole script - that is the safety property.
        self.assertEqual(self.text.count('call("PUT"'), 1,
                         "the hub must issue exactly one write")
        self.assertIn('call("GET"', self.text)
        # ...and that single PUT is the index inside the preview directory.
        put_target = re.search(r"(?s)path = f\"/contents/\{(?P<target>.+?)\}\"", self.text)
        self.assertIsNotNone(put_target, "no write path found")
        self.assertIn("index.html", put_target.group("target"))
        self.assertIn("preview_dir", put_target.group("target"))
        # No root-level write: index.html must never land outside preview_dir.
        self.assertNotRegex(self.text, r'path = f"/contents/index\.html"')
        self.assertIn("left alone", self.text)          # documented contract

    def test_links_are_relative(self) -> None:
        self.assertIn('href="./{urllib.parse.quote(b)}/"', self.text)

    def test_branch_names_are_escaped_and_quoted(self) -> None:
        self.assertIn("html.escape", self.text)
        self.assertIn("urllib.parse.quote", self.text)

    def test_a_lost_race_is_retried(self) -> None:
        self.assertIn("for attempt in range(1, 6)", self.text)
        self.assertIn('payload["sha"] = sha', self.text)
        self.assertIn("HTTP {status}", self.text)

    def test_it_reports_the_hub_url(self) -> None:
        self.assertIn("GITHUB_STEP_SUMMARY", self.text)
        self.assertRegex(self.text, r"hub at \{hub_url\}")

    def test_it_says_where_the_token_comes_from(self) -> None:
        self.assertIn(': "${GITHUB_TOKEN:?', self.text)
        self.assertIn("contents: write", self.text)

    def test_valid_bash(self) -> None:
        result = subprocess.run(["bash", "-n", str(HUB)], capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


class WorkflowWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = PREVIEW.read_text(encoding="utf-8")

    def _hub_step(self) -> str:
        match = re.search(r"(?m)^      - name: Refresh the preview hub index\n"
                          r"(?P<body>(?:        .*\n|\n)+)", self.text)
        self.assertIsNotNone(match, "the hub step is missing from web-preview.yml")
        return match.group("body")

    def test_the_step_runs_after_the_deploy(self) -> None:
        deploy = self.text.index("peaceiris/actions-gh-pages@v4")
        hub = self.text.index("Refresh the preview hub index")
        self.assertLess(deploy, hub, "the hub must index a deploy that already happened")

    def test_a_missing_index_never_fails_the_deploy(self) -> None:
        self.assertIn("continue-on-error: true", self._hub_step())

    def test_it_is_skipped_for_a_custom_destination_directory(self) -> None:
        body = self._hub_step()
        checkout = re.search(r"(?m)^      - name: Check out this builder "
                             r"\(for the preview hub script\)\n"
                             r"(?P<body>(?:        .*\n|\n)+)", self.text).group("body")
        guard = 'if: inputs.destination-dir == \'\''
        self.assertIn(guard, body)
        self.assertIn(guard, checkout,
                      "a custom layout has no preview/ directory to index")

    def test_it_calls_the_script_with_the_deployed_directory(self) -> None:
        body = self._hub_step()
        self.assertIn("preview-hub.sh", body)
        self.assertIn("--branch-dir", body)
        self.assertIn("steps.paths.outputs.dest-dir", body)

    def test_the_builder_pin_contains_the_script(self) -> None:
        checkout = re.search(r"(?m)^      - name: Check out this builder "
                             r"\(for the preview hub script\)\n"
                             r"(?P<body>(?:        .*\n|\n)+)", self.text).group("body")
        pinned = re.search(r"^          ref: (v[\d.]+)$", checkout, re.M)
        self.assertIsNotNone(pinned, "the hub checkout has no tag pin")
        packed = re.search(r"^PACK_VERSION=(v[\d.]+)$",
                           INSTALLER.read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(packed)
        self.assertGreaterEqual(version_tuple(pinned.group(1)),
                                version_tuple(packed.group(1)),
                                "the hub script is not in that tag yet")

    def test_the_summary_points_at_the_hub(self) -> None:
        self.assertIn("All previews:", self.text)


if __name__ == "__main__":
    unittest.main()
