"""Offline tests for the agent pack's CI watcher (tool/ci_watch.py).

No network, no token, no GitHub: every test patches `api` and the token/repo
resolution. The behaviours checked are the ones that decide an exit code -
timeout vs. still-running, which conclusions count as failures, branch
deduplication, UTC durations, and the log/redirect helpers.
"""

from __future__ import annotations

import contextlib
import gzip
import importlib.util
import io
import os
import sys
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "agent-pack"


class CiWatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location(
            "ci_watch_under_test", str(PACK / "ci_watch.py"))
        cls.ci = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.ci)

    # -- helpers ----------------------------------------------------------
    def run_main(self, *argv: str, runs: list[dict] | None = None,
                 jobs: dict | None = None):
        """Run main() with the network and token fully stubbed out."""
        def fake_api(path: str, token: str, raw: bool = False):
            if "/jobs" in path:
                return jobs if jobs is not None else {"jobs": []}
            return {"workflow_runs": runs or []}

        with mock.patch.object(self.ci, "resolve_token", return_value="t"), \
                mock.patch.object(self.ci, "resolve_repo", return_value="o/r"), \
                mock.patch.object(self.ci, "api", side_effect=fake_api), \
                mock.patch.object(self.ci.time, "sleep", return_value=None), \
                mock.patch.object(sys, "argv", ["ci_watch.py", *argv]), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            code = self.ci.main()
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def make_run(name: str = "build", event: str = "push", status: str = "completed",
            conclusion: str | None = "success", created: str = "2026-01-01T00:00:00Z",
            run_id: int = 1) -> dict:
        return {
            "id": run_id,
            "name": name,
            "event": event,
            "status": status,
            "conclusion": conclusion,
            "created_at": created,
            "run_started_at": created,
            "updated_at": created,
            "html_url": f"https://github.com/o/r/actions/runs/{run_id}",
        }

    # -- polling / timeout -------------------------------------------------
    def test_timeout_with_active_runs_returns_2(self) -> None:
        """Active runs at the deadline are a timeout, not a clean result."""
        active = [self.make_run(status="in_progress", conclusion=None)]
        code, out, err = self.run_main("--sha", "abc", "--timeout", "0",
                                       runs=active)
        self.assertEqual(code, 2, out + err)
        self.assertIn("timed out", err)
        self.assertNotIn("timed out", out)

    def test_once_returns_0_for_active_healthy_runs(self) -> None:
        active = [self.make_run(status="in_progress", conclusion=None)]
        code, out, _ = self.run_main("--sha", "abc", "--once", runs=active)
        self.assertEqual(code, 0, out)
        self.assertIn("still running", out)

    # -- conclusions -------------------------------------------------------
    def test_failure_conclusions_return_1(self) -> None:
        for conclusion in ("failure", "timed_out", "startup_failure",
                           "action_required"):
            with self.subTest(conclusion=conclusion):
                code, out, _ = self.run_main(
                    "--sha", "abc", "--once",
                    runs=[self.make_run(conclusion=conclusion)])
                self.assertEqual(code, 1, out)
                self.assertIn("FAILED", out)

    def test_success_conclusion_returns_0(self) -> None:
        code, out, _ = self.run_main("--sha", "abc", "--once",
                                     runs=[self.make_run(conclusion="success")])
        self.assertEqual(code, 0, out)
        self.assertIn("all green", out)

    def test_neutral_conclusion_is_not_a_failure(self) -> None:
        code, out, _ = self.run_main("--sha", "abc", "--once",
                                     runs=[self.make_run(conclusion="neutral")])
        self.assertEqual(code, 0, out)

    # -- branch deduplication ---------------------------------------------
    def test_branch_keeps_the_newest_run_per_name_and_event(self) -> None:
        """An older failure superseded by a newer green run must not be red."""
        runs = [
            self.make_run(conclusion="success", created="2026-01-01T01:00:00Z",
                     run_id=2),
            self.make_run(conclusion="failure", created="2026-01-01T00:00:00Z",
                     run_id=1),
        ]
        code, out, _ = self.run_main("--branch", "main", "--once", runs=runs)
        self.assertEqual(code, 0, out)
        self.assertIn("success", out)
        self.assertNotIn("FAILED", out)

    def test_branch_newest_failure_stays_red(self) -> None:
        runs = [
            self.make_run(conclusion="failure", created="2026-01-01T01:00:00Z",
                     run_id=2),
            self.make_run(conclusion="success", created="2026-01-01T00:00:00Z",
                     run_id=1),
        ]
        code, out, _ = self.run_main("--branch", "main", "--once", runs=runs)
        self.assertEqual(code, 1, out)
        self.assertIn("FAILED", out)

    def test_branch_distinguishes_events(self) -> None:
        """Same workflow name on a different event is a separate bucket."""
        runs = [
            self.make_run(event="push", conclusion="success",
                     created="2026-01-01T01:00:00Z", run_id=2),
            self.make_run(event="pull_request", conclusion="failure",
                     created="2026-01-01T00:00:00Z", run_id=1),
        ]
        code, out, _ = self.run_main("--branch", "main", "--once", runs=runs)
        self.assertEqual(code, 1, out)

    # -- durations ---------------------------------------------------------
    def test_seconds_is_utc_across_a_dst_change(self) -> None:
        old = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "America/New_York"
            time.tzset()
            if time.timezone != 18000:  # EST is five hours west of UTC
                self.skipTest("America/New_York tzdata is unavailable")
            # Three hours in UTC; a local-time parse would say two.
            self.assertEqual(
                self.ci.seconds("2026-03-08T01:00:00Z", "2026-03-08T04:00:00Z"),
                "10800s")
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_seconds_handles_missing_timestamps(self) -> None:
        self.assertEqual(self.ci.seconds(None, None), "?")
        self.assertEqual(self.ci.seconds("", "2026-01-01T00:00:05Z"), "?")
        self.assertEqual(self.ci.seconds("2026-01-01T00:00:00Z", None), "?")
        self.assertEqual(self.ci.seconds("2026-01-01T00:00:00Z",
                                          "2026-01-01T00:00:05Z"), "5s")

    # -- log helpers -------------------------------------------------------
    def test_interesting_lines_strips_timestamps_and_groups(self) -> None:
        log = (
            "2026-01-01T00:00:00.0000000Z ##[group]Run x\n"
            "2026-01-01T00:00:01.0000000Z ##[error]Expected: 1\n"
            "2026-01-01T00:00:02.0000000Z Actual: 2\n"
            "2026-01-01T00:00:03.0000000Z done\n"
        )
        lines = self.ci.interesting_lines(log)
        self.assertIn("##[error]Expected: 1", lines)
        self.assertIn("Actual: 2", lines)
        self.assertNotIn("##[group]Run x", lines)
        self.assertTrue(all(not line.startswith("2026-") for line in lines))

    def test_fetch_log_decompresses_gzip(self) -> None:
        with mock.patch.object(self.ci, "api",
                               return_value=gzip.compress(b"hello\n")):
            self.assertEqual(self.ci.fetch_log(1, "o/r", "t"), "hello\n")

    def test_fetch_log_plain_text(self) -> None:
        with mock.patch.object(self.ci, "api", return_value=b"plain\n"):
            self.assertEqual(self.ci.fetch_log(1, "o/r", "t"), "plain\n")

    def test_no_auth_redirect_strips_authorization(self) -> None:
        req = urllib.request.Request(
            "https://github.com/x",
            headers={"Authorization": "Bearer secret", "User-Agent": "t"})
        new = self.ci.NoAuthRedirect().redirect_request(
            req, None, 302, "Found", {}, "https://storage.example/log")
        self.assertNotIn("Authorization", new.headers)
        self.assertEqual(new.headers.get("User-agent"), "t")

    def test_resolve_token_does_not_shell_out_to_which(self) -> None:
        def forbidden(*args, **kwargs):
            raise AssertionError("subprocess.run must not be used for `which`")

        with mock.patch.object(self.ci.shutil, "which", return_value=None), \
                mock.patch.dict(os.environ, {"GITHUB_TOKEN": "",
                                             "GH_TOKEN": ""}), \
                mock.patch.object(self.ci.subprocess, "run",
                                  side_effect=forbidden):
            with self.assertRaises(SystemExit):
                self.ci.resolve_token(None)


if __name__ == "__main__":
    unittest.main()
