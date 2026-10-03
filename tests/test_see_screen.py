"""Tests for agent-pack/see_screen.py - the agent's way to look at a screen.

The script talks to the GitHub API, so the network parts are kept in thin
functions and everything with a decision in it is tested directly: which
repository the remote points at, what a route turns into, which run belongs to
this request, how the artifact's manifest is read, and where the images land.
A redirect handler is tested too - artifact downloads leave GitHub for blob
storage, and forwarding the Authorization header there fails with a 401 that
looks like a permissions bug.

Text-level tests plus a `--dry-run` call; no network, no token, no SDK.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "agent-pack"
sys.path.insert(0, str(PACK))

import see_screen as s  # noqa: E402


class RemoteTests(unittest.TestCase):
    def test_reads_the_slug_out_of_every_remote_shape(self) -> None:
        for url in ("https://github.com/Keshab1997/quizbaaz.git",
                    "https://github.com/Keshab1997/quizbaaz",
                    "git@github.com:Keshab1997/quizbaaz.git",
                    "ssh://git@github.com/Keshab1997/quizbaaz.git"):
            self.assertEqual(s.parse_remote(url), "Keshab1997/quizbaaz", url)

    def test_a_remote_that_is_not_github_is_not_a_repository(self) -> None:
        self.assertIsNone(s.parse_remote("https://gitlab.com/o/r.git"))
        self.assertIsNone(s.parse_remote(""))

    def test_repository_comes_from_git_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(["git", "remote", "add", "origin",
                            "https://github.com/Keshab1997/SpeakEasy.git"],
                           cwd=tmp, check=True)
            self.assertEqual(s.repo_slug(Path(tmp)), "Keshab1997/SpeakEasy")

    def test_no_origin_means_no_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            self.assertIsNone(s.repo_slug(Path(tmp)))


class RouteTests(unittest.TestCase):
    def test_routes_become_directories(self) -> None:
        self.assertEqual(s.route_slug("/"), "home")
        self.assertEqual(s.route_slug("/settings"), "settings")
        self.assertEqual(s.route_slug("/settings/edit-profile"), "settings-edit-profile")
        self.assertEqual(s.route_slug(""), "home")

    def test_two_requests_never_write_to_the_same_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = s.screen_dirs(root, ["/settings"], fresh=True)
            first.mkdir(parents=True)
            second = s.screen_dirs(root, ["/settings"], fresh=True)
            self.assertNotEqual(first, second)


class InputTests(unittest.TestCase):
    def args(self, **over):
        base = {"viewports": None, "wait_ms": None, "dart_defines": None}
        base.update(over)
        return type("A", (), base)()

    def test_one_dispatch_carries_every_route(self) -> None:
        inputs = s.build_inputs(["/settings", "/profile"], self.args(), "see 1 /settings /profile")
        self.assertEqual(inputs["routes"], "/settings,/profile")
        self.assertEqual(inputs["viewports"], s.DEFAULT_VIEWPORTS)
        self.assertEqual(inputs["wait-ms"], s.DEFAULT_WAIT_MS)
        self.assertEqual(inputs["note"], "see 1 /settings /profile")
        self.assertNotIn("dart-defines", inputs)

    def test_explicit_knobs_win(self) -> None:
        inputs = s.build_inputs(["/"], self.args(viewports="390x844", wait_ms=12000,
                                                dart_defines="API=1"), "n")
        self.assertEqual(inputs["viewports"], "390x844")
        self.assertEqual(inputs["wait-ms"], "12000")
        self.assertEqual(inputs["dart-defines"], "API=1")

    def test_the_note_is_what_identifies_the_run(self) -> None:
        """Two agents (or a human clicking Run workflow) must not collide."""
        note = "see 1730000000-4242 /settings"
        runs = [
            {"id": 1, "event": "workflow_dispatch", "display_title": "Flutter UI screenshots",
             "created_at": "2026-10-03T06:00:00Z"},
            {"id": 2, "event": "workflow_dispatch",
             "display_title": f"Flutter UI screenshots - {note}",
             "created_at": "2026-10-03T05:59:00Z"},
        ]
        picked = s.pick_run(runs, note, time.time() - 60)
        self.assertEqual(picked["id"], 2)

    def test_without_a_note_the_newest_dispatch_after_us_wins(self) -> None:
        now = time.time()
        runs = [
            {"id": 1, "event": "pull_request", "display_title": "x",
             "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 30))},
            {"id": 2, "event": "workflow_dispatch", "display_title": "run",
             "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 5))},
        ]
        self.assertEqual(s.pick_run(runs, "", now - 10)["id"], 2)

    def test_a_run_from_before_we_asked_is_not_ours(self) -> None:
        now = time.time()
        runs = [{"id": 7, "event": "workflow_dispatch", "display_title": "old",
                 "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 12 * 3600))}]
        self.assertIsNone(s.pick_run(runs, "", now))


class ManifestTests(unittest.TestCase):
    def write(self, body: str) -> Path:
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "manifest.tsv"
        path.write_text(body, encoding="utf-8")
        self.addCleanup(shutil.rmtree, tmp, True)
        return path

    def test_the_six_column_manifest_gives_colours(self) -> None:
        rows = s.summarise_manifest(self.write("home-390x844\t/\t390x844\t67739\t1491\t0.867\n"))
        self.assertEqual(rows[0]["colours"], 1491)
        self.assertEqual(rows[0]["bytes"], 67739)

    def test_an_older_manifest_leaves_colours_unknown(self) -> None:
        rows = s.summarise_manifest(self.write("home-390x844\t/\t390x844\t4496\n"))
        self.assertIsNone(rows[0]["colours"])

    def test_a_missing_manifest_is_not_a_crash(self) -> None:
        self.assertEqual(s.summarise_manifest(Path("/nonexistent/manifest.tsv")), [])


class DownloadTests(unittest.TestCase):
    def test_authorization_is_dropped_when_the_host_changes(self) -> None:
        """The artifact URL 302s to blob storage; that host rejects our token."""
        handler = s._StripAuthOnHostChange()
        req = urllib.request.Request("https://api.github.com/repos/o/r/actions/artifacts/1/zip",
                                     headers={"Authorization": "Bearer sekrit"})
        redirected = handler.redirect_request(
            req, None, 302, "Found", {},
            "https://objects.githubusercontent.com/signed/thing")
        self.assertIsNotNone(redirected)
        self.assertIsNone(redirected.get_header("Authorization"))

    def test_authorization_survives_a_same_host_redirect(self) -> None:
        handler = s._StripAuthOnHostChange()
        req = urllib.request.Request("https://api.github.com/a", headers={"Authorization": "Bearer sekrit"})
        redirected = handler.redirect_request(req, None, 302, "Found", {}, "https://api.github.com/b")
        self.assertIsNotNone(redirected)
        self.assertIn("sekrit", redirected.get_header("Authorization", ""))


class TokenTests(unittest.TestCase):
    def test_token_file_wins_over_the_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tok"
            path.write_text("from-file\n", encoding="utf-8")
            old = dict(**{k: __import__("os").environ.get(k) for k in ("GH_TOKEN", "GITHUB_TOKEN")})
            __import__("os").environ["GH_TOKEN"] = "from-env"
            try:
                self.assertEqual(s.resolve_token(str(path)), "from-file")
            finally:
                for key, value in old.items():
                    if value is None:
                        __import__("os").environ.pop(key, None)
                    else:
                        __import__("os").environ[key] = value

    def test_the_error_says_how_to_get_a_token(self) -> None:
        import os
        saved = {k: os.environ.pop(k, None) for k in ("GH_TOKEN", "GITHUB_TOKEN")}
        saved_which = shutil.which
        shutil.which = lambda name: None  # no gh in this test
        try:
            with self.assertRaises(SystemExit) as caught:
                s.resolve_token(None)
            self.assertIn("gh auth login", str(caught.exception))
        finally:
            shutil.which = saved_which
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value


class CommandLineTests(unittest.TestCase):
    def test_dry_run_prints_the_dispatch_and_touches_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(["git", "remote", "add", "origin",
                            "https://github.com/Keshab1997/quizbaaz.git"], cwd=tmp, check=True)
            import contextlib
            import io
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = s.main(["--route", "/settings", "--route", "/profile", "--dry-run"],
                              cwd=Path(tmp))
            payload = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["repo"], "Keshab1997/quizbaaz")
        self.assertEqual(payload["inputs"]["routes"], "/settings,/profile")
        self.assertTrue(payload["inputs"]["note"].startswith("see "))

    def test_no_repository_is_a_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            with self.assertRaises(SystemExit) as caught:
                s.main(["--route", "/", "--dry-run"], cwd=Path(tmp))
        self.assertIn("--repo", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
