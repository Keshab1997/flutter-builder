"""Read-only timing report for recent GitHub Pages preview runs."""
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import preview_timing as timing  # noqa: E402


class RepositoryTests(unittest.TestCase):
    def test_parses_common_github_remote_shapes(self) -> None:
        remotes = (
            "https://github.com/Keshab1997/docify.git",
            "https://github.com/Keshab1997/docify",
            "git@github.com:Keshab1997/docify.git",
            "ssh://git@github.com/Keshab1997/docify.git",
        )
        for remote in remotes:
            with self.subTest(remote=remote):
                self.assertEqual(
                    timing.parse_repo_remote(remote), "Keshab1997/docify"
                )

    def test_rejects_non_github_remote(self) -> None:
        self.assertIsNone(timing.parse_repo_remote("https://gitlab.com/o/r.git"))

    def test_repo_argument_must_be_owner_slash_name(self) -> None:
        with self.assertRaises(timing.PreviewTimingError):
            timing.resolve_repo("not-a-repo")


class DurationTests(unittest.TestCase):
    def test_computes_utc_durations_and_clamps_negative_values(self) -> None:
        self.assertEqual(
            timing.duration_seconds("2026-10-13T10:00:00Z", "2026-10-13T10:02:05Z"),
            125,
        )
        self.assertEqual(
            timing.duration_seconds("2026-10-13T10:02:05Z", "2026-10-13T10:00:00Z"),
            0,
        )

    def test_missing_or_invalid_time_is_unknown(self) -> None:
        self.assertIsNone(timing.duration_seconds(None, "2026-10-13T10:00:00Z"))
        self.assertIsNone(timing.duration_seconds("bad", "2026-10-13T10:00:00Z"))

    def test_format_duration_handles_seconds_minutes_and_missing(self) -> None:
        self.assertEqual(timing.format_duration(8), "8s")
        self.assertEqual(timing.format_duration(125), "2m 05s")
        self.assertEqual(timing.format_duration(None), "-")


class RunSummaryTests(unittest.TestCase):
    def test_extracts_named_preview_steps_and_total_runtime(self) -> None:
        run = {
            "id": 42,
            "head_branch": "feature/web",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "run_started_at": "2026-10-13T10:00:00Z",
            "completed_at": "2026-10-13T10:05:00Z",
        }
        jobs = [{
            "name": "preview",
            "conclusion": "success",
            "started_at": "2026-10-13T10:00:00Z",
            "completed_at": "2026-10-13T10:03:30Z",
            "steps": [
                {"name": "Set up Flutter", "started_at": "2026-10-13T10:00:10Z",
                 "completed_at": "2026-10-13T10:00:40Z"},
                {"name": "Install dependencies", "started_at": "2026-10-13T10:00:45Z",
                 "completed_at": "2026-10-13T10:00:53Z"},
                {"name": "Build web bundle", "started_at": "2026-10-13T10:01:00Z",
                 "completed_at": "2026-10-13T10:02:35Z"},
                {"name": "Deploy to GitHub Pages", "started_at": "2026-10-13T10:02:40Z",
                 "completed_at": "2026-10-13T10:03:20Z"},
            ],
        }]
        record = timing.run_record(run, jobs)
        self.assertEqual(record["duration_seconds"], 300)
        self.assertEqual(record["jobs"], [{
            "name": "preview",
            "conclusion": "success",
            "duration_seconds": 210,
        }])
        self.assertEqual(record["steps"]["flutter_setup"], 30)
        self.assertEqual(record["steps"]["pub_get"], 8)
        self.assertEqual(record["steps"]["build_web"], 95)
        self.assertEqual(record["steps"]["deploy"], 40)
        self.assertNotIn("preview_hub", record["steps"])

    def test_median_ignores_missing_step_samples(self) -> None:
        records = [
            {"duration_seconds": 100, "steps": {"build_web": 40}},
            {"duration_seconds": 200, "steps": {"build_web": 80}},
            {"duration_seconds": 300, "steps": {}},
        ]
        summary = timing.median_seconds(records)
        self.assertEqual(summary["total"], 200)
        self.assertEqual(summary["build_web"], 60)
        self.assertIsNone(summary["deploy"])
        self.assertEqual(
            timing.median_seconds([
                {"duration_seconds": 1, "steps": {}},
                {"duration_seconds": 2, "steps": {}},
            ])["total"],
            2,
        )

    def test_median_job_durations_ignore_missing_samples(self) -> None:
        records = [
            {"jobs": [
                {"name": "preview", "duration_seconds": 90},
                {"name": "cleanup", "duration_seconds": 40},
            ]},
            {"jobs": [
                {"name": "preview", "duration_seconds": 190},
                {"name": "cleanup", "duration_seconds": None},
            ]},
        ]
        self.assertEqual(
            timing.median_job_seconds(records),
            {"cleanup": 40, "preview": 140},
        )


class ApiSafetyTests(unittest.TestCase):
    def test_api_error_redacts_a_token(self) -> None:
        secret = "ghu-do-not-print-this"
        error = HTTPError(
            "https://api.github.com/private",
            403,
            "Forbidden",
            None,
            io.BytesIO(json.dumps({"message": f"invalid {secret}"}).encode()),
        )
        with patch.object(timing.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(timing.PreviewTimingError) as caught:
                timing.api_get("/private", secret)
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("Actions: read", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
