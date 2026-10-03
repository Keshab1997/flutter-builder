#!/usr/bin/env python3
"""see_screen.py - have CI photograph a screen, then look at the picture.

Why this exists
---------------
An agent working in this repository can edit any screen and still never *see*
one: there is no emulator, no phone, and `flutter build` is minutes it does not
have. That is how a change shipping a squashed layout, an invisible button or a
half-translated label reaches a human - nobody looked.

`ui-screenshots.yml` already knows how to turn a route into a PNG; this script
is the missing sentence: give it a route and it dispatches that workflow in this
repository, waits, downloads the artifact and prints the paths of the images,
so the next tool an agent reaches for is an image reader, not a guess.

    python3 tool/see_screen.py --route /settings
    python3 tool/see_screen.py --route /settings --route /profile
    python3 tool/see_screen.py --route / --viewport 390x844 --wait-ms 12000
    python3 tool/see_screen.py --route /settings --out /tmp/shots --json

One run captures every `--route`, so asking for three screens costs one build,
not three. Images land in `.agent-screens/<n>-<route>/` as
`<screen>-<WxH>.png` next to the capture manifest.

Credentials
-----------
`--token-file`, then `$GH_TOKEN`, then `$GITHUB_TOKEN`, then `gh auth token`
(`gh` is the one most agent sandboxes already have). A fine-grained token needs
`Actions: write` on the repository to dispatch and `Contents: read` to fetch the
artifact; a classic token needs `repo`.

Honest limits
-------------
* This is the *web* build of the app. Layout, colours, spacing and text are what
  a user would see; fonts and platform widgets differ slightly, and plugins that
  never run on web (camera, bluetooth, local notifications) make a blank shot -
  the manifest reports the pixel count, and this script calls a flat image out.
* Still pictures: no animation, no scroll position, no keyboard. A screen behind
  a login or a tap-through flow cannot be reached by a route; that needs an
  integration test, which the pack does not generate.
* The screenshot exists only if the app builds for web. `--generate-web-platform`
  is for apps that have never had a `web/` folder.
* Nothing is committed: the artifact is thrown away by GitHub after a few days,
  and the copy this script downloads lives in `.agent-screens/` (git-ignored on
  install) until deleted.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

WORKFLOW_FILE = "ui-screenshots.yml"
WORKFLOW_REPO = "Keshab1997/flutter-builder"
API = "https://api.github.com"
DEFAULT_OUT = ".agent-screens"
DEFAULT_VIEWPORTS = "390x844,768x1024"
DEFAULT_WAIT_MS = "8000"
FLAT_COLOUR_LIMIT = 2  # a screen that never painted; see pngStats() in capture-pages.cjs


# --------------------------------------------------------------------------
# small pieces, so the interesting ones can be tested without a network
# --------------------------------------------------------------------------
def parse_remote(url: str) -> str | None:
    """`https://github.com/o/r.git`, `git@github.com:o/r.git` -> `o/r`."""
    url = (url or "").strip()
    match = re.search(r"github\.com[:/]+(?P<slug>[^/\s]+/[^/\s]+?)(?:\.git)?/?$", url)
    return match.group("slug") if match else None


def repo_slug(cwd: Path) -> str | None:
    try:
        done = subprocess.run(["git", "remote", "get-url", "origin"], cwd=str(cwd),
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_remote(done.stdout) if done.returncode == 0 else None


def route_slug(route: str) -> str:
    """`/settings/edit` -> `settings-edit`; `/` -> `home`."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", (route or "/").lower()).strip("-")
    return cleaned or "home"


def build_inputs(routes: list[str], args: argparse.Namespace, note: str) -> dict:
    """The workflow_dispatch inputs the caller forwards to the reusable workflow."""
    inputs = {
        "routes": ",".join(routes),
        "viewports": args.viewports or DEFAULT_VIEWPORTS,
        "wait-ms": str(args.wait_ms or DEFAULT_WAIT_MS),
        "note": note,
    }
    if args.dart_defines:
        inputs["dart-defines"] = args.dart_defines
    return inputs


def pick_run(runs: list[dict], note: str, not_before: float) -> dict | None:
    """The run this script just dispatched: same note, dispatched after we asked.

    `run-name` in the caller writes the note into the run's display title, so a
    concurrent manual run of the same workflow cannot be mistaken for ours.
    Falls back to the newest dispatch started after `not_before` (older callers
    do not carry the note input).
    """
    exact = [r for r in runs
             if note and note in (r.get("display_title") or "")
             and r.get("event") == "workflow_dispatch"]
    if exact:
        return sorted(exact, key=lambda r: r.get("created_at", ""))[-1]
    recent = [r for r in runs if r.get("event") == "workflow_dispatch"
              and _epoch(r.get("created_at")) >= not_before - 5]
    return sorted(recent, key=lambda r: r.get("created_at", ""))[-1] if recent else None


def _epoch(stamp: str | None) -> float:
    if not stamp:
        return 0.0
    return time.mktime(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone


def summarise_manifest(path: Path) -> list[dict]:
    """Rows of manifest.tsv: name, route, viewport, bytes, colours, top share."""
    rows = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        row = {"name": fields[0], "route": fields[1], "viewport": fields[2],
               "bytes": int(fields[3]) if fields[3].isdigit() else 0,
               "colours": int(fields[4]) if len(fields) > 4 and fields[4].lstrip("-").isdigit() else None}
        rows.append(row)
    return rows


class _StripAuthOnHostChange(urllib.request.HTTPRedirectHandler):
    """GitHub redirects artifact downloads to blob storage.

    That target rejects the Authorization header ("Server failed to
    authenticate the request"), and urllib would forward it - so the header is
    dropped the moment the host changes. Same trap that swallowed the first
    attempt at fetching job logs.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and (urllib.parse.urlsplit(newurl).hostname
                                != urllib.parse.urlsplit(req.full_url).hostname):
            new.remove_header("Authorization")
        return new


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_StripAuthOnHostChange)


def api(method: str, path: str, token: str, payload: dict | None = None,
        raw: bool = False, timeout: int = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "flutter-builder-see-screen",
        "Content-Type": "application/json",
    })
    try:
        with _opener().open(req, timeout=timeout) as response:
            body = response.read()
            return body if raw else (json.loads(body.decode() or "{}") if body.strip() else {})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        hint = ""
        if exc.code in (401, 403):
            hint = " (token missing, expired, or without Actions: write)"
        elif exc.code == 404:
            hint = f" (no {WORKFLOW_FILE} in this repository, or no access to it)"
        raise SystemExit(f"see_screen: GitHub said {exc.code}{hint}\n{detail}") from exc


def resolve_token(token_file: str | None) -> str:
    if token_file:
        token = Path(token_file).read_text(encoding="utf-8").strip()
        if not token:
            raise SystemExit(f"see_screen: {token_file} is empty")
        return token
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    if shutil.which("gh"):
        done = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=30)
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    raise SystemExit(
        "see_screen: no GitHub token.\n"
        "  Run `gh auth login`, or export GH_TOKEN=... (needs Actions: write on "
        "the repository and Contents: read for the artifact).")


# --------------------------------------------------------------------------
# the steps
# --------------------------------------------------------------------------
def dispatch(repo: str, ref: str, inputs: dict, token: str) -> None:
    api("POST", f"/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/dispatches",
        token, {"ref": ref, "inputs": inputs})


def default_branch(repo: str, token: str) -> str:
    return api("GET", f"/repos/{repo}", token).get("default_branch", "main")


def find_run(repo: str, note: str, not_before: float, token: str,
             timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while True:
        runs = api("GET", f"/repos/{repo}/actions/runs?event=workflow_dispatch&per_page=20",
                   token).get("workflow_runs", [])
        run = pick_run(runs, note, not_before)
        if run:
            return run
        if time.time() > deadline:
            raise SystemExit(
                f"see_screen: dispatched, but no run appeared within {int(timeout)}s.\n"
                f"  Check https://github.com/{repo}/actions/workflows/{WORKFLOW_FILE}")
        time.sleep(5)


def wait_for_run(repo: str, run: dict, token: str, timeout: float,
                 report: bool = True) -> dict:
    started = time.time()
    last = ""
    while True:
        run = api("GET", f"/repos/{repo}/actions/runs/{run['id']}", token)
        state = run.get("conclusion") or run.get("status")
        if report and state != last:
            print(f"see_screen: run {run['id']} -> {state}  ({run['html_url']})")
            last = state
        if run.get("status") == "completed":
            return run
        if time.time() - started > timeout:
            raise SystemExit(f"see_screen: still running after {int(timeout)}s - "
                             f"watch it at {run['html_url']}")
        time.sleep(10)


def failed_steps(repo: str, run_id: int, token: str) -> list[str]:
    jobs = api("GET", f"/repos/{repo}/actions/runs/{run_id}/jobs", token).get("jobs", [])
    return [f"{job.get('name', '?')}: {step.get('name', '?')}"
            for job in jobs for step in job.get("steps", [])
            if step.get("conclusion") == "failure"]


def fetch_artifact(repo: str, run: dict, out: Path, token: str) -> list[Path]:
    artifacts = api("GET", f"/repos/{repo}/actions/runs/{run['id']}/artifacts",
                    token).get("artifacts", [])
    if not artifacts:
        raise SystemExit(f"see_screen: the run produced no artifact - {run['html_url']}")
    artifact = artifacts[0]
    blob = api("GET", f"/repos/{repo}/actions/artifacts/{artifact['id']}/zip",
               token, raw=True, timeout=180)
    archive = out / "artifact.zip"
    archive.write_bytes(blob)
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            target = (out / member).resolve()
            if out.resolve() in target.parents:  # no path escapes from a zip
                zf.extract(member, out)
    archive.unlink(missing_ok=True)
    return sorted(p for p in out.glob("*.png"))


def screen_dirs(out_root: Path, routes: list[str], fresh: bool) -> Path:
    """One directory per request, named so two requests never overwrite."""
    stem = "-".join(route_slug(r) for r in routes[:3]) + ("" if len(routes) <= 3 else "-more")
    index = 1
    while True:
        candidate = out_root / (stem if fresh and index == 1 else f"{stem}-{index}")
        if not candidate.exists() or not fresh:
            return candidate
        index += 1


def main(argv: list[str] | None = None, cwd: Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="see_screen.py",
        description="Capture app screens through CI and print the image paths.")
    parser.add_argument("--route", action="append", default=[],
                        help="app route to photograph, e.g. /settings (repeatable)")
    parser.add_argument("--repo", help="owner/name (default: the git origin remote)")
    parser.add_argument("--ref", help="branch to dispatch on (default: the default branch)")
    parser.add_argument("--viewport", dest="viewports",
                        help=f"comma separated WxH list (default {DEFAULT_VIEWPORTS})")
    parser.add_argument("--wait-ms", dest="wait_ms",
                        help=f"milliseconds to let the app settle (default {DEFAULT_WAIT_MS})")
    parser.add_argument("--dart-defines", dest="dart_defines",
                        help="compile-time defines, one KEY=VALUE per line")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"where to put the images (default {DEFAULT_OUT})")
    parser.add_argument("--token-file", help="file holding a GitHub token")
    parser.add_argument("--timeout", type=float, default=1500,
                        help="seconds to wait for the run (default 1500)")
    parser.add_argument("--no-wait", action="store_true",
                        help="dispatch and return immediately (prints the run URL)")
    parser.add_argument("--json", action="store_true", help="machine readable summary")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be dispatched, then stop")
    args = parser.parse_args(argv)

    cwd = cwd or Path.cwd()
    routes = [r.strip() for r in args.route if r.strip()] or ["/"]
    repo = args.repo or repo_slug(cwd)
    if not repo:
        raise SystemExit("see_screen: no --repo and no git origin remote to read one from")

    nonce = f"{int(time.time())}-{random.randint(1000, 9999)}"
    note = f"see {nonce} {' '.join(routes)}"
    inputs = build_inputs(routes, args, note)

    if args.dry_run:
        print(json.dumps({"repo": repo, "workflow": WORKFLOW_FILE, "inputs": inputs}, indent=2))
        return 0

    token = resolve_token(args.token_file)
    ref = args.ref or default_branch(repo, token)
    asked_at = time.time()
    dispatch(repo, ref, inputs, token)
    print(f"see_screen: asked {repo} to photograph {', '.join(routes)}")

    run = find_run(repo, note, asked_at, token)
    if args.no_wait:
        print(run["html_url"])
        return 0

    run = wait_for_run(repo, run, token, args.timeout)

    if run.get("conclusion") != "success":
        print(f"see_screen: the capture run ended as {run.get('conclusion')}")
        for step in failed_steps(repo, run["id"], token):
            print(f"  failed: {step}")
        print(f"  {run['html_url']}")
        print("  next: python3 tool/ci_watch.py   (prints the failing log lines)")
        return 1

    out = screen_dirs(Path(args.out), routes, fresh=True)
    out.mkdir(parents=True, exist_ok=True)
    images = fetch_artifact(repo, run, out, token)
    if not images:
        raise SystemExit(f"see_screen: no PNG in the artifact - {run['html_url']}")

    rows = summarise_manifest(out / "manifest.tsv")
    flat = [row for row in rows if row["colours"] is not None and row["colours"] <= FLAT_COLOUR_LIMIT]
    summary = {"repo": repo, "run": run["html_url"], "routes": routes,
               "out": str(out.resolve()),
               "images": [{"path": str(p.resolve()), "bytes": p.stat().st_size}
                          for p in images],
               "manifest": rows, "flat": [row["name"] for row in flat]}
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print(f"\nsee_screen: {len(images)} image(s) in {out.resolve()}")
    for row in rows:
        colours = "?" if row["colours"] is None else row["colours"]
        print(f"  {row['name']}.png  {row['route']}  {row['viewport']}  "
              f"{row['bytes'] // 1024} KB  {colours} colours")
    for image in images:
        print(f"  read this: {image.resolve()}")
    if flat:
        print("\nsee_screen: WARNING - these look flat (<= "
              f"{FLAT_COLOUR_LIMIT} colours), so the screen never painted:")
        for row in flat:
            print(f"  {row['name']} ({row['route']})")
        print("  Usually a platform-only plugin (camera, notifications) on web, or a "
              "route the app does not have. The build log in the run has the reason.")
    print("\nsee_screen: now open the image(s) listed above - do not guess what they show.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
