#!/usr/bin/env bash
# Install the flutter-builder agent pack into an existing Flutter repository.
#
#   curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.9.0/scripts/install-agent-pack.sh | bash
#
# What it installs (repository root, never touches anything else):
#   tool/preflight.py    Dart checks that need no Flutter SDK: dead code,
#                        unused optional constructor parameters, unused imports.
#                        Run it before every push; it catches the mistakes that
#                        most often turn a push red.
#   tool/ci_watch.py     Waits for GitHub Actions on a commit and prints the
#                        failing lines of the failed jobs. Standard library
#                        only, no `gh` required.
#   AGENTS.md            A playbook for AI agents: the one-change/one-push
#                        loop, the CI map, how to read CI cheaply, and the
#                        rules to keep. The text between the
#                        flutter-builder:agent-pack markers is maintained by
#                        this installer; everything else in the file is yours.
#
# This file is self-contained so it also works when streamed through
# curl | bash. It never adds GitHub secrets and never runs git.
set -euo pipefail

PACK_VERSION=v1.9.0
REPO=Keshab1997/flutter-builder
RAW_BASE="https://raw.githubusercontent.com/${REPO}/${PACK_VERSION}"

say()  { printf '[agent-pack] %s\n' "$*"; }
fail() { printf '[agent-pack] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'HELP'
Install the flutter-builder agent pack (tool/preflight.py, tool/ci_watch.py and
a managed AGENTS.md block) into a Flutter repository. No Flutter SDK needed.

Run from anywhere inside the repository:
  curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.9.0/scripts/install-agent-pack.sh | bash

Options when running a downloaded/local script:
  --dry-run   Show what would change without writing anything
  --force     Replace differing tool/preflight.py or tool/ci_watch.py
              (originals are backed up first)
  -h, --help  Show this help

AGENTS.md is always merged, never replaced: the managed block between the
flutter-builder:agent-pack markers is updated in place and every other line of
the file stays exactly as it is.
HELP
}

force=false
dry_run=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --force) force=true; shift ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1 (try --help)." ;;
  esac
done

command -v python3 >/dev/null 2>&1 || fail "python3 not found (the pack's tools need python3 >= 3.8)."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' \
  || fail "python3 is too old: $(python3 -V 2>&1)"

invoked_from="$(pwd -P)"
repo_root="$invoked_from"
if command -v git >/dev/null 2>&1 && git -C "$invoked_from" rev-parse --show-toplevel >/dev/null 2>&1; then
  repo_root="$(git -C "$invoked_from" rev-parse --show-toplevel)"
  repo_root="$(cd -- "$repo_root" && pwd -P)"
fi

# The app name only lands in a markdown heading; refuse anything that could
# look like a GitHub expression and fall back to a neutral label otherwise.
app_name=''
if [ -f "$repo_root/pubspec.yaml" ]; then
  app_name="$(sed -n 's/^name:[[:space:]]*\([A-Za-z0-9._-]*\).*$/\1/p' "$repo_root/pubspec.yaml" | head -n 1)"
fi
if [ -z "$app_name" ]; then
  app_name="$(basename -- "$repo_root")"
fi
case "$app_name" in
  ''|*'${{'*|*\$*|*[!A-Za-z0-9._-]*) app_name='this project' ;;
esac

# Never write through symlinks, and never create a tool/ that is not a real dir.
[ ! -L "$repo_root/AGENTS.md" ] || fail "AGENTS.md is a symlink; refusing to write through it."
[ ! -e "$repo_root/AGENTS.md" ] || [ -f "$repo_root/AGENTS.md" ] || fail "AGENTS.md exists but is not a regular file."
[ ! -L "$repo_root/tool" ] || fail "tool/ is a symlink; refusing to write through it."
[ ! -e "$repo_root/tool" ] || [ -d "$repo_root/tool" ] || fail "tool/ exists but is not a directory."
for name in preflight.py ci_watch.py; do
  [ ! -L "$repo_root/tool/$name" ] || fail "tool/$name is a symlink; refusing to replace it."
  [ ! -e "$repo_root/tool/$name" ] || [ -f "$repo_root/tool/$name" ] || fail "tool/$name exists but is not a regular file."
done

say "Repository: $repo_root"
say "App name:   $app_name"
say "Pack:       $PACK_VERSION"

stage="$(mktemp -d)"
trap 'rm -rf -- "$stage"' EXIT

# Payload. Quoted heredocs keep GitHub's ${{ }} out of bash's hands, and they
# keep this script self-contained for the curl | bash path.
cat > "$stage/preflight.py" <<'AGENT_PACK_PREFLIGHT_PY_EOF'
#!/usr/bin/env python3
"""preflight.py - fast Dart sanity checks that need no Flutter SDK.

A repo sandbox usually has no Flutter SDK, so an agent cannot run the same
`flutter analyze` the CI runs. Pushing a guess costs one full CI round
(2+ minutes); this script costs a second and catches the mistakes that send
most small pushes red:

  * unused_element_parameter - an optional named parameter of a private class
    that no call site passes any more. Deleting the one place that used a
    private widget's `footer:` slot leaves this behind, and the shared CI runs
    `flutter analyze --fatal-infos`, so the push fails on a warning.
  * unused_element - a private class / function nothing references any more
    (the widget you "forgot" to delete after removing its only user).
  * unused_import - `import '...' as alias;` where `alias.` is gone, and
    `show X` names that are never used.

It is intentionally heuristic: it reads the file as text, blanks comments and
string literals, and never executes Dart. It will not catch type errors,
lints, or anything in generated code. It is a pre-push smoke check, not a
replacement for CI - CI remains the single source of truth.

Usage:
    python3 tool/preflight.py              # checks lib/ and test/
    python3 tool/preflight.py lib test     # explicit paths
    python3 tool/preflight.py lib/foo.dart # a single file

Exit code 0 when clean, 1 when something is reported (advisory, not fatal to
your workflow - fix or justify, then push).
"""
from __future__ import annotations

import pathlib
import re
import sys

# Comments and string literals are blanked before any matching so that a class
# name inside a doc comment cannot count as a use of it. Line numbers survive.
COMMENT_OR_STRING = re.compile(
    r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'", re.S)

# Return types this script bothers to look at for private functions. Dart has
# more, but a miss here only means one fewer advisory line.
FUNCTION_RE = re.compile(
    r"(?m)^[ \t]*(?:static\s+)?(?:Future<[^>]*>|void|int|double|bool|String|"
    r"Widget|List<[^>]*>|Map<[^>]*>|[A-Z]\w*(?:<[^>]*>)?\??)\s+(_\w+)\s*\(")

IMPORT_RE = re.compile(
    r"(?m)^\s*import\s+'([^']+)'\s*(?:as\s+(\w+))?\s*(?:show\s+([^;]+))?;")


def blanked(src: str) -> str:
    """Replace comments and string literals with spaces, keeping line breaks."""
    return COMMENT_OR_STRING.sub(
        lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)


def line_of(text: str, index: int) -> int:
    return text[:index].count("\n") + 1


def balanced(text: str, start: int) -> str:
    """Contents of the parenthesised group that opens at `start`."""
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    return text[start + 1:]


def split_params(params: str) -> list[str]:
    """Split a parameter list on top-level commas only."""
    out: list[str] = []
    depth, cur = 0, ""
    for ch in params:
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def named_section(params: str) -> str | None:
    """Text inside the outermost { } of a parameter list, if there is one."""
    depth, start = 0, None
    for i, ch in enumerate(params):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return params[start + 1:i]
    return None


def optional_named_params(params: str) -> list[str]:
    """Optional NAMED parameters only.

    `this.x` in the positional part of a constructor is required-positional;
    the analyzer never reports unused_element_parameter for those, so neither
    does this script.
    """
    section = named_section(params)
    if section is None:
        return []
    names: list[str] = []
    for p in split_params(section):
        if not p or p.startswith("@") or "required" in p:
            continue
        m = re.search(r"\bthis\.(\w+)", p)
        if m:
            names.append(m.group(1))
            continue
        m = re.search(r"([A-Za-z_]\w*)\s*(?:=|$)", p)
        if m:
            names.append(m.group(1))
    return names


def check_private_classes(path: pathlib.Path, text: str) -> list[str]:
    problems: list[str] = []
    for cm in re.finditer(r"\bclass\s+(_\w+)", text):
        cls = cm.group(1)
        spans = [cm.span()]

        ctor = re.search(
            rf"(?:const\s+)?{re.escape(cls)}\((?P<p>.*?)\)\s*(?:[:{{;]|=>)",
            text[cm.end():], re.S)
        params = ""
        if ctor:
            spans.append((cm.end() + ctor.start(), cm.end() + ctor.end()))
            params = ctor.group("p")

        refs = [m for m in re.finditer(rf"\b{re.escape(cls)}\b", text)
                if not any(a <= m.start() < b for a, b in spans)]
        if not refs:
            problems.append(f"{path}:{line_of(text, cm.start())}: private class "
                            f"{cls} is never used (unused_element)")
            continue

        sites = [m for m in re.finditer(rf"\b{re.escape(cls)}\s*\(", text)
                 if not any(a <= m.start() < b for a, b in spans)]
        if not sites:
            continue
        passed: set[str] = set()
        for m in sites:
            passed |= set(re.findall(r"(?:^|[,{])\s*(\w+)\s*:",
                                     balanced(text, m.end() - 1)))
        for name in optional_named_params(params):
            if name not in passed:
                problems.append(
                    f"{path}:{line_of(text, cm.start())}: optional parameter "
                    f"'{name}' of {cls} is never passed (unused_element_parameter)")
    return problems


def check_private_functions(path: pathlib.Path, text: str) -> list[str]:
    problems: list[str] = []
    for fm in FUNCTION_RE.finditer(text):
        fn = fm.group(1)
        depth, params_close = 1, None
        for i, ch in enumerate(text[fm.end():]):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    params_close = i
                    break
        if params_close is None:
            continue
        after = text[fm.end() + params_close:]
        if not re.match(r"\s*(?:async\s*)?\{", after):
            continue  # abstract / declaration only, not a definition
        body_start = fm.end() + params_close
        if not re.search(rf"\b{re.escape(fn)}\b", text[body_start:]):
            problems.append(f"{path}:{line_of(text, fm.start())}: private "
                            f"function {fn} is never used (unused_element)")
    return problems


def check_imports(path: pathlib.Path, text: str) -> list[str]:
    problems: list[str] = []
    for im in IMPORT_RE.finditer(text):
        line = line_of(text, im.start())
        alias, shown = im.group(2), im.group(3)
        if alias and not re.search(rf"\b{re.escape(alias)}\s*\.", text):
            problems.append(f"{path}:{line}: import alias '{alias}' is unused "
                            f"(unused_import)")
        if shown:
            for name in (n.strip() for n in shown.split(",")):
                if name and len(re.findall(rf"\b{re.escape(name)}\b", text)) < 2:
                    problems.append(f"{path}:{line}: '{name}' shown in import "
                                    f"but unused (unused_import)")
    return problems


def check_file(path: pathlib.Path) -> list[str]:
    text = blanked(path.read_text(errors="replace"))
    return (check_private_classes(path, text)
            + check_private_functions(path, text)
            + check_imports(path, text))


def collect(roots: list[str]) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in roots:
        p = pathlib.Path(root)
        if p.is_dir():
            files += sorted(p.rglob("*.dart"))
        elif p.suffix == ".dart" and p.exists():
            files.append(p)
    return files


def main(argv: list[str]) -> int:
    files = collect(argv[1:] or ["lib", "test"])
    problems: list[str] = []
    for f in files:
        problems += check_file(f)
    for line in problems:
        print(line)
    print(f"\npreflight: {len(files)} file(s) checked, {len(problems)} issue(s)")
    if problems:
        print("These would likely fail `flutter analyze --fatal-infos` in CI.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
AGENT_PACK_PREFLIGHT_PY_EOF

cat > "$stage/ci_watch.py" <<'AGENT_PACK_CI_WATCH_PY_EOF'
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
AGENT_PACK_CI_WATCH_PY_EOF

cat > "$stage/agents-template.md" <<'AGENT_PACK_AGENTS_MD_EOF'
# AGENTS.md — {{APP_NAME}}

Playbook for AI agents working in this repository. Read it once at the start of
a session: everything here exists to keep one change loop short.

<!-- flutter-builder:agent-pack:start v1.9.0 -->
## Rule #1 — CI verifies, you never push a guess

This sandbox usually has **no Flutter SDK**, and even when it does, the local
result would not match CI (SDK pin, Android SDK, Firebase secrets). So:

- Do **not** run `flutter test`, `flutter analyze`, `flutter build`,
  `dart analyze` or `gradlew` locally to "check quickly".
- Use the two zero-dependency tools in `tool/` instead — they are seconds, not
  minutes, and they catch the mistakes that actually turn pushes red.
- **CI is the single source of truth.** Read its result before calling a change
  done; a local impression is never verification.

```bash
python3 tool/preflight.py     # before pushing: dead code / unused params / unused imports
python3 tool/ci_watch.py      # after pushing: waits for CI, prints the failing lines
```

## The fast loop — one change, one push, one CI round

1. **Edit** the smallest diff that does one thing.
2. **`python3 tool/preflight.py`** — 1 second, no SDK. Fix what it reports.
3. **Commit.** While the branch is still yours, `git commit --amend` instead of
   piling "fix ci" commits on top.
4. **Push once.** Never push WIP "to see what happens". If you have several
   things to try, open the PR as a **draft** — drafts do not run CI, so iterate
   freely; mark *Ready for review* when you want the run.
5. **`python3 tool/ci_watch.py`** — it polls for you (no turn-by-turn waiting)
   and prints the conclusion of every workflow plus the interesting lines of
   the failed ones.
6. **Red?** Fix → `git commit --amend` → `git push --force-with-lease` →
   watch again. One more round, not five.

Rules of thumb: ten 30-second pushes waste more time than one 3-minute CI run.
Read the CI log before editing; guessing at a red build doubles the rounds.

## What a push costs here (and why it is already cheap)

| Situation | What runs |
|---|---|
| Push to a feature branch **with an open PR** | the PR event only — the push trigger is main-only, so no duplicate |
| Push to `main` | CI (+ Web Preview) once |
| **Draft** PR | nothing, until you press *Ready for review* |
| Docs-only change (`**.md`, `docs/**`, `distribution/**`) | nothing (excluded by `paths-ignore`) |
| Merge | CI on `main` + Web Preview deploy |

If a run is cancelled or skipped, do **not** retrigger it with an empty commit —
use *Actions → Run workflow* or the re-run API call.

## CI map

| Workflow | Runs when | What it does |
|---|---|---|
| `ci.yml` → shared `flutter-build.yml` | push to main, PRs | `dart format` check → `flutter analyze --fatal-infos` → `flutter test` + coverage |
| `web-preview.yml` | push to main, PRs | builds the web app, deploys `preview/<branch>/` to GitHub Pages (a branch delete removes its preview) |
| `manual-build.yml` | manual dispatch | APK / AAB artifact |
| `publish-release.yml` | manual dispatch | signed build → tag → GitHub Release (+ Play internal if configured) |
| `release.yml` | `v*` tag push | signed AAB artifact for the tag |

The reusable workflows are pinned by tag; bump the pin in one place
(`.github/workflows/*.yml`) and every project picks the change up.

## Reading CI without wasting a turn

```bash
python3 tool/ci_watch.py                       # HEAD commit, waits, prints failures
python3 tool/ci_watch.py --branch main         # newest runs of a branch
python3 tool/ci_watch.py --once                # no waiting: current state only
python3 tool/ci_watch.py --sha <sha>           # a specific commit
python3 tool/ci_watch.py --token-file secrets/gh_token.txt
```

Token order: `--token-file`, then `$GITHUB_TOKEN` / `$GH_TOKEN`, then `gh auth
token`. Never print a token, and never paste one into a log or a commit.

Raw API equivalents, if you need them:

```bash
GET /repos/{owner}/{repo}/actions/runs?head_sha=<sha>     # run list + conclusions
GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs      # failing job and step
GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs      # plain-text log
```

The log endpoint answers with a **302 to blob storage**; the pre-signed URL
rejects a request that still carries the `Authorization` header
(`InvalidAuthenticationInfo`), so strip it on redirect — `ci_watch.py` does.

## Working rules

- **Small, focused diffs.** One concern per commit; conventional commit
  messages (`fix(profile): …`, `feat(cv): …`, `chore(ci): …`).
- **Branch + PR** for anything non-trivial; keep the branch name descriptive.
  Docs-only fixes may go straight to `main` when the project allows it.
- **Merge only when green.** Delete the branch after merging — the preview
  cleanup runs automatically.
- **Secrets never enter git:** `google-services.json`, `android/key.properties`,
  `*.jks` / `*.keystore`, `.pem`, tokens. CI receives them from repository
  secrets. Do not add them to the repo to "make CI pass".
- **Respect existing structure:** edit existing files over adding new ones, and
  read the file you are about to change (comments explain *why* the code is the
  way it is — keep that voice).

## Ask the human before

- merging to `main` (when the project wants review), **tagging a release**, or
  touching workflows / secrets / repository settings;
- force-pushing a branch you do not own, rewriting published history, or
  deleting branches, tags, or repository content;
- anything that publishes publicly, spends money, or is irreversible.

<!-- flutter-builder:agent-pack:end -->

## Project notes — edit freely

Everything above the end marker is maintained by
`scripts/install-agent-pack.sh` (re-run the one-liner to update it; your text
down here is never touched).

- **App:** {{APP_NAME}} — one line about what it does.
- **App directory:** `.` (change this line if the Flutter app lives in a
  subdirectory).
- **Extra project rules:** _(fill in: invariants, store metadata that must stay
  in sync, screenshots that must be regenerated, …)_
- **Extra verification:** _(fill in: anything CI cannot see — copy changes,
  Play Console steps, manual checks …)_
AGENT_PACK_AGENTS_MD_EOF

changes=()
conflicts=()
for name in preflight.py ci_watch.py; do
  dest="$repo_root/tool/$name"
  if [ -e "$dest" ]; then
    if cmp -s "$stage/$name" "$dest"; then
      say "Already current: tool/$name"
      continue
    fi
    conflicts+=("$name")
    if [ "$force" = true ]; then
      say "Will replace (backup first): tool/$name"
    else
      say "CONFLICT (left untouched): tool/$name"
    fi
  else
    say "Will add: tool/$name"
  fi
  changes+=("$name")
done

if [ "${#conflicts[@]}" -gt 0 ] && [ "$force" = false ]; then
  fail "Existing tool file(s) differ; nothing was changed. Review them, or rerun with --force to back them up and replace them."
fi

# The AGENTS.md decision comes from the same python that performs the merge, so
# --dry-run and the real run always agree.
agents_action="$(python3 - "$stage/agents-template.md" "$repo_root/AGENTS.md" "$app_name" "$dry_run" <<'AGENT_PACK_MERGE_PY_EOF'
import pathlib, sys

template_path, target_path, app_name, dry = sys.argv[1:5]
start = "<!-- flutter-builder:agent-pack:start"
end = "<!-- flutter-builder:agent-pack:end -->"

template = pathlib.Path(template_path).read_text(encoding="utf-8").replace("{{APP_NAME}}", app_name)
# Three parts: the title/intro above the managed block (head), the managed
# block itself (markers included), and the project notes below it.
head = template[:template.index(start)].rstrip("\n")
block_end = template.index(end) + len(end)
block = template[template.index(start):block_end].rstrip("\n") + "\n"
notes = template[block_end:].lstrip("\n")

target = pathlib.Path(target_path)
if not target.exists():
    new = head + "\n\n" + block + "\n" + notes
    action = "created"
else:
    text = target.read_text(encoding="utf-8")
    if start in text and end in text:
        i, j = text.index(start), text.index(end) + len(end)
        tail = text[j:]
        new = text[:i].rstrip("\n") + "\n\n" + block + "\n" + (tail.lstrip("\n") or notes)
    else:
        # First install into a file that already has content: keep every line,
        # put the managed block right below the first H1 when there is one.
        lines = text.splitlines(keepends=True)
        idx = next((k for k, line in enumerate(lines) if line.startswith("# ")), None)
        if idx is None:
            new = head + "\n\n" + block + "\n" + text.lstrip("\n")
        else:
            new = "".join(lines[:idx + 1]) + "\n" + block + "\n" + "".join(lines[idx + 1:]).lstrip("\n")
    action = "unchanged" if new == text else "updated"

if action != "unchanged" and dry != "true":
    target.write_text(new, encoding="utf-8")
print(action)
AGENT_PACK_MERGE_PY_EOF
)"

case "$agents_action" in
  created) say "Will add: AGENTS.md" ;;
  updated) say "Will update (managed block): AGENTS.md" ;;
  unchanged) say "Already current: AGENTS.md" ;;
  *) fail "internal error: unexpected AGENTS.md action '$agents_action'." ;;
esac

if [ "${#changes[@]}" -eq 0 ] && [ "$agents_action" = "unchanged" ]; then
  say "Agent pack $PACK_VERSION is already installed; nothing changed."
  exit 0
fi

if [ "$dry_run" = true ]; then
  say "Dry run: no files were changed."
  exit 0
fi

if [ "${#conflicts[@]}" -gt 0 ]; then
  backups="$repo_root/.agent-pack-backups"
  [ ! -L "$backups" ] || fail "$backups is a symlink; refusing to write through it."
  [ ! -e "$backups" ] || [ -d "$backups" ] || fail "$backups is not a directory."
  mkdir -p -- "$backups"
  backup_dir="$(mktemp -d "$backups/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXXXX")"
  for name in "${conflicts[@]}"; do
    cp -p -- "$repo_root/tool/$name" "$backup_dir/$name"
  done
  say "Originals backed up to: $backup_dir"
fi

mkdir -p -- "$repo_root/tool"
for name in "${changes[@]}"; do
  # Write through a temporary file in the destination directory so an
  # interrupted run cannot leave half a script behind.
  (
    temp="$(mktemp "$repo_root/tool/.$name.tmp.XXXXXX")"
    trap 'rm -f -- "$temp"' EXIT
    cp -- "$stage/$name" "$temp"
    chmod 644 "$temp"
    mv -f -- "$temp" "$repo_root/tool/$name"
  )
  say "Installed: tool/$name"
done

if [ "$agents_action" != "unchanged" ]; then
  say "Installed: AGENTS.md ($agents_action)"
fi

say "Done. Review the changes, then commit tool/ and AGENTS.md."
say "  Before a push :  python3 tool/preflight.py"
say "  After a push  :  python3 tool/ci_watch.py"
say "  Pack docs     :  ${RAW_BASE}/README.md"
if [ ! -e "$repo_root/.agent-pack-backups" ]; then
  :
else
  say "Note: .agent-pack-backups/ holds replaced files; add it to .gitignore."
fi
