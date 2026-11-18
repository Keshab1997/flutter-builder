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

import json
import os
import re
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

    def test_deploy_replaces_only_the_current_preview_directory(self) -> None:
        """Clear old assets for this branch without wiping other Pages paths."""
        self.assertIn("destination_dir: ${{ steps.paths.outputs.dest-dir }}", self.text)
        self.assertIn("keep_files: false", self.text)
        self.assertNotIn("keep_files: true", self.text)

    def test_web_build_reuses_the_dependency_resolve(self) -> None:
        self.assertIn("cache: true", self.text)
        self.assertIn("run: flutter pub get", self.text)
        self.assertIn("flutter build web --release --no-pub", self.text)

    def test_branch_push_updates_the_open_pr_preview_comment(self) -> None:
        self.assertIn("github.event_name == 'push'", self.text)
        self.assertIn("github.rest.pulls.list", self.text)
        self.assertIn('head: `${context.repo.owner}:${process.env.BRANCH_NAME}`',
                      self.text)


class HubStub:
    """A loopback stand-in for the two Contents endpoints the hub uses.

    The script's network seam is GITHUB_API_URL (default
    https://api.github.com), so pointing it at 127.0.0.1 exercises the real
    code path: listing the preview directory, reading the index sha, PUT-ing
    the index - including the 409 retry.
    """

    def __init__(self) -> None:
        self.directories: dict[str, set[str]] = {}
        self.files: dict[str, tuple[str, str, str]] = {}  # path -> (sha, b64, message)
        self.put_count = 0
        self.put_failures_left = 0
        self.queries_seen: list[str] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:  # keep the log quiet
                pass

            def _send(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _contents_path(self) -> str:
                path, _, query = self.path.partition("?")
                stub.queries_seen.append(query)
                parts = path.split("/")
                assert len(parts) >= 6 and parts[1] == "repos", self.path
                return "/".join(parts[5:])

            def do_GET(self) -> None:
                contents_path = self._contents_path()
                if contents_path in stub.directories:
                    body = json.dumps([
                        {"name": n, "type": "dir"}
                        for n in sorted(stub.directories[contents_path])
                    ]).encode()
                    self._send(200, body)
                elif contents_path in stub.files:
                    sha, b64, message = stub.files[contents_path]
                    self._send(200, json.dumps(
                        {"sha": sha, "content": b64, "message": message}).encode())
                else:
                    self._send(404, b'{"message": "Not Found"}')

            def do_PUT(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode() or "{}")
                contents_path = self._contents_path()
                if stub.put_failures_left > 0:
                    stub.put_failures_left -= 1
                    self._send(409, b'{"message": "sha mismatch (stale write)"}')
                    return
                stub.put_count += 1
                sha = f"stub-sha-{stub.put_count:04d}"
                stub.files[contents_path] = (
                    sha, payload.get("content", ""), payload.get("message", ""))
                self._send(201, json.dumps({"content": {"sha": sha}}).encode())

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def seed(self, preview_dir: str, *names: str) -> None:
        self.directories[preview_dir] = set(names)

    def index(self, preview_dir: str) -> tuple[str, str, str] | None:
        return self.files.get(f"{preview_dir}/index.html")

    def index_page(self, preview_dir: str) -> str:
        import base64
        stored = self.files.get(f"{preview_dir}/index.html")
        assert stored is not None, "the hub never wrote the index"
        return base64.b64decode(stored[1]).decode()


class HubBehaviourTests(unittest.TestCase):
    """Behavioural checks against the loopback Contents API stub."""

    HUB = ROOT / "scripts" / "preview-hub.sh"

    def setUp(self) -> None:
        self.stub = HubStub()
        self.stub.start()
        self.addCleanup(self.stub.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.summary_file = str(Path(self.temp.name) / "summary.md")

    def run_hub(self, *args: str, pages_branch: str = "gh-pages") -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.update({
            "GITHUB_TOKEN": "test-token",
            "GITHUB_REPOSITORY": "acme/demo",
            "PAGES_BRANCH": pages_branch,
            "GITHUB_API_URL": self.stub.base_url,
            "GITHUB_STEP_SUMMARY": self.summary_file,
        })
        return subprocess.run(
            ["bash", str(self.HUB), *args],
            capture_output=True, text=True, check=False, env=env, timeout=120)

    def test_deploy_indexes_the_listing_and_inserts_the_deployed_label(self) -> None:
        """The API may lag a deploy by a beat: the label is inserted first."""
        self.stub.seed("preview", "feature-x")
        result = self.run_hub("--branch-dir", "preview/new-branch")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.stub.put_count, 1)
        page = self.stub.index_page("preview")
        self.assertIn('<a href="./new-branch/">new-branch</a>', page)
        self.assertIn('<a href="./feature-x/">feature-x</a>', page)
        # The deployed branch is listed first, before the sorted API listing.
        list_block = page.split("<ul", 1)[1].split("</ul>", 1)[0]
        self.assertLess(list_block.index("new-branch"), list_block.index("feature-x"))
        self.assertIn("Latest: <strong>new-branch</strong>", page)
        _, _, message = self.stub.files["preview/index.html"]
        self.assertIn("new-branch", message)
        # The hub URL still lands in the step summary.
        self.assertIn("All previews of this repository:",
                      Path(self.summary_file).read_text(encoding="utf-8"))

    def test_remove_drops_a_stale_deleted_slug_and_inserts_no_label(self) -> None:
        self.stub.seed("preview", "main", "gone")
        result = self.run_hub("--preview-dir", "preview", "--remove", "gone")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.stub.put_count, 1)
        page = self.stub.index_page("preview")
        self.assertIn('<a href="./main/">main</a>', page)
        self.assertNotIn("gone", page)
        self.assertNotIn("Latest:", page)
        self.assertIn("1 branch preview(s): main", result.stdout)
        _, _, message = self.stub.files["preview/index.html"]
        self.assertIn("removed gone", message)

    def test_refresh_with_zero_previews_writes_an_empty_state(self) -> None:
        self.stub.seed("preview")  # empty listing
        result = self.run_hub("--preview-dir", "preview", "--refresh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.stub.put_count, 1,
                         "an empty listing must still write the page")
        page = self.stub.index_page("preview")
        self.assertIn("No active branch previews.", page)
        self.assertNotIn("Latest:", page)
        self.assertNotIn('<a href="./', page)
        self.assertIn("0 branch preview(s)", result.stdout)

    def test_http_409_on_put_is_retried(self) -> None:
        self.stub.seed("preview", "main")
        self.stub.put_failures_left = 1
        result = self.run_hub("--branch-dir", "preview/main")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("attempt 1 got HTTP 409", result.stdout)
        self.assertEqual(self.stub.put_count, 1)
        self.assertIn('<a href="./main/">main</a>', self.stub.index_page("preview"))

    def test_html_and_url_special_characters_are_escaped(self) -> None:
        self.stub.seed("preview", "a<b>&c")
        result = self.run_hub("--preview-dir", "preview", "--refresh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        page = self.stub.index_page("preview")
        self.assertIn('href="./a%3Cb%3E%26c/"', page)
        self.assertIn("a&lt;b&gt;&amp;c", page)
        # The Pages branch is a query value, so it must be percent-encoded.
        self.assertEqual(
            self.run_hub("--preview-dir", "preview", "--refresh",
                         pages_branch="pages/1.0").returncode, 0)
        self.assertTrue(
            any("ref=pages%2F1.0" in query for query in self.stub.queries_seen),
            f"pages_branch was not URL-encoded in ?ref= (seen: {self.stub.queries_seen})")

    def test_empty_dot_or_dotdot_segments_are_rejected(self) -> None:
        for args in (
            ("--preview-dir", ".."),
            ("--preview-dir", "."),
            ("--preview-dir", "a/../b"),
            ("--preview-dir", "a/./b"),
            ("--preview-dir", "a//b"),
            ("--branch-dir", "../x"),
        ):
            with self.subTest(args=args):
                result = self.run_hub(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("must not contain", result.stderr)
        self.assertEqual(self.stub.put_count, 0, "a rejected run must not write")


if __name__ == "__main__":
    unittest.main()
