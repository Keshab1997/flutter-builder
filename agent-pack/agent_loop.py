#!/usr/bin/env python3
"""agent_loop.py - one command for one full change loop.

An agent working in this repository normally spends four or five tool calls
per iteration: run preflight, commit, push, wait for CI, read the failure.
Every one of those calls is a place where the loop can be abandoned halfway -
a push without a preflight, a CI run nobody read, a commit made on `main`.

This script performs the whole loop in one call and stops at the first thing
that would waste a CI run:

    preflight  ->  secret guard  ->  commit  ->  push  ->  ci_watch

    python3 tool/agent_loop.py -m "fix(profile): guard null avatar"
    python3 tool/agent_loop.py -m "..." --amend          # fix the last commit
    python3 tool/agent_loop.py -m "..." --draft-pr       # branch + draft PR
    python3 tool/agent_loop.py -m "..." --no-watch       # push and stop

What it refuses to do, on purpose:

  * commit on the default branch (main/master) unless `--allow-main` is given:
    nobody reviews a change that never left main, and CI there is not free;
  * commit a file that looks like a credential (`.env`, `*.jks`, `*.keystore`,
    `*.pem`, `key.properties`, `google-services.json`, `secrets/**`, ...)
    unless `--allow-secret-paths` is given: the playbook says secrets never
    enter git, and a pre-commit refusal is cheaper than a history rewrite;
  * push when `tool/preflight.py` reports issues, unless `--no-preflight` is
    given: those findings are exactly what turns a push red.

Exit codes: 0 = pushed (and green, when watched); 1 = CI failed or the push
failed; 2 = refused or stopped before anything was changed.

Standard library only, python3 >= 3.8. `git` must be on PATH.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.github.com"

# Paths that must not be committed. Deliberately a short list of things that
# are secrets in *every* Flutter/Android project; anything project-specific
# belongs in .gitignore, which this script also honours (see staged_secrets).
SECRET_PATTERNS = [
    r"(^|/)\.env(\..*)?$",
    r"\.jks$", r"\.keystore$", r"\.p12$", r"\.pfx$", r"\.pem$", r"\.key$",
    r"(^|/)key\.properties$",
    r"(^|/)google-services\.json$",
    r"(^|/)GoogleService-Info\.plist$",
    r"(^|/)secrets/",
    r"(^|/)service-account.*\.json$",
]

DEFAULT_BRANCHES = ("main", "master")


class Stop(Exception):
    """A refusal that must happen before anything is changed."""


def run(cmd: list[str], cwd: Path | None = None, check: bool = True,
        capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command, printing it the way a human would type it."""
    try:
        proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True,
                              capture_output=capture, check=False)
    except FileNotFoundError as e:
        raise Stop(f"cannot run {cmd[0]}: {e}") from e
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise Stop(f"`{' '.join(cmd)}` failed ({proc.returncode})"
                   + (f":\n{detail}" if detail else ""))
    return proc


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=cwd, check=check)


def git_out(*args: str, cwd: Path) -> str:
    return git(*args, cwd=cwd).stdout.strip()


def repo_root() -> Path:
    proc = run(["git", "rev-parse", "--show-toplevel"], check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise Stop("not inside a git repository")
    return Path(proc.stdout.strip())


def default_branch(root: Path) -> str:
    """Best effort: origin/HEAD, then whichever of main/master exists."""
    proc = git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", cwd=root,
               check=False)
    if proc.returncode == 0 and "/" in proc.stdout:
        return proc.stdout.strip().rsplit("/", 1)[-1]
    for name in DEFAULT_BRANCHES:
        if git("rev-parse", "--verify", "--quiet", f"refs/heads/{name}", cwd=root,
               check=False).returncode == 0:
            return name
    return "main"


def staged_secrets(root: Path) -> list[str]:
    """Staged paths that look like credentials (ignoring .gitignore'd ones)."""
    proc = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", cwd=root)
    hits: list[str] = []
    for path in proc.stdout.splitlines():
        path = path.strip()
        if not path:
            continue
        if any(re.search(pattern, path) for pattern in SECRET_PATTERNS):
            hits.append(path)
    return hits


def resolve_token(arg: str | None) -> str | None:
    """Same order as ci_watch.py: flag, environment, then the GitHub CLI."""
    if arg:
        try:
            token = Path(arg).read_text(encoding="utf-8").strip()
        except OSError as e:
            raise Stop(f"cannot read --token-file {arg}: {e}") from e
        return token or None
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        token = os.environ.get(var, "").strip()
        if token:
            return token
    if subprocess.run(["which", "gh"], capture_output=True).returncode == 0:
        proc = subprocess.run(["gh", "auth", "token"], capture_output=True,
                              text=True, check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return None


def api_request(method: str, path: str, token: str, payload: dict | None = None):
    url = path if path.startswith("http") else API + path
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "agent_loop.py (flutter-builder agent pack)",
        "Authorization": f"Bearer {token}",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"message": body[:300]}
    except Exception as e:  # noqa: BLE001 - transport failures are reported, not raised
        return 0, {"message": str(e)}


def github_repo(root: Path) -> str | None:
    proc = git("remote", "get-url", "origin", cwd=root, check=False)
    if proc.returncode != 0:
        return None
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/.]+?)(?:\.git)?$",
                      proc.stdout.strip())
    return f"{match.group('owner')}/{match.group('name')}" if match else None


def open_or_update_pr(root: Path, branch: str, title: str, body: str,
                      draft: bool, token: str, ready: bool) -> int:
    """Create a PR for the branch (or report the existing one). Draft by default."""
    repo = github_repo(root)
    if not repo:
        print("agent_loop: no GitHub 'origin' remote; skipping the PR step.")
        return 0
    owner = repo.split("/")[0]
    status, existing = api_request("GET", f"/repos/{repo}/pulls?head={owner}:{branch}&state=open",
                                   token)
    if status == 200 and existing:
        pr = existing[0]
        print(f"Pull request already open: {pr['html_url']}")
        if ready and pr.get("draft"):
            status, data = api_request("POST", "/graphql", token, {
                "query": "mutation($id: ID!) { markPullRequestReadyForReview(input: {pullRequestId: $id})"
                         " { pullRequest { url isDraft } } }",
                "variables": {"id": pr["node_id"]},
            })
            if status == 200 and "errors" not in data:
                print("Marked the pull request ready for review.")
            else:
                print(f"::warning::could not mark it ready: {data}")
        return 0
    base = default_branch(root)
    status, pr = api_request("POST", f"/repos/{repo}/pulls", token, {
        "title": title, "head": branch, "base": base, "body": body, "draft": draft,
    })
    if status in (200, 201):
        print(f"Pull request {'(draft) ' if draft else ''}created: {pr['html_url']}")
        return 0
    print(f"agent_loop: could not open a pull request (HTTP {status}): "
          f"{pr.get('message', pr)}")
    return 0  # a PR problem must not fail an otherwise good push


def watch(root: Path, sha: str, args) -> int:
    """Delegate to the sibling ci_watch.py, which owns the polling behaviour."""
    script = HERE / "ci_watch.py"
    if not script.exists():
        print(f"agent_loop: {script} not found; push finished, watch skipped.")
        return 0
    cmd = [sys.executable, str(script), "--sha", sha]
    if args.token_file:
        cmd += ["--token-file", args.token_file]
    if args.timeout:
        cmd += ["--timeout", str(args.timeout)]
    if args.interval:
        cmd += ["--interval", str(args.interval)]
    return subprocess.run(cmd, cwd=str(root)).returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="agent_loop.py",
        description="preflight -> commit -> push -> watch CI, in one call.")
    parser.add_argument("-m", "--message", help="commit message (conventional commits)")
    parser.add_argument("--amend", action="store_true",
                        help="amend the last commit (pushes with --force-with-lease)")
    parser.add_argument("--paths", nargs="*", default=None,
                        help="paths to stage (default: everything changed)")
    parser.add_argument("--allow-main", action="store_true",
                        help="permit a commit on the default branch")
    parser.add_argument("--allow-secret-paths", action="store_true",
                        help="stage files that look like credentials (review them first)")
    parser.add_argument("--no-preflight", action="store_true",
                        help="skip tool/preflight.py (CI will be the first check)")
    parser.add_argument("--no-push", action="store_true", help="commit only")
    parser.add_argument("--no-watch", action="store_true",
                        help="push and return (useful for draft pull requests)")
    parser.add_argument("--draft-pr", action="store_true",
                        help="open a draft pull request for this branch")
    parser.add_argument("--ready", action="store_true",
                        help="mark an existing draft pull request ready for review")
    parser.add_argument("--token-file",
                        help="file holding a GitHub token (for --draft-pr / watching)")
    parser.add_argument("--timeout", type=int, help="passed to ci_watch.py")
    parser.add_argument("--interval", type=int, help="passed to ci_watch.py")
    args = parser.parse_args(argv[1:])

    if not args.message and not args.amend:
        parser.error("give -m/--message (or --amend to reuse the previous message)")
    if args.no_preflight and not (args.no_watch or args.no_push):
        print("agent_loop: --no-preflight with a watched push means CI is the "
              "first check; that is exactly the slow path this tool avoids.")

    root = repo_root()
    branch = git_out("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    base = default_branch(root)
    if branch == base and not args.allow_main:
        raise Stop(
            f"HEAD is on '{branch}' (the default branch). Commit on a branch "
            f"instead, or pass --allow-main if the project really works that way.\n"
            f"  git switch -c fix/short-description")
    if branch == "HEAD":
        raise Stop("detached HEAD; check out a branch first.")

    started = time.time()

    # 1. preflight -- the cheap check that saves a full CI round.
    if not args.no_preflight:
        script = HERE / "preflight.py"
        if script.exists():
            proc = subprocess.run([sys.executable, str(script)], cwd=str(root),
                                  text=True, capture_output=True)
            sys.stdout.write(proc.stdout)
            if proc.returncode != 0:
                print("agent_loop: preflight reported issues - nothing was "
                      "committed. Fix them, or pass --no-preflight if they are "
                      "deliberate.", file=sys.stderr)
                return 2
        else:
            print(f"agent_loop: {script} not found; preflight skipped.")

    # 2. stage.
    if args.paths:
        git("add", "--", *args.paths, cwd=root)
    else:
        git("add", "-A", cwd=root)

    if not args.amend:
        staged = git("diff", "--cached", "--name-only", cwd=root).stdout.strip()
        if not staged:
            print("agent_loop: nothing staged; there is no change to commit.")
            return 2

    # 3. secret guard -- before the commit, never after the push.
    hits = staged_secrets(root)
    if hits and not args.allow_secret_paths:
        print("agent_loop: refusing to commit files that look like credentials:",
              file=sys.stderr)
        for path in hits:
            print(f"  {path}", file=sys.stderr)
        print("  Add them to .gitignore (and rotate anything already exposed), "
              "or pass --allow-secret-paths if they are safe by design.",
              file=sys.stderr)
        return 2

    # 4. commit.
    if args.amend:
        cmd = ["commit", "--amend", "--no-edit"] if not args.message \
            else ["commit", "--amend", "-m", args.message]
        git(*cmd, cwd=root)
    else:
        git("commit", "-m", args.message, cwd=root)
    sha = git_out("rev-parse", "HEAD", cwd=root)
    print(f"Committed {sha[:7]} on {branch}: "
          f"{git_out('log', '-1', '--pretty=%s', cwd=root)}")

    if args.no_push:
        print("agent_loop: --no-push; stopped after the commit.")
        return 0

    # 5. push. An amended commit needs --force-with-lease: plain --force would
    # risk clobbering work somebody else pushed to the same branch.
    push = ["push"]
    if args.amend:
        push += ["--force-with-lease"]
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name",
                   "@{upstream}", cwd=root, check=False).returncode != 0
    if upstream:
        push += ["-u", "origin", branch]
    proc = run(["git", *push], cwd=root, check=False)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        print("agent_loop: push failed (see git's message above).", file=sys.stderr)
        return 1
    print(f"Pushed {sha[:7]} ({time.time() - started:.1f}s since start).")

    if args.draft_pr or args.ready:
        token = resolve_token(args.token_file)
        if not token:
            print("agent_loop: no token for the PR step (--token-file, "
                  "$GITHUB_TOKEN, or `gh auth login`).")
        else:
            title = args.message or git_out("log", "-1", "--pretty=%s", cwd=root)
            open_or_update_pr(root, branch, title,
                              "Opened by `tool/agent_loop.py`.\n\n"
                              "<!-- agent-loop-pr -->", draft=not args.ready,
                              token=token, ready=args.ready)
            if not args.ready:
                print("Draft PRs run no CI; use --ready when you want the run.")

    # 6. watch. A draft PR runs no CI at all, so waiting would time out.
    if args.no_watch or args.draft_pr:
        print("agent_loop: done (CI not watched).")
        return 0
    return watch(root, sha, args)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except Stop as e:
        print(f"agent_loop: {e}", file=sys.stderr)
        raise SystemExit(2)
    except KeyboardInterrupt:
        raise SystemExit("\ninterrupted.")
