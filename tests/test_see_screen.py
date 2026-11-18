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

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

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
        with mock.patch.dict(os.environ, {"GH_TOKEN": "", "GITHUB_TOKEN": ""}), \
                mock.patch.object(s, "Path") as home:
            home.home.return_value = Path("/nonexistent-home-for-this-test")
            with mock.patch.object(s.shutil, "which", return_value=None):
                with self.assertRaises(SystemExit) as caught:
                    s.resolve_token(None)
                self.assertIn("gh auth login", str(caught.exception))

    def test_the_bootstrap_save_is_the_last_resort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            secrets = Path(tmp) / "agent-bootstrap" / "secrets"
            secrets.mkdir(parents=True)
            (secrets / "gh_token.txt").write_text("from-bootstrap\n")
            with mock.patch.dict(os.environ, {"GH_TOKEN": "", "GITHUB_TOKEN": ""}), \
                    mock.patch.object(s, "Path") as home:
                home.home.return_value = Path(tmp)
                with mock.patch.object(s.shutil, "which", return_value=None):
                    self.assertEqual(s.resolve_token(None), "from-bootstrap")

    def test_an_empty_bootstrap_save_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            secrets = Path(tmp) / "agent-bootstrap" / "secrets"
            secrets.mkdir(parents=True)
            (secrets / "gh_token.txt").write_text("   \n")
            with mock.patch.dict(os.environ, {"GH_TOKEN": "", "GITHUB_TOKEN": ""}), \
                    mock.patch.object(s, "Path") as home:
                home.home.return_value = Path(tmp)
                with mock.patch.object(s.shutil, "which", return_value=None):
                    with self.assertRaises(SystemExit):
                        s.resolve_token(None)


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


class EpochTests(unittest.TestCase):
    def test_epoch_is_utc_across_a_dst_change(self) -> None:
        old = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "America/New_York"
            time.tzset()
            if time.timezone != 18000:  # EST is five hours west of UTC
                self.skipTest("America/New_York tzdata is unavailable")
            # Three hours in UTC; the old local-time math said two.
            self.assertEqual(
                s._epoch("2026-03-08T04:00:00Z") - s._epoch("2026-03-08T01:00:00Z"),
                3 * 3600.0)
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_epoch_handles_missing_and_malformed_timestamps(self) -> None:
        self.assertEqual(s._epoch(None), 0.0)
        self.assertEqual(s._epoch(""), 0.0)
        self.assertEqual(s._epoch("not-a-time"), 0.0)


class WorkflowTests(unittest.TestCase):
    def test_the_default_workflow_is_ui_screenshots(self) -> None:
        self.assertEqual(s.WORKFLOW_FILE, "ui-screenshots.yml")

    def test_find_run_queries_the_workflow_scoped_endpoint(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake_api(method, path, token, payload=None, raw=False, timeout=60):
            calls.append((method, path))
            return {"workflow_runs": [{
                "id": 9, "event": "workflow_dispatch",
                "display_title": "see note",
                "created_at": "2026-01-01T00:00:00Z"}]}

        with mock.patch.object(s, "api", side_effect=fake_api), \
                mock.patch.object(s.time, "sleep", return_value=None):
            run = s.find_run("o/r", "see note", time.time() - 60, "t",
                             workflow="my-flow.yml")
        self.assertEqual(run["id"], 9)
        self.assertIn("/actions/workflows/my-flow.yml/runs", calls[0][1])
        self.assertIn("event=workflow_dispatch", calls[0][1])

    def test_dry_run_reports_the_requested_workflow(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = s.main(["--dry-run", "--repo", "o/r",
                          "--workflow", "custom.yml"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["workflow"], "custom.yml")


class JsonModeTests(unittest.TestCase):
    def capture_run(self, *argv: str):
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "shot.png"
            png.write_bytes(b"\x89PNG")
            run = {"id": 1, "html_url": "https://github.com/o/r/actions/runs/1",
                   "conclusion": "success", "status": "completed"}
            with mock.patch.object(s, "resolve_token", return_value="t"), \
                    mock.patch.object(s, "default_branch", return_value="main"), \
                    mock.patch.object(s, "dispatch", return_value=None), \
                    mock.patch.object(s, "find_run", return_value=run), \
                    mock.patch.object(s, "wait_for_run", return_value=run), \
                    mock.patch.object(s, "fetch_artifact", return_value=[png]), \
                    mock.patch.object(s, "screen_dirs", return_value=Path(tmp)), \
                    contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                code = s.main(["--repo", "o/r", "--route", "/settings", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_json_keeps_stdout_parseable(self) -> None:
        code, out, err = self.capture_run("--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["routes"], ["/settings"])
        self.assertIn("asked", err)

    def test_progress_goes_to_stdout_without_json(self) -> None:
        code, out, err = self.capture_run()
        self.assertEqual(code, 0)
        self.assertIn("image(s)", out)
        self.assertEqual(err, "")


class ArtifactTests(unittest.TestCase):
    @staticmethod
    def zip_bytes(path: Path, entries: list[tuple[str, bytes, int | None]]) -> bytes:
        with zipfile.ZipFile(path, "w") as zf:
            for name, data, mode in entries:
                if mode is None:
                    zf.writestr(name, data)
                else:
                    info = zipfile.ZipInfo(name)
                    info.external_attr = mode << 16
                    zf.writestr(info, data)
        return path.read_bytes()

    def fetch(self, tmp: str, blob: bytes) -> list[Path]:
        out = Path(tmp) / "out"
        out.mkdir()
        artifacts = {"artifacts": [
            {"id": 1, "name": "ui-screenshots", "expired": False}]}

        def fake_api(method, path, token, payload=None, raw=False, timeout=60):
            if path.endswith("/artifacts"):
                return artifacts
            return blob

        with mock.patch.object(s, "api", side_effect=fake_api):
            return s.fetch_artifact("o/r", {"id": 9, "html_url": "u"}, out, "t")

    def test_expired_is_skipped_and_the_named_artifact_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            zip_a = self.zip_bytes(Path(tmp) / "a.zip", [("a.png", b"a", None)])
            zip_b = self.zip_bytes(Path(tmp) / "b.zip", [("b.png", b"b", None)])
            artifacts = {"artifacts": [
                {"id": 1, "name": "other", "expired": False},
                {"id": 2, "name": "ui-screenshots", "expired": False},
                {"id": 3, "name": "expired-one", "expired": True},
            ]}

            def fake_api(method, path, token, payload=None, raw=False, timeout=60):
                if path.endswith("/artifacts"):
                    return artifacts
                if path.endswith("/artifacts/1/zip"):
                    return zip_a
                if path.endswith("/artifacts/2/zip"):
                    return zip_b
                raise AssertionError(path)

            with mock.patch.object(s, "api", side_effect=fake_api):
                images = s.fetch_artifact("o/r", {"id": 9, "html_url": "u"},
                                          out, "t")
            self.assertEqual([p.name for p in images], ["b.png"])
            self.assertFalse((out / "a.png").exists())

    def test_directory_and_symlink_members_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blob = self.zip_bytes(Path(tmp) / "z.zip", [
                ("dir/", b"", None),
                ("real.png", b"r", None),
                ("link.png", b"real.png", 0o120777),
            ])
            images = self.fetch(tmp, blob)
            self.assertEqual([p.name for p in images], ["real.png"])
            self.assertFalse((Path(tmp) / "out" / "link.png").exists())
            self.assertFalse((Path(tmp) / "out" / "dir").exists())

    def test_a_zip_path_escape_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blob = self.zip_bytes(Path(tmp) / "z.zip", [
                ("../escaped.png", b"x", None),
                ("ok.png", b"y", None),
            ])
            images = self.fetch(tmp, blob)
            self.assertEqual([p.name for p in images], ["ok.png"])
            self.assertFalse((Path(tmp) / "escaped.png").exists())


class ApiHeadersTests(unittest.TestCase):
    def test_get_has_no_content_type_but_post_does(self) -> None:
        class FakeResponse:
            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class FakeOpener:
            def __init__(self):
                self.requests: list[urllib.request.Request] = []

            def open(self, req, timeout=60):
                self.requests.append(req)
                return FakeResponse()

        opener = FakeOpener()
        with mock.patch.object(s, "_opener", return_value=opener):
            s.api("GET", "/x", "t")
            s.api("POST", "/y", "t", {"a": 1})
        self.assertNotIn("Content-type", opener.requests[0].headers)
        self.assertEqual(opener.requests[1].headers.get("Content-type"),
                         "application/json")

    def test_cross_host_redirect_clears_both_header_maps(self) -> None:
        handler = s._StripAuthOnHostChange()
        req = urllib.request.Request("https://api.github.com/a")
        req.add_header("Authorization", "Bearer sekrit")
        redirected = handler.redirect_request(
            req, None, 302, "Found", {},
            "https://objects.githubusercontent.com/signed/thing")
        self.assertIsNotNone(redirected)
        self.assertNotIn("Authorization", redirected.headers)
        self.assertNotIn("Authorization", redirected.unredirected_hdrs)


if __name__ == "__main__":
    unittest.main()
