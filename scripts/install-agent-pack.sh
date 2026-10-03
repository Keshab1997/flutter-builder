#!/usr/bin/env bash
# Install the flutter-builder agent pack into an existing Flutter repository.
#
#   curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.12.1/scripts/install-agent-pack.sh | bash
#
# What it installs (repository root, never touches anything else):
#   tool/preflight.py    Dart checks that need no Flutter SDK: dead code,
#                        unused optional constructor parameters, unused imports.
#                        Run it before every push; it catches the mistakes that
#                        most often turn a push red.
#   tool/ci_watch.py     Waits for GitHub Actions on a commit and prints the
#                        failing lines of the failed jobs. Standard library
#                        only, no `gh` required.
#   tool/see_screen.py   Have CI photograph a screen and print the image paths,
#                        so an agent can look at what it changed.
#   tool/agent_loop.py   One command for the whole loop: preflight, secret
#                        guard, commit, push, watch. Refuses to commit on the
#                        default branch or to stage a credential, so an agent
#                        cannot skip a step by accident.
#   AGENTS.md            A playbook for AI agents: the one-change/one-push
#                        loop, the CI map, how to read CI cheaply, and the
#                        rules to keep. The text between the
#                        flutter-builder:agent-pack markers is maintained by
#                        this installer; everything else in the file is yours.
#
# This file is self-contained so it also works when streamed through
# curl | bash. It never adds GitHub secrets and never runs git.
set -euo pipefail

PACK_VERSION=v1.12.1
REPO=Keshab1997/flutter-builder
RAW_BASE="https://raw.githubusercontent.com/${REPO}/${PACK_VERSION}"

say()  { printf '[agent-pack] %s\n' "$*"; }
fail() { printf '[agent-pack] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'HELP'
Install the flutter-builder agent pack (tool/preflight.py, tool/ci_watch.py,
tool/agent_loop.py, tool/see_screen.py and a managed AGENTS.md block) into a Flutter repository.
No Flutter SDK needed.

Run from anywhere inside the repository:
  curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.12.1/scripts/install-agent-pack.sh | bash

Options when running a downloaded/local script:
  --dry-run   Show what would change without writing anything
  --force     Replace any differing tool/*.py from the pack
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
for name in preflight.py ci_watch.py agent_loop.py see_screen.py; do
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
  * avoid_print - `print(...)` left in code that ships; the lint is in
    flutter_lints and `--fatal-infos` turns it into a red step.
  * unused_field / unused_local_variable - a private name declared once and
    never mentioned again in its file.
  * orphan files and ambiguous imports - a lib/ file nothing imports any more
    (an extracted widget that was never wired up), and a file importing two
    libraries that both declare the same top-level name. Neither is visible to
    the per-file checks above, and both waste a CI round.

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

# Comments only; `blanked()` also removes string literals and is therefore
# unusable for import scanning. See without_comments().
COMMENT_ONLY = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def blanked(src: str) -> str:
    """Replace comments and string literals with spaces, keeping line breaks."""
    return COMMENT_OR_STRING.sub(
        lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)


def without_comments(src: str) -> str:
    """Blank comments only - string literals survive.

    `blanked()` above is right for anything that must not match a name inside a
    doc comment or a literal, but it also erases the path inside
    `import 'package:app/x.dart';`, which is why the import checks need this
    variant. (They used to run on `blanked()` text and could never match - the
    unused-import check was dead code for that reason.)
    """
    return COMMENT_ONLY.sub(
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


def check_prints(path: pathlib.Path, text: str, is_test: bool) -> list[str]:
    """`print(` in code that ships; the lint is avoid_print.

    Skipped for test/ (printing in a test is normal). `debugPrint(` does not
    match: the pattern demands a non-word, non-dot character before `print`.
    """
    if is_test:
        return []
    return [f"{path}:{line_of(text, m.start())}: print() in code that ships "
            f"(avoid_print)"
            for m in re.finditer(r"(?<![\w.])print\s*\(", text)]


def check_private_fields(path: pathlib.Path, raw: str, text: str) -> list[str]:
    """A private name that is declared and never mentioned again.

    Uses are counted in the raw source, so a use inside a string interpolation
    (`'$_count'`) still counts, while the declaration is looked up in the
    blanked source so commented-out code cannot report a field. Requiring the
    name to appear exactly once keeps false positives out: a field, getter or
    local that is used anywhere has a second occurrence.
    """
    decl = re.compile(
        r"(?m)^[ \t]+(?:static\s+)?(?:late\s+)?(?:final\s+)?(?:const\s+)?"
        r"[A-Za-z_][\w<>,.?\s]*?\s+(_\w+)\s*(?:=|;|\{)")
    problems: list[str] = []
    seen: set[str] = set()
    for m in decl.finditer(text):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        if len(re.findall(rf"\b{re.escape(name)}\b", raw)) < 2:
            problems.append(
                f"{path}:{line_of(text, m.start())}: private member '{name}' is "
                f"declared but never used again "
                f"(unused_field / unused_local_variable)")
    return problems


IMPORT_OR_EXPORT_RE = re.compile(r"(?m)^\s*(?:import|export)\s+'([^']+)'")
DECL_RE = re.compile(r"(?m)^\s*(?:abstract\s+)?(?:class|enum|mixin|"
                     r"extension|typedef)\s+([A-Z]\w*)")


def resolve_target(source: pathlib.Path, spec: str,
                   package_name: str | None) -> pathlib.Path | None:
    """Map an import/export URI onto a file in this repository, or None."""
    if spec.startswith("dart:"):
        return None
    if spec.startswith("package:"):
        head, _, rest = spec[len("package:"):].partition("/")
        return pathlib.Path("lib") / rest if package_name == head else None
    return source.parent / spec


def check_cross_file(files: list[pathlib.Path], decl_texts: dict,
                     code_texts: dict, package_name: str | None,
                     cwd: pathlib.Path) -> list[str]:
    """Orphan files, ambiguous imports, duplicate declarations.

    Ambiguity is reported only when one file really imports two libraries that
    declare the same public name - the same name in two unrelated files is
    legal Dart and stays silent.
    """
    problems: list[str] = []

    def key(p: pathlib.Path) -> str:
        try:
            return str((cwd / p).resolve())
        except OSError:
            return str(cwd / p)

    declared: dict[pathlib.Path, dict[str, int]] = {}
    referenced: set[str] = set()
    for path in files:
        declared[path] = {m.group(1): line_of(decl_texts[path], m.start())
                          for m in DECL_RE.finditer(decl_texts[path])}
        for m in IMPORT_OR_EXPORT_RE.finditer(code_texts[path]):
            target = resolve_target(path, m.group(1), package_name)
            if target is not None:
                referenced.add(key(target))

    # Orphans: only meaningful once something in the tree refers to something
    # else, so a brand-new single-file project is never nagged.
    if referenced:
        for path in files:
            if pathlib.PurePosixPath(path.as_posix()).parts[:1] != ("lib",):
                continue
            if path.name == "main.dart" or "part of" in code_texts[path]:
                continue
            if declared[path] and key(path) not in referenced:
                problems.append(f"{path}: no file imports or exports this one "
                                f"(orphan file - wire it up or delete it)")

    for path in files:
        providers: dict[str, list[pathlib.Path]] = {}
        for m in IMPORT_OR_EXPORT_RE.finditer(code_texts[path]):
            target = resolve_target(path, m.group(1), package_name)
            if target is None or key(target) == key(path):
                continue
            for other in files:
                if key(other) != key(target):
                    continue
                for name in declared[other]:
                    bucket = providers.setdefault(name, [])
                    if all(key(o) != key(other) for o in bucket):
                        bucket.append(other)
        for name, sources in providers.items():
            if len(sources) > 1:
                where = " and ".join(f"{s}:{declared[s][name]}" for s in sources)
                problems.append(f"{path}: '{name}' is declared in {where}, and "
                                f"this file imports both (ambiguous_import)")

    for path, names in declared.items():
        for name, first_line in names.items():
            if len(re.findall(rf"(?m)^\s*(?:abstract\s+)?(?:class|enum|mixin|"
                              rf"extension|typedef)\s+{re.escape(name)}\b",
                              decl_texts[path])) > 1:
                problems.append(f"{path}:{first_line}: '{name}' is declared more "
                                f"than once in this file (duplicate_definition)")
    return problems


def package_name(cwd: pathlib.Path) -> str | None:
    """`name:` from pubspec.yaml, needed to resolve package: imports."""
    try:
        for line in (cwd / "pubspec.yaml").read_text(encoding="utf-8").splitlines():
            m = re.match(r"^name:\s*([A-Za-z0-9_]+)\s*$", line)
            if m:
                return m.group(1)
    except OSError:
        return None
    return None


def check_file(path: pathlib.Path) -> list[str]:
    raw = path.read_text(errors="replace")
    text = blanked(raw)
    code = without_comments(raw)
    return (check_private_classes(path, text)
            + check_private_functions(path, text)
            + check_imports(path, code)
            + check_prints(path, text, is_test="test" in path.parts)
            + check_private_fields(path, raw, text))


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
    decl_texts: dict[pathlib.Path, str] = {}
    code_texts: dict[pathlib.Path, str] = {}
    for f in files:
        problems += check_file(f)
        raw = f.read_text(errors="replace")
        decl_texts[f] = blanked(raw)
        code_texts[f] = without_comments(raw)
    if len(files) > 1:
        problems += check_cross_file(files, decl_texts, code_texts,
                                     package_name(pathlib.Path.cwd()),
                                     pathlib.Path.cwd())
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

cat > "$stage/agent_loop.py" <<'AGENT_PACK_AGENT_LOOP_PY_EOF'
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
AGENT_PACK_AGENT_LOOP_PY_EOF

cat > "$stage/see_screen.py" <<'AGENT_PACK_SEE_SCREEN_PY_EOF'
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
AGENT_PACK_SEE_SCREEN_PY_EOF

cat > "$stage/agents-template.md" <<'AGENT_PACK_AGENTS_MD_EOF'
# AGENTS.md — {{APP_NAME}}

Playbook for AI agents working in this repository. Read it once at the start of
a session: everything here exists to keep one change loop short.

<!-- flutter-builder:agent-pack:start v1.12.1 -->
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
python3 tool/agent_loop.py -m "fix(scope): what changed"   # all five steps, one call
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

### The same loop as one command

`tool/agent_loop.py` performs steps 2-5 in a single call, and stops before the
first thing that would waste a run:

```bash
python3 tool/agent_loop.py -m "fix(profile): guard a null avatar"
python3 tool/agent_loop.py -m "fix(profile): drop the unused import" --amend
python3 tool/agent_loop.py -m "feat(cv): add PDF export" --draft-pr
python3 tool/agent_loop.py -m "..." --ready          # drafts run no CI: this starts it
python3 tool/agent_loop.py -m "..." --no-watch       # push and return immediately
```

It refuses, before touching the repository, when

- HEAD is the default branch (`main`/`master`) — use a branch, or `--allow-main`
  when the project really works that way;
- a staged file looks like a credential (`.env`, `*.jks`, `*.keystore`, `*.pem`,
  `key.properties`, `google-services.json`, `secrets/**`, …) — a refusal costs
  one edit, a leaked keystore costs a rotation;
- `preflight.py` reports anything — use `--no-preflight` only when the findings
  are deliberate.

Exit codes: `0` pushed (and green when watched), `1` CI red or push failed,
`2` refused before changing anything. An `--amend` push uses
`--force-with-lease`, never a bare `--force`.

## Seeing a screen — look, do not guess

You cannot run the app, but you can *see* it. `tool/see_screen.py` asks CI to
build the app for web and photograph the routes you name, waits for the run,
downloads the images and prints their paths. Then open them — with your image
tool, not your imagination:

```bash
python3 tool/see_screen.py --route /settings           # one screen
python3 tool/see_screen.py --route / --route /profile  # several, one build
python3 tool/see_screen.py --route /settings --wait-ms 12000   # slow first frame
```

* **Use it before and after a UI change.** Before: see what the screen looks
  like now. After: see what your change did. A green CI says the code compiles;
  only the picture says the layout is right.
* The routes are the app's own (`/settings`, `/profile`) — the same names the
  app navigates to. A screen behind a login or several taps cannot be reached
  this way; ask the human for a screenshot of that one instead.
* It is the **web** build: layout, colours and text are faithful; fonts and
  platform widgets differ, and camera/bluetooth/notification plugins render as a
  blank screen. The script says so when the pixels are flat — believe it rather
  than "fixing" the capture.
* `--out` defaults to `.agent-screens/` (git-ignored). The images are throwaway
  artifacts: never commit them, and never use one as a test fixture.
* No token? `gh auth login` once, or pass `--token-file`.

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
for name in preflight.py ci_watch.py agent_loop.py see_screen.py; do
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
say "  Whole loop    :  python3 tool/agent_loop.py -m \"fix(x): what changed\""
say "  Pack docs     :  ${RAW_BASE}/README.md"
if [ ! -e "$repo_root/.agent-pack-backups" ]; then
  :
else
  say "Note: .agent-pack-backups/ holds replaced files; add it to .gitignore."
fi
