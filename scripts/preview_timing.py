#!/usr/bin/env python3
"""Report where recent GitHub Pages web-preview runs spend their time.

This is read-only and uses only the Python standard library. It reports
workflow runtimes, job durations, and named step timings, so cache/build changes
can be based on real runs rather than guesses.

Usage:
    python3 scripts/preview_timing.py --repo OWNER/REPO --limit 20
    python3 scripts/preview_timing.py --branch main --json

Authentication is optional for public repositories. For private repositories,
use --token-file, $GITHUB_TOKEN / $GH_TOKEN, or `gh auth login`. The token is
never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

API = "https://api.github.com"
REPO_RE = re.compile(
    r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
STEP_NAMES = {
    "Set up Flutter": "flutter_setup",
    "Install dependencies": "pub_get",
    "Build web bundle": "build_web",
    "Deploy to GitHub Pages": "deploy",
    "Refresh the preview hub index": "preview_hub",
}
STEP_LABELS = {
    "flutter_setup": "Flutter setup",
    "pub_get": "pub get",
    "build_web": "web build",
    "deploy": "Pages deploy",
    "preview_hub": "preview hub",
}


class PreviewTimingError(Exception):
    """An actionable input or GitHub API error."""


def parse_repo_remote(url: str) -> Optional[str]:
    match = REPO_RE.search(url.strip())
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def resolve_repo(value: Optional[str]) -> str:
    if value:
        repo = value.strip()
    else:
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise PreviewTimingError(
                "pass --repo OWNER/REPO or run inside a clone with an origin remote"
            ) from error
        repo = parse_repo_remote(result.stdout)
        if not repo:
            raise PreviewTimingError("could not parse a GitHub repository from origin")

    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repo):
        raise PreviewTimingError("--repo must be OWNER/REPO")
    return repo


def resolve_token(token_file: Optional[str]) -> Optional[str]:
    if token_file:
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as error:
            raise PreviewTimingError(f"cannot read --token-file: {error}") from error
        if not token:
            raise PreviewTimingError("--token-file is empty")
        return token

    for variable in ("GITHUB_TOKEN", "GH_TOKEN"):
        token = os.environ.get(variable, "").strip()
        if token:
            return token

    if shutil.which("gh"):
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        token = result.stdout.strip()
        return token or None
    return None


def api_get(path: str, token: Optional[str] = None) -> Dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "flutter-builder-preview-timing",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:250]
        if token:
            detail = detail.replace(token, "[redacted]")
        if error.code in (401, 403):
            message = (
                "GitHub API access denied; check Actions: read permission and token"
            )
        elif error.code == 404:
            message = "repo/workflow not found, or token cannot read Actions"
        else:
            message = f"GitHub API returned HTTP {error.code}: {detail}"
        raise PreviewTimingError(message) from error
    except urllib.error.URLError as error:
        raise PreviewTimingError(f"GitHub API request failed: {error.reason}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreviewTimingError("GitHub API returned invalid JSON") from error


def parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def duration_seconds(start: Optional[str], end: Optional[str]) -> Optional[int]:
    first = parse_time(start)
    last = parse_time(end)
    if first is None or last is None:
        return None
    return max(0, int((last - first).total_seconds()))


def run_record(run: Dict[str, Any], jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    end = run.get("completed_at") or run.get("updated_at")
    total = duration_seconds(run.get("run_started_at"), end)
    job_records: List[Dict[str, Any]] = []
    steps: Dict[str, int] = {}
    for job in jobs:
        job_records.append({
            "name": job.get("name") or "?",
            "conclusion": job.get("conclusion") or job.get("status") or "?",
            "duration_seconds": duration_seconds(
                job.get("started_at"), job.get("completed_at")
            ),
        })
        for step in job.get("steps", []):
            key = STEP_NAMES.get(step.get("name", ""))
            elapsed = duration_seconds(step.get("started_at"), step.get("completed_at"))
            if key and elapsed is not None:
                steps[key] = steps.get(key, 0) + elapsed

    return {
        "id": run.get("id"),
        "branch": run.get("head_branch") or "?",
        "event": run.get("event") or "?",
        "conclusion": run.get("conclusion") or run.get("status") or "?",
        "started_at": run.get("run_started_at"),
        "duration_seconds": total,
        "jobs": job_records,
        "steps": steps,
    }


def format_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "-"
    minutes, remainder = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {remainder:02d}s"
    return f"{remainder}s"


def median_seconds(records: List[Dict[str, Any]]) -> Dict[str, Optional[int]]:
    result: Dict[str, Optional[int]] = {}
    for key, label in [("total", "total"), *[(k, k) for k in STEP_LABELS]]:
        values: List[int] = []
        for record in records:
            value = record["duration_seconds"] if key == "total" else record["steps"].get(key)
            if value is not None:
                values.append(value)
        result[label] = int(statistics.median(values) + 0.5) if values else None
    return result


def median_job_seconds(records: List[Dict[str, Any]]) -> Dict[str, Optional[int]]:
    names = sorted({
        job["name"]
        for record in records
        for job in record.get("jobs", [])
        if job.get("name") and job["name"] != "?"
    })
    result: Dict[str, Optional[int]] = {}
    for name in names:
        values = [
            job["duration_seconds"]
            for record in records
            for job in record.get("jobs", [])
            if job.get("name") == name and job.get("duration_seconds") is not None
        ]
        result[name] = int(statistics.median(values) + 0.5) if values else None
    return result


def print_text(records: List[Dict[str, Any]], repo: str,
               pending: int = 0) -> None:
    print(f"Preview timing: {repo} ({len(records)} completed run(s), {pending} pending)")
    print("run       branch                    event             result       total     pub get  web build  deploy")
    for record in records:
        steps = record["steps"]
        print(
            f"{str(record['id'] or '?'):<9} "
            f"{record['branch'][:25]:<25} "
            f"{record['event'][:16]:<16} "
            f"{record['conclusion'][:11]:<11} "
            f"{format_duration(record['duration_seconds']):>8} "
            f"{format_duration(steps.get('pub_get')):>9} "
            f"{format_duration(steps.get('build_web')):>10} "
            f"{format_duration(steps.get('deploy')):>8}"
        )
        job_times = [
            f"{job['name']} {format_duration(job['duration_seconds'])}"
            for job in record.get("jobs", [])
        ]
        if job_times:
            print("  Jobs: " + " | ".join(job_times))

    if records:
        medians = median_seconds(records)
        summary = [f"total {format_duration(medians['total'])}"]
        for key in ("flutter_setup", "pub_get", "build_web", "deploy", "preview_hub"):
            summary.append(f"{STEP_LABELS[key]} {format_duration(medians[key])}")
        for name, seconds in median_job_seconds(records).items():
            summary.append(f"job {name} {format_duration(seconds)}")
        print("Median: " + " | ".join(summary))
    if pending:
        print("Pending runs are not included in timing samples.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure recent GitHub Actions web-preview runs (read-only)."
    )
    parser.add_argument("--repo", help="OWNER/REPO; default: infer from git origin")
    parser.add_argument("--workflow", default="web-preview.yml",
                        help="caller workflow filename (default: web-preview.yml)")
    parser.add_argument("--branch", help="limit runs to one branch")
    parser.add_argument("--limit", type=int, default=10,
                        help="number of recent runs to inspect (1-100, default 10)")
    parser.add_argument("--token-file", help="file containing a GitHub token")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args(argv)

    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")

    try:
        repo = resolve_repo(args.repo)
        token = resolve_token(args.token_file)
        workflow_path = urllib.parse.quote(args.workflow, safe="")
        query = {"per_page": str(args.limit)}
        if args.branch:
            query["branch"] = args.branch
        runs_path = (
            f"/repos/{urllib.parse.quote(repo, safe='/')}/actions/workflows/"
            f"{workflow_path}/runs?{urllib.parse.urlencode(query)}"
        )
        response = api_get(runs_path, token)
        all_runs = response.get("workflow_runs", [])
        pending = sum(1 for run in all_runs if run.get("status") != "completed")
        records: List[Dict[str, Any]] = []
        for run in all_runs:
            if run.get("status") != "completed":
                continue
            jobs_path = (
                f"/repos/{urllib.parse.quote(repo, safe='/')}/actions/runs/"
                f"{run['id']}/jobs?per_page=100"
            )
            jobs = api_get(jobs_path, token).get("jobs", [])
            records.append(run_record(run, jobs))

        if args.json:
            print(json.dumps({
                "repo": repo,
                "workflow": args.workflow,
                "pending": pending,
                "runs": records,
                "median_seconds": median_seconds(records),
                "median_job_seconds": median_job_seconds(records),
            }, indent=2))
        else:
            print_text(records, repo, pending)
        return 0 if records else 2
    except PreviewTimingError as error:
        print(f"preview_timing: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
