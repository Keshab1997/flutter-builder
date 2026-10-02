#!/usr/bin/env python3
"""ci_watch.py - wait for GitHub Actions on your commit and print what failed.

Polling CI by hand costs a turn (and a human's patience) every time. This
script does the waiting, then prints the conclusion of every workflow and the
interesting lines of the failed ones, so the next edit can start from the real
error instead of a guess.

Standard library only; works with a fine-grained or GitHub App token that can
read Actions (Actions: read, Contents: read).

Usage (inside any clone):
    python3 tool/ci_watch.py                  # watches the HEAD commit
    python3 tool/ci_watch.py --sha <sha>      # a specific commit
    python3 tool/ci_watch.py --branch main    # newest runs on a branch
    python3 tool/ci_watch.py --once           # report now, do not wait
    python3 tool/ci_watch.py --timeout 600 --interval 10

Token (first hit wins):
    --token-file PATH   e.g. secrets/gh_token.txt
    $GITHUB_TOKEN  /  $GH_TOKEN
    `gh auth token` when the GitHub CLI is installed

Exit code: 0 = everything green (or still running with --once), 1 = at least
one workflow failed, 2 = could not read state (token/repo/timeout).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s?")
LOG_INTEREST = re.compile(
    r"(##\[error\]|error •|warning •|info •|issue found|not formatted|"
    r"would reformat|Expected:|Actual:|FAILED|Failed to|Exception:|: Error:|"
    r"No such file|✗|error:)")


class NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects to blob storage without our header.

    Job-log downloads answer with a 302 to a pre-signed URL; sending the
    Authorization header along makes storage reject the request with
    "InvalidAuthenticationInfo ... token was missing or malformed" (HTTP 401),
    which looks like a permissions problem and is not one.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


OPENER = urllib.request.build_opener(NoAuthRedirect)


def die(msg: str, code: int = 2) -> None:
    print(f"ci_watch: {msg}", file=sys.stderr)
    raise SystemExit(code)


def git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True,
                             check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def resolve_token(arg: str | None) -> str:
    if arg:
        try:
            token = open(arg).read().strip()
        except OSError as e:
            die(f"cannot read --token-file {arg}: {e}")
        if token:
            return token
        die(f"--token-file {arg} is empty")
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        token = os.environ.get(var, "").strip()
        if token:
            return token
    if subprocess.run(["which", "gh"], capture_output=True).returncode == 0:
        try:
            token = subprocess.run(["gh", "auth", "token"], capture_output=True,
                                   text=True, check=True).stdout.strip()
        except subprocess.CalledProcessError:
            token = ""
        if token:
            return token
    die("no token: pass --token-file PATH, set $GITHUB_TOKEN, or run `gh auth login`")


def resolve_repo(arg: str | None) -> str:
    if arg:
        return arg
    url = git("remote", "get-url", "origin")
    if not url:
        die("no --repo given and no git 'origin' remote found")
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?$", url)
    if not m:
        die(f"cannot parse a GitHub repo out of origin URL: {url}")
    return f"{m.group('owner')}/{m.group('name')}"


def api(path: str, token: str, raw: bool = False):
    req = urllib.request.Request(API + path, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ci_watch.py (flutter-builder agent pack)"})
    try:
        with OPENER.open(req, timeout=60) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        die(f"HTTP {e.code} for {path}: {detail}")
    if raw:
        return data
    return json.loads(data.decode() or "{}")


def fetch_log(job_id: int, repo: str, token: str) -> str:
    data = api(f"/repos/{repo}/actions/jobs/{job_id}/logs", token, raw=True)
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode(errors="replace")


def interesting_lines(log: str, limit: int = 15) -> list[str]:
    hits: list[str] = []
    for raw in log.splitlines():
        line = TIMESTAMP.sub("", raw).rstrip()
        if LOG_INTEREST.search(line) and "##[group]" not in line:
            if line not in hits:
                hits.append(line)
        if len(hits) >= limit:
            break
    tail = [TIMESTAMP.sub("", l).rstrip() for l in log.splitlines()[-3:] if l.strip()]
    for line in tail:
        if line and line not in hits:
            hits.append(line)
    return hits


def seconds(iso_a: str, iso_b: str) -> str:
    try:
        def parse(s: str) -> float:
            return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
        return f"{int(parse(iso_b) - parse(iso_a))}s"
    except Exception:  # noqa: BLE001 - display only
        return "?"


def main() -> int:
    p = argparse.ArgumentParser(
        prog="ci_watch.py",
        description="Wait for GitHub Actions on a commit and print what failed.")
    p.add_argument("--repo", help="owner/name (default: the origin remote)")
    p.add_argument("--sha", help="commit to watch (default: HEAD)")
    p.add_argument("--branch", help="watch the newest runs of a branch instead")
    p.add_argument("--token-file", help="file containing a GitHub token")
    p.add_argument("--timeout", type=int, default=900,
                   help="give up after N seconds of waiting (default 900)")
    p.add_argument("--interval", type=int, default=15,
                   help="poll interval in seconds (default 15)")
    p.add_argument("--once", action="store_true",
                   help="report the current state without waiting")
    p.add_argument("--quiet", action="store_true",
                   help="only print the final report")
    args = p.parse_args()

    token = resolve_token(args.token_file)
    repo = resolve_repo(args.repo)
    sha = args.sha
    if not sha and not args.branch:
        sha = git("rev-parse", "HEAD") or die(
            "not a git repository and no --sha/--branch given")

    if args.branch:
        query = f"/repos/{repo}/actions/runs?branch={urllib.parse.quote(args.branch)}&per_page=30"
        label = f"branch {args.branch}"
    else:
        query = f"/repos/{repo}/actions/runs?head_sha={sha}&per_page=30"
        label = f"commit {sha[:9]}"

    print(f"ci_watch: {repo} {label}")
    deadline = time.time() + args.timeout
    runs: list[dict] = []
    while True:
        runs = api(query, token).get("workflow_runs", [])
        active = [w for w in runs if w.get("status") != "completed"]
        if runs and (not active or args.once or time.time() >= deadline):
            break
        if not runs and args.once:
            break
        if time.time() >= deadline:
            print(f"ci_watch: timed out after {args.timeout}s", file=sys.stderr)
            return 2
        if not args.quiet:
            if not runs:
                print(f"  [{time.strftime('%H:%M:%S')}] waiting for runs to appear ...")
            else:
                state = " | ".join(
                    f"{w['name']}={w.get('conclusion') or w['status']}"
                    for w in sorted(active, key=lambda x: x["name"]))
                print(f"  [{time.strftime('%H:%M:%S')}] {state}")
        time.sleep(args.interval)

    if not runs:
        print("ci_watch: no workflow runs found for this commit yet")
        return 2

    print("\nworkflow                 event         result     duration")
    failures: list[dict] = []
    for w in sorted(runs, key=lambda x: (x["name"], x["event"])):
        result = w.get("conclusion") or w.get("status")
        print(f"  {w['name'][:22]:<22} {w['event'][:12]:<12} {str(result):<10} "
              f"{seconds(w['run_started_at'], w['updated_at'])}")
        if w.get("conclusion") == "failure":
            failures.append(w)

    if not failures:
        pending = [w for w in runs if w.get("status") != "completed"]
        if pending:
            names = ", ".join(sorted({w["name"] for w in pending}))
            print(f"\nci_watch: no failures yet, still running: {names}")
            print("(run without --once to wait for the result)")
        else:
            print("\nci_watch: all green")
        return 0

    for w in failures:
        print(f"\n=== FAILED: {w['name']} ({w['event']}) {w['html_url']}")
        jobs = api(f"/repos/{repo}/actions/runs/{w['id']}/jobs", token).get("jobs", [])
        for job in jobs:
            if job.get("conclusion") != "failure":
                continue
            failed_step = next((s["name"] for s in job.get("steps", [])
                                if s.get("conclusion") == "failure"), "?")
            print(f"\n  job: {job['name']}  (failed step: {failed_step})")
            print(f"  {job.get('html_url', '')}")
            try:
                log = fetch_log(job["id"], repo, token)
            except SystemExit:
                print("    (could not download this log)")
                continue
            for line in interesting_lines(log):
                print(f"    {line[:200]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
