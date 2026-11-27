#!/usr/bin/env bash
# Install the flutter-builder agent pack into an existing Flutter repository.
#
#   curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.18.9/scripts/install-agent-pack.sh | bash
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
#   tool/agent_loop.py   One command for the whole loop: preflight, artifact
#                        and secret guard, commit, push, watch. Refuses to
#                        stage a credential or the pack's screenshot/backup
#                        artifacts, so an agent cannot skip a step by accident.
#   tool/local_screenshots.py
#                        Photographs a screen: renders it to a PNG with
#                        `flutter test`, offline, about a second per screen. No
#                        CI run, no device, no emulator.
#   tool/screenshots/shot_framework.dart, shot_runner_test.dart
#                        The harness the CLI drives: a project-agnostic frame
#                        plus the golden runner test. Replaced when the pack
#                        updates, so fixes belong upstream.
#   tool/screenshots/shot_registry.dart
#                        YOUR file: which screens to photograph and how to
#                        dress them (theme, fonts, native mocks). Written once,
#                        then never replaced - not even with --force.
#   AGENTS.md            A playbook for AI agents: the one-change/one-push
#                        loop, the CI map, how to read CI cheaply, and the
#                        rules to keep. The text between the
#                        flutter-builder:agent-pack markers is maintained by
#                        this installer; everything else in the file is yours.
#
# This file is self-contained so it also works when streamed through
# curl | bash. It never adds GitHub secrets and never runs git.
set -euo pipefail

PACK_VERSION=v1.18.9
REPO=Keshab1997/flutter-builder
RAW_BASE="https://raw.githubusercontent.com/${REPO}/${PACK_VERSION}"

say()  { printf '[agent-pack] %s\n' "$*"; }
fail() { printf '[agent-pack] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'HELP'
Install the flutter-builder agent pack (tool/preflight.py, tool/ci_watch.py,
tool/agent_loop.py, tool/see_screen.py, tool/local_screenshots.py, the
tool/screenshots/ harness and a managed AGENTS.md block) into a Flutter
repository. No Flutter SDK needed to install.

Run from anywhere inside the repository:
  curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.18.9/scripts/install-agent-pack.sh | bash

Options when running a downloaded/local script:
  --dry-run   Show what would change without writing anything
  --force     Replace any differing tool/*.py or tool/screenshots/*.dart from
              the pack (originals are backed up first). Your
              tool/screenshots/shot_registry.dart is never replaced.
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
for name in preflight.py ci_watch.py agent_loop.py see_screen.py local_screenshots.py; do
  [ ! -L "$repo_root/tool/$name" ] || fail "tool/$name is a symlink; refusing to replace it."
  [ ! -e "$repo_root/tool/$name" ] || [ -f "$repo_root/tool/$name" ] || fail "tool/$name exists but is not a regular file."
done
[ ! -L "$repo_root/tool/screenshots" ] || fail "tool/screenshots is a symlink; refusing to write through it."
[ ! -e "$repo_root/tool/screenshots" ] || [ -d "$repo_root/tool/screenshots" ] || fail "tool/screenshots exists but is not a directory."
for name in shot_framework.dart shot_runner_test.dart shot_registry.dart; do
  [ ! -L "$repo_root/tool/screenshots/$name" ] || fail "tool/screenshots/$name is a symlink; refusing to write through it."
  [ ! -e "$repo_root/tool/screenshots/$name" ] || [ -f "$repo_root/tool/screenshots/$name" ] || fail "tool/screenshots/$name exists but is not a regular file."
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
lints, or anything in generated code, and it honours the file's own
`// ignore:` / `// ignore_for_file:` directives so it never reports what
`flutter analyze` would suppress. It is a pre-push smoke check, not a
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
# Dart has more than one string shape, and each must be blanked as a unit:
#   * raw strings (`r'...'`, `r"..."`) - a backslash is literal there, so it
#     does NOT escape the closing quote;
#   * triple-quoted strings (`'''...'''`, `"""..."""`), which span lines; a
#     lone quote inside them is just a character.
# Order matters: triple-quoted before single-line, raw before ordinary.
COMMENT_OR_STRING = re.compile(
    r"//[^\n]*"
    r"|/\*.*?\*/"
    r"|[rR]'''(?:[^']|'(?!''))*?'''"
    r'|[rR]"""(?:[^"]|"(?!""))*?"""'
    r"|[rR]'[^'\n]*'"
    r'|[rR]"[^"\n]*"'
    r"|'''(?:\\[\s\S]|[^']|'(?!''))*?'''"
    r'|"""(?:\\[\s\S]|[^"]|"(?!""))*?"""'
    r"|'(?:\\[\s\S]|[^'\\\n])*'"
    r'|"(?:\\[\s\S]|[^"\\\n])*"',
    re.S,
)

# Return types this script bothers to look at for private functions. Dart has
# more, but a miss here only means one fewer advisory line.
FUNCTION_RE = re.compile(
    r"(?m)^[ \t]*(?:static\s+)?(?:Future<[^>]*>|void|int|double|bool|String|"
    r"Widget|List<[^>]*>|Map<[^>]*>|[A-Z]\w*(?:<[^>]*>)?\??)\s+(_\w+)\s*\(")

# `import` only: a barrel `export '...' show Foo;` is not an unused import when
# Foo is not referenced locally, and flagging it would be a false positive.
# Cross-file resolution still uses IMPORT_OR_EXPORT_RE below, which keeps both.
IMPORT_RE = re.compile(
    # `[ \t]*`, not `\s*`: with MULTILINE, `\s*` also eats the newline of a
    # preceding blank or commented line, so `im.start()` - and the reported
    # line number - landed one line above the import itself.
    r"(?m)^[ \t]*import\s+[\"'](?P<uri>[^\"']+)[\"'](?P<tail>[^;]*);")

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


IGNORE_FOR_FILE = re.compile(r"//\s*ignore_for_file:\s*([^\n]*)")
IGNORE_LINE = re.compile(r"//\s*ignore:\s*([^\n]*)")
PROBLEM_RULE = re.compile(r"\(([A-Za-z_][\w-]*)\)\s*$")
PROBLEM_LINE = re.compile(r"^.*?:(\d+):")


def ignore_rules(raw: str) -> tuple[set[str], dict[int, set[str]]]:
    """Dart's ignore directives as (file-wide rules, {line: rules}).

    The analyzer honours `// ignore:` and `// ignore_for_file:`, and generated
    files (`flutter gen-l10n`, build_runner) ship with them - a generated
    `app_localizations_bn.dart` opens with `// ignore: unused_import` and ends
    with `// ignore_for_file: type=lint`. A heuristic that reports what the
    analyzer suppresses makes the pre-push gate lie, so the directives are
    parsed from the raw source here: `blanked()` and `without_comments()` both
    erase them.
    """
    file_rules: set[str] = set()
    line_rules: dict[int, set[str]] = {}
    for number, line in enumerate(raw.splitlines(), start=1):
        for match in IGNORE_FOR_FILE.finditer(line):
            file_rules.update(name.strip() for name in match.group(1).split(",") if name.strip())
        for match in IGNORE_LINE.finditer(line):
            names = {name.strip() for name in match.group(1).split(",") if name.strip()}
            # A directive alone on its line covers the next line; a trailing
            # one covers the line it sits on.
            target = number if line.split("//", 1)[0].strip() else number + 1
            line_rules.setdefault(target, set()).update(names)
    return file_rules, line_rules


def keep_unignored(problems: list[str], raw: str) -> list[str]:
    """Drop the findings the file's own ignore directives already suppress."""
    file_rules, line_rules = ignore_rules(raw)
    if "type=lint" in file_rules:
        return []  # generated file: the analyzer lints nothing in it
    kept: list[str] = []
    for problem in problems:
        rule = PROBLEM_RULE.search(problem)
        line = PROBLEM_LINE.match(problem)
        if rule and (rule.group(1) in file_rules
                     or rule.group(1) in line_rules.get(int(line.group(1)) if line else 0, ())):
            continue
        kept.append(problem)
    return kept


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
        if re.search(r"\bsuper\.", p):
            # `super.key` (and typed forms like `Key? super.key`) is forwarded
            # to the superclass, not an optional slot of this class.
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
        # `params_close` is the index of the closing `)`, so the body starts one
        # character later; starting at `)` made every definition look abstract.
        body_start = fm.end() + params_close + 1
        after = text[body_start:]
        if not re.match(r"\s*(?:(?:async|sync)\s*\*?\s*)?(?:\{|=>)", after):
            continue  # abstract / declaration only, not a definition
        # Search everywhere except the declaration itself: Dart lets a function
        # be used above its definition, and a recursive call counts as a use.
        rest = text[:fm.start()] + text[fm.end():]
        if not re.search(rf"\b{re.escape(fn)}\b", rest):
            problems.append(f"{path}:{line_of(text, fm.start())}: private "
                            f"function {fn} is never used (unused_element)")
    return problems


def import_tail(tail: str) -> tuple[str | None, list[str]]:
    """`as` alias and `show` names from an import/export clause.

    `hide` may legally come before `show`, so the combinators are read in order
    instead of assuming one fixed position.
    """
    alias_match = re.search(r"\bas\s+(\w+)", tail)
    alias = alias_match.group(1) if alias_match else None
    shown: list[str] = []
    for cm in re.finditer(r"\bshow\s+([^;]+?)(?=\s+(?:show|hide)\b|$)", tail):
        shown += [n.strip() for n in cm.group(1).split(",") if n.strip()]
    return alias, shown


def check_imports(path: pathlib.Path, text: str) -> list[str]:
    problems: list[str] = []
    for im in IMPORT_RE.finditer(text):
        line = line_of(text, im.start())
        alias, shown = import_tail(im.group("tail"))
        # Look for uses outside the statement itself, so a name that also occurs
        # in the URI (`thing` in `thing.dart`) cannot count as a use.
        rest = text[:im.start()] + text[im.end():]
        if alias and not re.search(rf"\b{re.escape(alias)}\s*\.", rest):
            problems.append(f"{path}:{line}: import alias '{alias}' is unused "
                            f"(unused_import)")
        for name in shown:
            if not re.search(rf"\b{re.escape(name)}\b", rest):
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


IMPORT_OR_EXPORT_RE = re.compile(
    r"(?m)^\s*(?:import|export)\s+[\"']([^\"']+)[\"']")
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


def check_file(path: pathlib.Path, raw: str | None = None) -> list[str]:
    raw = path.read_text(errors="replace") if raw is None else raw
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
    raws: dict[pathlib.Path, str] = {}
    for f in files:
        raw = f.read_text(errors="replace")
        raws[f] = raw
        problems += keep_unignored(check_file(f, raw), raw)
        decl_texts[f] = blanked(raw)
        code_texts[f] = without_comments(raw)
    if len(files) > 1:
        for problem in check_cross_file(files, decl_texts, code_texts,
                                        package_name(pathlib.Path.cwd()),
                                        pathlib.Path.cwd()):
            raw = next((raws[p] for p in files if problem.startswith(f"{p}:")), "")
            problems += keep_unignored([problem], raw)
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
import calendar
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s?")
LOG_INTEREST = re.compile(
    r"(##\[error\]|error •|warning •|info •|issue found|not formatted|"
    r"would reformat|Expected:|Actual:|FAILED|Failed to|Exception:|: Error:|"
    r"No such file|✗|error:)")

# Conclusions GitHub reports that are not a pass. A `timed_out` or
# `startup_failure` run is a red branch, not "all green".
FAILURE_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "startup_failure", "action_required"})


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


def _bootstrap_token() -> str | None:
    """The token saved by agent-bootstrap, when it left one behind."""
    try:
        path = Path.home() / "agent-bootstrap" / "secrets" / "gh_token.txt"
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
    except OSError:
        pass
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
    if shutil.which("gh"):
        try:
            token = subprocess.run(["gh", "auth", "token"], capture_output=True,
                                   text=True, check=True).stdout.strip()
        except subprocess.CalledProcessError:
            token = ""
        if token:
            return token
    bootstrap = _bootstrap_token()
    if bootstrap:
        return bootstrap
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


def seconds(iso_a: str | None, iso_b: str | None) -> str:
    """Whole seconds between two ISO-8601 timestamps, in UTC.

    `time.mktime` reads the struct as local time, so a duration spanning a DST
    change would be off by the UTC offset; `calendar.timegm` treats it as UTC.
    A missing timestamp is a normal in-progress state, not an error.
    """
    if not iso_a or not iso_b:
        return "?"
    try:
        def parse(value: str) -> float:
            return float(calendar.timegm(
                time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")))
        return f"{int(parse(iso_b) - parse(iso_a))}s"
    except (TypeError, ValueError):
        return "?"


def run_order(run: dict) -> str:
    """Best-effort timestamp for ordering runs; ISO strings sort lexically."""
    return (run.get("created_at") or run.get("run_started_at")
            or run.get("updated_at") or "")


def newest_runs(runs: list[dict]) -> list[dict]:
    """One run per (name, event): the newest.

    A branch accumulates runs; an older failed run that a newer green run
    superseded must not keep the branch red.
    """
    newest: dict[tuple[str, str], dict] = {}
    for run in sorted(runs, key=run_order):
        newest[(run.get("name", ""), run.get("event", ""))] = run
    return list(newest.values())


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
        if args.branch:
            runs = newest_runs(runs)
        active = [w for w in runs if w.get("status") != "completed"]
        if runs and (not active or args.once):
            break
        if not runs and args.once:
            break
        if time.time() >= deadline:
            # Still active at the deadline is a timeout, not a clean bill of
            # health: the caller asked for a wait and got an unfinished state.
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
              f"{seconds(w.get('run_started_at'), w.get('updated_at'))}")
        if w.get("conclusion") in FAILURE_CONCLUSIONS:
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

An agent working in this repository normally spends several tool calls per
iteration: run preflight, commit, push, wait for CI, read the failure. Every one
of those calls is a place where the loop can be abandoned halfway.

This script performs the loop in one call:

    preflight  ->  secret guard  ->  commit  ->  push

    python3 tool/agent_loop.py -m "fix(profile): guard null avatar"
    python3 tool/agent_loop.py -m "..." --amend          # fix the last commit
    python3 tool/agent_loop.py -m "..." --no-push        # commit only

Work happens on the current branch (normally `main`) and is pushed straight
there - no feature branch, no pull request. CI is manual in this setup (see
AGENTS.md): nothing runs on a push, so this loop does not wait for a run. Batch
your edits and let the human dispatch CI once when the batch is ready; pass
`--watch` only when a run is already in flight.

What it refuses to do, on purpose:

  * commit a file that looks like a credential (`.env`, `*.jks`, `*.keystore`,
    `*.pem`, `key.properties`, `google-services.json`, `secrets/**`, ...)
    unless `--allow-secret-paths` is given: the playbook says secrets never
    enter git, and a pre-commit refusal is cheaper than a history rewrite;
  * stage the pack's throwaway artifacts (`.agent-screens/`,
    `.agent-pack-backups/`, `.flutter-builder-backups/`) unless
    `--allow-secret-paths` is given: they are local evidence, not source, and a
    refused run unstages them again so nothing is left in the index;
  * push when `tool/preflight.py` reports issues, unless `--no-preflight` is
    given: those findings are exactly what turns a push red.

Exit codes: 0 = pushed (or committed with --no-push); 1 = the push failed;
2 = refused or stopped before anything was changed.

Standard library only, python3 >= 3.8. `git` must be on PATH.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
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

# The pack's own output directories: screenshots and replaced-file backups.
# They are git-ignored on install (see scripts/install-agent-pack.sh) and are
# evidence, never source, so a run must not sweep them into a commit.
ARTIFACT_PATTERNS = [
    r"(^|/)\.agent-screens/",
    r"(^|/)\.agent-pack-backups/",
    r"(^|/)\.flutter-builder-backups/",
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


def staged_paths(root: Path) -> list[str]:
    """Currently staged paths (added/copied/modified/renamed)."""
    proc = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", cwd=root)
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def staged_secrets(root: Path) -> list[str]:
    """Staged paths that look like credentials (ignoring .gitignore'd ones)."""
    return [path for path in staged_paths(root)
            if any(re.search(pattern, path) for pattern in SECRET_PATTERNS)]


def staged_artifacts(root: Path) -> list[str]:
    """Staged paths inside the pack's throwaway artifact directories."""
    return [path for path in staged_paths(root)
            if any(re.search(pattern, path) for pattern in ARTIFACT_PATTERNS)]


def unstage_newly_forbidden(root: Path, already_staged: set[str],
                            hits: list[str]) -> None:
    """Unstage forbidden paths this run added, leaving prior state alone.

    `git add -A` sweeps in everything, including a `.env` that was never
    staged; a refused run must not leave that in the index. Paths that were
    already staged before this run are the caller's prior state and stay.
    """
    newly = [path for path in hits if path not in already_staged]
    if newly:
        git("reset", "-q", "--", *newly, cwd=root)


def _bootstrap_token() -> str | None:
    """The token saved by agent-bootstrap, when it left one behind."""
    try:
        path = Path.home() / "agent-bootstrap" / "secrets" / "gh_token.txt"
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
    except OSError:
        pass
    return None


def resolve_token(arg: str | None) -> str | None:
    """Flag, environment, then the GitHub CLI, then agent-bootstrap's save."""
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
    if shutil.which("gh"):
        proc = subprocess.run(["gh", "auth", "token"], capture_output=True,
                              text=True, check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return _bootstrap_token()


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
    # Repository names may contain dots (`flutter.bootstrap`); only a trailing
    # `.git` is stripped.
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?$",
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
        description="preflight -> commit -> push, in one call.")
    parser.add_argument("-m", "--message", help="commit message (conventional commits)")
    parser.add_argument("--amend", action="store_true",
                        help="amend the last commit (pushes with --force-with-lease)")
    parser.add_argument("--paths", nargs="*", default=None,
                        help="paths to stage (default: everything changed)")
    parser.add_argument("--allow-secret-paths", action="store_true",
                        help="stage files that look like credentials (review them first)")
    parser.add_argument("--no-preflight", action="store_true",
                        help="skip tool/preflight.py (CI will be the first check)")
    parser.add_argument("--no-push", action="store_true", help="commit only")
    parser.add_argument("--watch", action="store_true",
                        help="wait for this commit's CI run (CI is manual here, "
                             "so only after a run is already in flight)")
    parser.add_argument("--no-watch", action="store_true",
                        help="accepted for compatibility; not watching is the default")
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
    if args.no_preflight and args.watch:
        print("agent_loop: --no-preflight with --watch means CI is the first "
              "check; that is exactly the slow path this tool avoids.")

    root = repo_root()
    branch = git_out("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
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

    # 2. stage. Remember what was already staged so a refusal can put the
    # index back the way it found it.
    already_staged = set(staged_paths(root))
    if args.paths:
        git("add", "--", *args.paths, cwd=root)
    else:
        git("add", "-A", cwd=root)

    if not args.amend:
        staged = git("diff", "--cached", "--name-only", cwd=root).stdout.strip()
        if not staged:
            print("agent_loop: nothing staged; there is no change to commit.")
            return 2

    # 3. artifact guard -- local output must not be committed, and a refused
    # run must not leave it staged either.
    artifacts = staged_artifacts(root)
    if artifacts and not args.allow_secret_paths:
        unstage_newly_forbidden(root, already_staged, artifacts)
        print("agent_loop: refusing to stage pack artifacts:", file=sys.stderr)
        for path in artifacts:
            print(f"  {path}", file=sys.stderr)
        print("  Add them to .gitignore (they are local evidence), or pass "
              "--allow-secret-paths if they are safe by design.",
              file=sys.stderr)
        return 2

    # 4. secret guard -- before the commit, never after the push.
    hits = staged_secrets(root)
    if hits and not args.allow_secret_paths:
        unstage_newly_forbidden(root, already_staged, hits)
        print("agent_loop: refusing to commit files that look like credentials:",
              file=sys.stderr)
        for path in hits:
            print(f"  {path}", file=sys.stderr)
        print("  Add them to .gitignore (and rotate anything already exposed), "
              "or pass --allow-secret-paths if they are safe by design.",
              file=sys.stderr)
        return 2

    # 5. commit.
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

    # 6. push. An amended commit needs --force-with-lease: plain --force would
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

    # 7. watch. CI is manual here, so a push normally starts nothing and waiting
    # would only time out. --watch opts in when a run is already in flight.
    if not args.watch or args.draft_pr:
        print("agent_loop: done (CI not watched; run it from Actions when ready).")
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
import calendar
import json
import os
import random
import re
import shutil
import stat
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
    """Seconds since the epoch for a GitHub UTC timestamp, or 0.0.

    `time.mktime` reads the struct as local time and `time.timezone` is only the
    standard-time offset, so the old `mktime(...) - time.timezone` shifted by an
    hour across a DST boundary. `calendar.timegm` treats the fields as UTC.
    """
    if not stamp:
        return 0.0
    try:
        return float(calendar.timegm(
            time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return 0.0


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
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_StripAuthOnHostChange)


def api(method: str, path: str, token: str, payload: dict | None = None,
        raw: bool = False, timeout: int = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "flutter-builder-see-screen",
    }
    if data is not None:  # a bodyless GET has no Content-Type
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers=headers)
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


def _bootstrap_token() -> str | None:
    """The token saved by agent-bootstrap, when it left one behind."""
    try:
        path = Path.home() / "agent-bootstrap" / "secrets" / "gh_token.txt"
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
    except OSError:
        pass
    return None


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
    bootstrap = _bootstrap_token()
    if bootstrap:
        return bootstrap
    raise SystemExit(
        "see_screen: no GitHub token.\n"
        "  Run `gh auth login`, or export GH_TOKEN=... (needs Actions: write on "
        "the repository and Contents: read for the artifact).")


# --------------------------------------------------------------------------
# the steps
# --------------------------------------------------------------------------
def dispatch(repo: str, ref: str, inputs: dict, token: str,
             workflow: str = WORKFLOW_FILE) -> None:
    quoted = urllib.parse.quote(workflow, safe="")
    api("POST", f"/repos/{repo}/actions/workflows/{quoted}/dispatches",
        token, {"ref": ref, "inputs": inputs})


def default_branch(repo: str, token: str) -> str:
    return api("GET", f"/repos/{repo}", token).get("default_branch", "main")


def find_run(repo: str, note: str, not_before: float, token: str,
             workflow: str = WORKFLOW_FILE, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    quoted = urllib.parse.quote(workflow, safe="")
    path = (f"/repos/{repo}/actions/workflows/{quoted}/runs"
            f"?event=workflow_dispatch&per_page=20")
    while True:
        runs = api("GET", path, token).get("workflow_runs", [])
        run = pick_run(runs, note, not_before)
        if run:
            return run
        if time.time() > deadline:
            raise SystemExit(
                f"see_screen: dispatched, but no run appeared within {int(timeout)}s.\n"
                f"  Check https://github.com/{repo}/actions/workflows/{workflow}")
        time.sleep(5)


def wait_for_run(repo: str, run: dict, token: str, timeout: float,
                 report: bool = True, notify=None) -> dict:
    started = time.time()
    last = ""
    while True:
        run = api("GET", f"/repos/{repo}/actions/runs/{run['id']}", token)
        state = run.get("conclusion") or run.get("status")
        if report and state != last:
            message = f"see_screen: run {run['id']} -> {state}  ({run['html_url']})"
            if notify is not None:
                notify(message)
            else:
                print(message)
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
    artifacts = [a for a in api(
        "GET", f"/repos/{repo}/actions/runs/{run['id']}/artifacts",
        token).get("artifacts", []) if not a.get("expired")]
    if not artifacts:
        raise SystemExit(f"see_screen: the run produced no artifact - {run['html_url']}")
    named = [
        a for a in artifacts
        if a.get("name") == "ui-screenshots"
        or str(a.get("name") or "").startswith("ui-screenshots-")
    ]
    artifact = (named or artifacts)[0]
    blob = api("GET", f"/repos/{repo}/actions/artifacts/{artifact['id']}/zip",
               token, raw=True, timeout=180)
    archive = out / "artifact.zip"
    archive.write_bytes(blob)
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            if member.endswith("/"):
                continue  # directory entry
            target = (out / member).resolve()
            if not target.is_relative_to(out.resolve()):
                continue  # no path escapes from a zip
            info = zf.getinfo(member)
            if stat.S_ISLNK(info.external_attr >> 16):
                continue  # never materialise a zip symlink
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
    parser.add_argument("--workflow", default=WORKFLOW_FILE,
                        help=f"caller workflow file (default {WORKFLOW_FILE})")
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

    workflow = args.workflow or WORKFLOW_FILE

    def notify(message: str) -> None:
        """Progress goes to stderr under --json, so stdout stays parseable."""
        print(message, file=sys.stderr if args.json else sys.stdout)

    nonce = f"{int(time.time())}-{random.randint(1000, 9999)}"
    note = f"see {nonce} {' '.join(routes)}"
    inputs = build_inputs(routes, args, note)

    if args.dry_run:
        print(json.dumps({"repo": repo, "workflow": workflow, "inputs": inputs}, indent=2))
        return 0

    token = resolve_token(args.token_file)
    ref = args.ref or default_branch(repo, token)
    asked_at = time.time()
    dispatch(repo, ref, inputs, token, workflow)
    notify(f"see_screen: asked {repo} to photograph {', '.join(routes)}")

    run = find_run(repo, note, asked_at, token, workflow)
    if args.no_wait:
        notify(run["html_url"])
        return 0

    run = wait_for_run(repo, run, token, args.timeout, notify=notify)

    if run.get("conclusion") != "success":
        notify(f"see_screen: the capture run ended as {run.get('conclusion')}")
        for step in failed_steps(repo, run["id"], token):
            notify(f"  failed: {step}")
        notify(f"  {run['html_url']}")
        notify("  next: python3 tool/ci_watch.py   (prints the failing log lines)")
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
a session: everything here exists to keep the work moving without burning CI.

<!-- flutter-builder:agent-pack:start v1.18.9 -->
## Captain task or independent work?

**Captain A/B/C assignment:** attach this **app repo** in Arena Agent Mode,
not `flutter-builder`. Read the pinned GitHub `BRIEF.md` and `task.json` from
this app repo, then follow [Captain Fast Lane](https://github.com/Keshab1997/agent-bootstrap/blob/main/captain/FASTLANE.md).
If the correct repo is not attached, report `BLOCKED` before editing; don't
use a separate clone or new pairing.

- Use the installed `tool/preflight.py` and the exact gate in `task.json`.
  For Dart, use the assigned SDK pin, lockfile and targeted test. Keep the
  app's existing `flutter-builder` pin; don't install or upgrade the pack
  just to follow a brief.
- Stay on the actual `arena/*` branch. Use Fast Lane to check and publish
  the checkpoint. Do not push `main`, run `tool/agent_loop.py`, dispatch CI
  (including via `tool/see_screen.py`), or open, merge or close a PR.
- After verifying the remote checkpoint, mention `@Keshab1997` in the
  approved tracking issue. If commenting is unavailable, report
  `MENTION PENDING` and the verified checkpoint in Arena.

The direct-to-`main` and one-command push examples below are only for
**independent work explicitly authorized to push to `main`**.

## Rule #1 — CI is one dispatch per batch; preflight is your check

This repository's CI is **manual** — a push never queues it (a push can still
start configured previews or checks). Since 2026-11-20 Keshab approves agents
dispatching it themselves once a batch is ready:
`python3 /home/user/agent-bootstrap/captain/ci_dispatch.py <owner>/<repo> --watch 900`
(button fallback: Actions → *Flutter CI* → Run workflow). Captain **workers**
never dispatch — they checkpoint their `arena/*` branch and report. So:

> **Name things as the project actually has them.** The workflow names in this
> file are the pack's defaults; a project may hand-roll its gates instead of
> copying the examples. Read `.github/workflows/` once per session and quote the
> real names — dispatching a workflow that does not exist wastes the human's
> turn, and assuming one covers your change is how a batch ships unchecked.

- For explicitly authorized independent work, push directly to `main`. A
  Captain worker only checkpoints its `arena/*` branch as above.
- Do **not** wait for CI mid-batch. Keep working; dispatch once, when the
  batch is ready (command above), and say *"batch ready"* in the report.
- `tool/preflight.py` is your only automatic check. Run it before every push —
  it is seconds, not minutes, and catches the mistakes that would otherwise
  surface in the next manual CI run.
- **Dart edits are checked on purpose, not by reflex.** Most changes have a
  matching test file: run the one that covers your edit
  (`flutter test test/<name>_test.dart`), not the whole suite. `flutter analyze`
  and the full `flutter test` are for diffs that touch a shared surface, for
  work that feels risky, or for when the human asks — repeating the full pair
  after every small edit is the fastest way to make the loop feel like a chore.
  Everything else (Markdown, YAML, scripts, docs) still ships on preflight
  alone. See *Checking Dart for real* below.
- **When CI does run, it is the source of truth** — read its result before
  calling a batch done. But it runs when the human says so, not on your push.

```bash
python3 tool/preflight.py     # before every push: dead code / unused params / unused imports
python3 tool/agent_loop.py -m "fix(scope): what changed"   # independent work explicitly authorized for main only
```

### What a check costs

| Check | Cost | When it is the right check |
|---|---|---|
| `python3 tool/preflight.py` | ~1 s | every change, before every push |
| `flutter test test/<file>_test.dart` (via flutter-bootstrap) | 40 s once per session, then seconds | the Dart change that file covers |
| `flutter analyze` or the full `flutter test` | ~20 s / 1–3 min | shared surfaces, risky diffs, or when the human asks |
| `python3 tool/local_screenshots.py --shot <name>` | one `flutter test` run, ~1 s per screen, no CI | every widget change you want to see |
| `python3 tool/see_screen.py` | one CI run | before and after a UI change |
| The human's CI run | the human's attention + a runner | once per finished batch — never per edit |

Pick the cheapest check that actually covers the change. Building the whole app
to answer a question `flutter analyze` can answer is the most common way to turn
a two-minute task into a twenty-minute one.

### Checking Dart for real (flutter-bootstrap)

The sandbox starts without a Flutter SDK, and one installed now is gone next
session. `flutter-bootstrap` installs a working SDK in ~40 seconds, with no
credentials and a sha256-verified download:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-bootstrap/main/setup.sh) --quiet --json
cd <app-dir> && flutter pub get && flutter analyze && flutter test
```

- When you run a Dart check at all, `flutter analyze` is the floor: it catches
  exactly what preflight cannot, in ~20 seconds. Worth it for a diff that
  reaches a shared surface, or one you cannot clear by reading it.
- A behaviour change with a matching test gets that **one file** run
  (`flutter test test/<name>_test.dart`). The full suite belongs to the human's
  CI run, unless the human asks for it locally.
- CI pins its own Flutter version: a local pass is *indicative*, not final. When
  the two disagree, CI wins — do not "fix" code to satisfy the local version
  without saying so in the commit message.
- Do **not** `flutter build apk` / `flutter build aab` / `flutter build web`
  locally "just to check". That is minutes per run for an artifact only the CI
  workflow needs to produce, and the signing secrets live in CI anyway.
- Re-running that one-liner later in the same session is safe and instant (~0.2 s
  when the SDK is already there).
- For authorized independent work, the companion repo `agent-bootstrap` can
  restore an approved GitHub session if existing access is insufficient. A
  Captain worker uses the attached repo’s native Arena access and does not pair.

## Independent work: the batch loop for an authorized `main` push

Small edits are cheap; CI runs are not. So batch them instead of running CI per
change:

1. **Edit** the smallest diff that does one thing.
2. **`python3 tool/preflight.py`** — 1 second, no SDK. Fix what it reports.
3. **Commit and push to `main`.** `python3 tool/agent_loop.py -m "…"` does
   preflight, the secret guard, the commit and the push in one call. Repeat for
   each small change; every commit goes straight to `main`.
4. **Do not wait for CI mid-batch.** Keep working.
5. **When the batch is ready, say *"batch ready"* and dispatch CI once** —
   `python3 /home/user/agent-bootstrap/captain/ci_dispatch.py <owner>/<repo> --watch 900`,
   or the button: Actions → *Flutter CI* → Run workflow. If a run is already
   in flight, `python3 tool/ci_watch.py` prints the conclusion of every
   workflow plus the interesting lines of the failed ones.

Rules of thumb: a CI run per push wastes the most time; push freely, run CI once
per batch. When a red run does arrive, read the log before editing — guessing at
a red build doubles the rounds.

### The same independent loop as one command

Never use this shortcut on a Captain assignment. `tool/agent_loop.py` performs
preflight, the secret guard, the commit and the push in a single call:

```bash
python3 tool/agent_loop.py -m "fix(profile): guard a null avatar"
python3 tool/agent_loop.py -m "fix(profile): drop the unused import" --amend
python3 tool/agent_loop.py -m "chore: wip" --no-push     # commit without pushing
python3 tool/agent_loop.py -m "…" --watch                # wait, only if a run is in flight
```

It refuses, before touching the repository, when

- a staged file looks like a credential (`.env`, `*.jks`, `*.keystore`, `*.pem`,
  `key.properties`, `google-services.json`, `secrets/**`, …) — a refusal costs
  one edit, a leaked keystore costs a rotation;
- `preflight.py` reports anything — use `--no-preflight` only when the findings
  are deliberate.

It commits on the current branch (normally `main`) and pushes there; no branch,
no pull request. Exit codes: `0` committed/pushed, `1` the push failed,
`2` refused before changing anything. An `--amend` push uses
`--force-with-lease`, never a bare `--force`.

## Seeing a screen — look, do not guess

You cannot run the app, but you can *see* it, and the fast way costs nothing on
GitHub: `tool/local_screenshots.py` renders the screens listed in
`tool/screenshots/shot_registry.dart` to PNGs with `flutter test`, offline.

```bash
python3 tool/local_screenshots.py --list               # the shots this project has
python3 tool/local_screenshots.py --shot home          # one
python3 tool/local_screenshots.py --shot home,settings # several, one run
python3 tool/local_screenshots.py                      # all of them
```

* `shot_registry.dart` is **your** file: it says which screens to photograph and
  how to dress them (the app's theme, its fonts, its native channel answered as
  "nothing granted yet", any local store initialised). Add a shot when you add a
  screen; keep it small and honest. The framework and the runner next to it are
  the pack's and are replaced when the pack updates — a fix belongs upstream.
* The pictures land in `.agent-screens/` (git-ignored). They are **evidence, not
  fixtures**: never read one back as a test input, never commit one, and never
  let CI pay for rendering.
* A shot that renders as a red error page is telling you the truth: a missing
  mock, a missing font, a missing `setUp`. Fix the shot, not the screenshot tool.

For independent work with the human's CI approval, `tool/see_screen.py` can
photograph the pushed web build instead of a local test. It dispatches CI,
waits for the run, downloads the images and prints their paths. Then open
those images to verify the screen:

```bash
python3 tool/see_screen.py --route /settings           # one screen
python3 tool/see_screen.py --route / --route /profile  # several, one build
python3 tool/see_screen.py --route /settings --wait-ms 12000   # slow first frame
```

* **Use it before and after a UI change.** Before: see what the screen looks
  like now. After: see what your change did. A green CI says the code compiles;
  only the picture says the layout is right.
* This starts the UI-screenshots workflow. It is not a Captain worker check.
  For a screen you can render in a test, use `tool/local_screenshots.py`
  without starting CI.
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

## Four things that cost an hour here (do not do them)

1. **Waiting for manual CI after a push.** That run was not queued; see the
   table below.
2. **Running a full build to check a Dart edit.** `flutter build apk|aab|web`
   takes minutes and proves nothing `analyze` + `test` did not already prove.
3. **Asking the human for a CI run before preflight is green and the tests you
   chose to run pass.** A red run spends their attention and a runner, and tells
   you what a local check would have.
4. **Guessing at a red build.** Read the failing step's log first (below). A
   guess that misses doubles the rounds, which is the whole cost this file
   exists to avoid.

## What a push costs here

| Situation | What runs |
|---|---|
| Push to a non-Pages branch with app/code/assets/dependency changes | web preview refreshes; CI stays manual |
| Docs/Markdown/release-note/`.github/`-only push | nothing |
| You ask the human to run CI | CI once, for the whole batch |
| `flutter analyze` / `flutter test` (via flutter-bootstrap) | nothing on GitHub — 40 s to install once per session, then seconds to minutes |
| `local_screenshots.py` | nothing on GitHub — local `flutter test` only |
| `see_screen.py` | the UI-screenshots workflow, once per call |
| a workflow with a `paths:` filter that your change misses | **nothing** — see below |

A project's Dart job is often path-filtered (e.g. `paths: lib/features/x/**`)
so that a small batch does not spend a run. The trap: a change *outside* those
paths starts **no run at all**, and a green board afterwards means "nothing
was checked", not "nothing broke". When the diff is even slightly risky and no
workflow matches it, run the local pair once (`flutter analyze` + the relevant
`flutter test`) — that is the only check that diff will ever get.

If you want a run right now, do **not** retrigger it with an empty commit — use
*Actions → Run workflow* (or the `ci_dispatch.py` one-liner from Rule #1).

## CI map

The pack's standard set, for a project that copied `examples/project-workflows/`.
Confirm the list against `.github/workflows/` before quoting it — a project may
have fewer (or differently named) workflows:

| Workflow | Runs when | What it does |
|---|---|---|
| `ci.yml` → shared `flutter-build.yml` | **manual** (`workflow_dispatch`) | `dart format` check → `flutter analyze --fatal-infos` → `flutter test` + coverage |
| `web-preview.yml` | relevant branch push, manual dispatch, branch delete | builds the web app and replaces that branch's `preview/<branch>/` on GitHub Pages |
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
- **Use the authorized lane.** Captain workers checkpoint only `arena/*`.
  Independent work can push to `main` when explicitly authorized. Batch small
  changes and let the human run CI once at the end.
- **Secrets never enter git:** `google-services.json`, `android/key.properties`,
  `*.jks` / `*.keystore`, `.pem`, tokens. CI receives them from repository
  secrets. Do not add them to the repo to "make CI pass".
- **Respect existing structure:** edit existing files over adding new ones, and
  read the file you are about to change (comments explain *why* the code is the
  way it is — keep that voice).
- **Match the check to the change** — the cost table near the top of this file
  is the map. Cheap checks run every time; CI runs once, at the end.

## Companion Flutter packages — reuse, don't rebuild

Before writing boilerplate for cross-app features from scratch, check these
shared `Keshab1997` Dart packages (all install cleanly via `pubspec.yaml` `git:`
dependencies):

| Need | Package | Notes |
|---|---|---|
| Remote soft/force updates, maintenance screen, scheduled notices, feature flags | [`app_pulse_kit`](https://github.com/Keshab1997/app_pulse_kit) | Zero-cost `pulse.json` or Firestore (`CallbackPulseSource`), offline cache, built-in EN + বাংলা UI. Keep `pulse.json` aligned with `pubspec.yaml` via `scripts/sync-pulse-config.py` from `flutter-builder`. |
| Smart Play Store rating gate (4–5★ → In-App Review, 1–3★ → in-app feedback + auto diagnostics) | [`smart_review_feedback`](https://github.com/Keshab1997/smart_review_feedback) | Pluggable sinks (Webhook, Telegram, Email, Firestore `CallbackFeedbackSink`), built-in EN + বাংলা UI. |
| Indian currency (`₹`/`৳`, Lakh/Crore), Bangla digits, number-to-words, Bangla dates & deadline chips | [`bangla_kit`](https://github.com/Keshab1997/bangla_kit) | Zero third-party dependencies; ideal for Bengali/Indian finance, quiz, and job apps. |
| Offline-first encrypted JSON backup & restore (SHA-256 + password + schema migrations, EN + বাংলা UI) | [`local_vault_backup`](https://github.com/Keshab1997/local_vault_backup) | Pure-Dart encryption (`crypto` only); works with SQLite, Hive, Isar, or SharedPreferences. |
| Single web control panel to manage `pulse.json` across all Flutter apps | [`pulse-control-panel`](https://github.com/Keshab1997/pulse-control-panel) | Zero-cost static web UI (GitHub Pages / local browser) for updates, maintenance, notices & flags. |
| AdMob monetization (auto debug test IDs, interstitial capping, adaptive banners, EN/বাংলা rewarded prompts & kill-switch) | [`smart_ad_kit`](https://github.com/Keshab1997/smart_ad_kit) | Protects AdMob accounts in debug builds, supports 1-line `app_pulse_kit` `ads_enabled` toggle & `FakeAdBackend` for tests. |
| Firestore-backed admin API key pool (failover, cooldowns, health checks, admin UI) | [`admin_api_key_manager`](https://github.com/Keshab1997/admin_api_key_manager) | Shared Gemini / OpenRouter key rotation & management. |
| Shared OCR + AI extraction pipeline | [`smart_ocr_ai_bridge`](https://github.com/Keshab1997/smart_ocr_ai_bridge) | Reusable OCR-to-AI bridge for scanner apps. |
| 1-click new Flutter app template (pre-wired with `flutter-builder`, Agent Pack, `app_pulse_kit`, signing & Settings) | [`flutter-app-starter`](https://github.com/Keshab1997/flutter-app-starter) | Click **Use this template** → **Actions → Setup New App (1-Click)** to spin up a new app in ~30s. |

## Ask the human before

- running CI, when a batch is ready to be checked (they own the run button);
- **tagging a release**, or touching workflows / secrets / repository settings;
- force-pushing over history you do not own, or deleting branches, tags, or
  repository content;
- anything that publishes publicly, spends money, or is irreversible.

## মানুষের জন্য — এই ফাইলটা কী

- **যে যাচাইটা আসলে দরকার, শুধু সেটাই:** ছোট পরিবর্তনে শুধু `preflight.py`
  (~১ সেকেন্ড); Dart বদলালে সংশ্লিষ্ট একটা test ফাইল
  (`flutter test test/<name>_test.dart`) — পুরো `analyze` + `test` শুধু shared
  কিছু বদলালে বা আপনি বললে। প্রতিটা ছোট edit-এর পিছনে পুরো suite চালানো লাগে না।
- **Captain brief হলে** app repo Arena-তে attach করে শুধু `arena/*` branch-এ
  checkpoint দিন। আলাদা অনুমোদিত কাজেই সরাসরি `main`-এ push।
- **CI চালানোর বোতাম আপনারই** — একটা batch শেষ হলে একবার চালালেই যথেষ্ট।
- **UI বদলালে ছবি দেখে যাচাই** — আগে `python3 tool/local_screenshots.py --shot <নাম>` (ফ্রি, সেকেন্ডে), দরকার হলে `python3 tool/see_screen.py`।
- **agent আগে অনুমতি নেবে** — tag/release, secrets, store metadata, বা যা
  ফিরিয়ে আনা যায় না এমন কিছুর আগে।
- এই ব্লকটা `install-agent-pack.sh` চালালে নিজে থেকেই update হয়; নিচের
  আপনার নিজের notes কখনো মোছা হয় না।

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

# The screenshot harness. Four files, and only three of them are ours.
cat > "$stage/shot_framework.dart" <<'AGENT_PACK_SHOT_FRAMEWORK_DART_EOF'
// ============================================================================
// shim: part of the flutter-builder agent pack. DO NOT EDIT IN A PROJECT.
//
// Installed by scripts/install-agent-pack.sh into tool/screenshots/. The
// canonical copy lives in Keshab1997/flutter-builder (agent-pack/); a local
// edit is overwritten the next time the installer runs with --force, and the
// pack's own tests compare this file byte for byte with that copy.
//
// Everything a project has to say about itself lives in shot_registry.dart
// next door: this file must compile against any Flutter app, which is why it
// imports nothing from the app, no state-management package and no theme class.
// ============================================================================
//
// Render screens to PNGs, in the test harness, with the app's real theme and
// real fonts - no device, no CI run, no network.
//
// Why it exists next to tool/see_screen.py: that one asks CI to build the web
// app and photograph *routes*. It costs a run and it cannot reach a screen you
// have to tap into (any pushed detail screen). This renders the widget itself,
// so it takes about a second and photographs exactly what you named.
//
// The PNGs are throwaway evidence: they land in .agent-screens/local/
// (git-ignored) and nothing reads them back as a test fixture.
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

/// One screen, rendered the way a phone would render it.
class Shot {
  const Shot({
    required this.name,
    required this.build,
    this.preferences = const <String, Object>{},
    this.logicalSize = const Size(390, 844),
    this.dpr = 2,
    this.dark = true,
    this.textScale = 1,
  });

  /// What `--shot <name>` takes, and the PNG's file name. Kebab-case.
  final String name;
  final Widget Function() build;

  /// Values seeded into SharedPreferences before the pump - this is how a shot
  /// can show a Bengali session or a three-draft setting without anybody
  /// tapping anything.
  final Map<String, Object> preferences;

  /// Logical size. 390x844 is a modern phone; use 320x... to see what a narrow
  /// screen does to a layout, because that is where layouts break.
  final Size logicalSize;
  final double dpr;
  final bool dark;
  final double textScale;

  String get sizeLabel =>
      '${logicalSize.width.toInt()}x${logicalSize.height.toInt()}@${dpr}x';
}

/// Everything the framework needs to know about the app it is rendering.
///
/// This is the whole contract with a project, and it is deliberately small:
/// the app shell, a wrapper, font files, and the mocks a widget test needs. A
/// screenshot taken in a bare theme is a screenshot of a different app, so
/// [app] is required and there is no default.
class ShotEnv {
  const ShotEnv({
    required this.app,
    this.wrap = _noWrap,
    this.fontAssets = const <String, String>{},
    this.bridgeChannel,
    this.bridgeAnswers = const <String, Object?>{},
    this.seedPreferences,
    this.setUpAll,
    this.materialIconsFamily = 'MaterialIcons',
  });

  /// Builds the widget that goes above the screen: the app's own MaterialApp
  /// (or CupertinoApp), with its real theme and locale.
  ///
  /// It is a callback rather than a `ThemeData` field on purpose. Flutter has
  /// started moving material out of the framework into `package:material_ui`,
  /// where `ThemeData` is a *different type* than the one in
  /// `package:flutter/material.dart` - so a framework that named either import
  /// would fail to compile in half the projects that install it. Handing the
  /// shell back to the project keeps this file free of both, and lets a project
  /// add a locale, a golden-ratio fix or a ProviderScope without touching the,
  /// pack.
  final Widget Function(Shot shot, Widget home) app;

  /// ProviderScope, MultiBlocProvider, GetIt bootstrap - whatever the app puts
  /// above its widgets in main(). Identity by default, when there is nothing.
  final Widget Function(Widget child) wrap;

  /// Font family name -> asset path, e.g. {'Inter': 'assets/fonts/Inter.ttf'}.
  /// Without these every glyph renders as a solid box and the picture is worse
  /// than useless: it looks like a layout bug.
  final Map<String, String> fontAssets;

  /// The MethodChannel the app talks to its native side on, mocked for the
  /// duration of the run. Null means the app has no such channel.
  final String? bridgeChannel;

  /// method name -> the answer a "nothing is set up yet" install would give.
  /// A shot should show the honest empty state, not a red screen.
  final Map<String, Object?> bridgeAnswers;

  /// How to seed SharedPreferences from [Shot.preferences].
  ///
  /// The pack does not import shared_preferences: an app without that
  /// dependency would fail to compile, and the pack has to fit every project.
  /// Pass `(values) => SharedPreferences.setMockInitialValues(values)` (add the
  /// `// ignore: invalid_use_of_visible_for_testing_member`) or seed your own
  /// store instead. Leave it null only if no shot declares preferences.
  final Future<void> Function(Map<String, Object> values)? seedPreferences;

  /// Runs once before the first shot: Hive.init, temp directories, fake clocks.
  /// A widget that opens a local box throws without this, and the shot would be
  /// a red error page instead of a screen.
  final Future<void> Function()? setUpAll;

  /// The icon font family, which ships with the SDK rather than the repo.
  final String materialIconsFamily;

  static Widget _noWrap(Widget child) => child;
}

/// The two flags, read as strings.
///
/// `bool.fromEnvironment` only understands "true"/"false", so the documented
/// `--dart-define=SHOTS=1` would leave the whole tool silently off. Strings do
/// not have that trap.
const String _shotsFlag = String.fromEnvironment('SHOTS');
const String requestedShots = String.fromEnvironment('SHOT');

/// No define, no rendering: a direct run of the runner cannot start writing
/// PNGs by accident.
const bool shotsEnabled = _shotsFlag == '1' || _shotsFlag == 'true';

/// Where the PNGs go. Two spellings of one directory on purpose: Flutter
/// resolves a golden path against *the test file's* directory, while dart:io
/// creates directories against the *package root*.
const String goldenDir = '../../.agent-screens/local';
const String outputDir = '.agent-screens/local';

/// The widget the golden is taken of: everything the app drew, nothing else.
const ValueKey<String> shotRootKey = ValueKey<String>('agent-pack-shot-root');

/// `--dart-define=SHOT=a,b` selects; empty means every shot.
List<Shot> selectShots(List<Shot> shots, String requested) {
  final wanted = requested
      .split(',')
      .map((name) => name.trim())
      .where((name) => name.isNotEmpty)
      .toSet();
  if (wanted.isEmpty) return shots;
  return shots.where((shot) => wanted.contains(shot.name)).toList();
}

Future<void> _loadAppFonts(ShotEnv env) async {
  for (final entry in env.fontAssets.entries) {
    final file = File(entry.value);
    if (!file.existsSync()) {
      throw StateError(
        'shot fonts: "${entry.key}" points at ${entry.value}, which does not '
        'exist. Fix fontAssets in shot_registry.dart.',
      );
    }
    final bytes = file.readAsBytesSync();
    final loader = FontLoader(entry.key)
      ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
    await loader.load();
  }

  // Icons are a font too, and this one ships with the SDK, not the repo. Two
  // ways to find the SDK: the environment, and the running binary itself - a
  // test process lives at <sdk>/bin/cache/dart-sdk/bin/dart, so five parents up
  // is the SDK root. Never a hard-coded install path: that is one machine's
  // layout, and this file has to work on everybody's.
  final candidates = <String>[
    for (final root in <String>[
      Platform.environment['FLUTTER_ROOT'] ?? '',
      _sdkRootFromExecutable(),
    ])
      if (root.isNotEmpty)
        '$root/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
  ];
  final icons = candidates.map(File.new).where((f) => f.existsSync()).toList();
  if (icons.isEmpty) {
    throw StateError(
      'shot fonts: MaterialIcons not found (looked in $candidates). Icons '
      'would render as boxes, so this stops instead of writing a misleading '
      'screenshot. Set FLUTTER_ROOT if the SDK lives elsewhere.',
    );
  }
  final bytes = icons.first.readAsBytesSync();
  final loader = FontLoader(env.materialIconsFamily)
    ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
  await loader.load();
}

/// `<sdk>/bin/cache/dart-sdk/bin/dart` -> `<sdk>`, where the SDK keeps the
/// icon font. Empty when the binary does not sit inside an SDK (a `dart` from a
/// package manager, say) - then FLUTTER_ROOT has to answer.
String _sdkRootFromExecutable() {
  Directory dir = File(Platform.resolvedExecutable).parent;
  for (var i = 0; i < 5; i++) {
    dir = dir.parent;
  }
  return dir.path;
}

void _mockBridge(TestWidgetsFlutterBinding binding, ShotEnv env) {
  final name = env.bridgeChannel;
  if (name == null) return;
  final channel = MethodChannel(name);
  binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
    call,
  ) async {
    return env.bridgeAnswers[call.method];
  });
}

/// The whole suite. Call this from the runner; there is nothing else to it.
void runShotSuite({
  required List<Shot> shots,
  required ShotEnv env,
  String requested = requestedShots,
  bool enabled = shotsEnabled,
}) {
  if (!enabled) {
    test('screenshot runner is off (pass --dart-define=SHOTS=1)', () {});
    return;
  }

  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  final selected = selectShots(shots, requested);

  setUpAll(() async {
    await _loadAppFonts(env);
    _mockBridge(binding, env);
    await env.setUpAll?.call();
    Directory(outputDir).createSync(recursive: true);
  });

  if (selected.isEmpty) {
    test('no shot matched --dart-define=SHOT=$requested', () {
      fail(
        'Nothing matched. Known shots: '
        '${shots.map((shot) => shot.name).join(', ')}',
      );
    });
    return;
  }

  for (final shot in selected) {
    testWidgets('shot: ${shot.name} (${shot.sizeLabel})', (tester) async {
      final seed = env.seedPreferences;
      if (seed != null) {
        await seed(shot.preferences);
      } else if (shot.preferences.isNotEmpty) {
        // Fail loudly here rather than let the screen paint a MissingPlugin
        // red page: a silent empty store looks like a bug in the app.
        fail(
          'shot "${shot.name}" declares preferences but ShotEnv.seedPreferences '
          'is null - nothing was seeded.',
        );
      }

      tester.view.physicalSize = Size(
        shot.logicalSize.width * shot.dpr,
        shot.logicalSize.height * shot.dpr,
      );
      tester.view.devicePixelRatio = shot.dpr;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(
        env.wrap(
          MediaQuery(
            data: MediaQueryData(
              size: shot.logicalSize,
              textScaler: TextScaler.linear(shot.textScale),
              devicePixelRatio: shot.dpr,
            ),
            // The boundary is what gets photographed, and its key is what the
            // golden is asked for: the pack cannot say find.byType(MaterialApp)
            // without importing material, and it must not import material.
            child: RepaintBoundary(
              key: shotRootKey,
              child: env.app(shot, shot.build()),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Asset images decode on a real event loop, which the fake async of a
      // widget test never advances. Without this a logo or mascot photographs
      // as a coloured circle - a picture that lies about the app.
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 80)),
      );
      await tester.pump();

      // A layout exception is the most valuable thing a screenshot can tell
      // you, and it is invisible in the pixels. Fail loudly, with the name.
      expect(
        tester.takeException(),
        isNull,
        reason: '${shot.name} threw while rendering',
      );

      await expectLater(
        find.byKey(shotRootKey),
        matchesGoldenFile('$goldenDir/${shot.name}.png'),
      );
    });
  }
}
AGENT_PACK_SHOT_FRAMEWORK_DART_EOF

cat > "$stage/shot_runner_test.dart" <<'AGENT_PACK_SHOT_RUNNER_TEST_DART_EOF'
// ============================================================================
// shim: part of the flutter-builder agent pack. DO NOT EDIT IN A PROJECT.
// Canonical copy: Keshab1997/flutter-builder (agent-pack/shot_runner_test.dart).
// ============================================================================
//
// The entry point the CLI runs:
//
//     python3 tool/local_screenshots.py --list
//     python3 tool/local_screenshots.py --shot settings
//
// All of the work is in shot_framework.dart; everything specific to this app is
// in shot_registry.dart. This file is deliberately two imports and four lines,
// because a project should never need to touch it - and if it does, the next
// installer run takes the change away.
//
// It lives in tool/, not test/, so a plain `flutter test` never discovers it:
// CI stays as fast as it was and cannot go red because a golden moved.
import 'shot_framework.dart';
import 'shot_registry.dart';

void main() {
  runShotSuite(shots: shots, env: env);
}
AGENT_PACK_SHOT_RUNNER_TEST_DART_EOF

cat > "$stage/shot_registry.dart" <<'AGENT_PACK_SHOT_REGISTRY_DART_EOF'
// The one file in tool/screenshots/ that belongs to THIS project.
//
// The installer writes this once, only when it is missing, and never touches it
// again - everything else in this directory is replaced by the pack. So: edit
// it freely, commit it, and treat it as app code.
//
// It has to compile in a project that has just installed the pack, which is why
// the shot list starts empty and the env is a placeholder. Fill both in:
//
//   1. env - the app's real theme (the same function main() gives MaterialApp),
//      the font files it ships, the MethodChannel it talks to Kotlin/Java on,
//      and whatever its widget tests have to initialise first (Hive, a clock).
//   2. shots - one entry per screen worth looking at, named in kebab-case.
//
// A worked example, from a real project:
//
//   final ShotEnv env = ShotEnv(
//     // The app's real shell. Note it is *your* import of Material/Cupertino:
//     // the pack names neither, because Flutter's material move makes
//     // package:flutter/material.dart and package:material_ui/material_ui.dart
//     // different ThemeData types.
//     app: (shot, home) => MaterialApp(
//       theme: shot.dark ? AppTheme.dark() : AppTheme.light(),
//       home: home,
//     ),
//     wrap: (child) => ProviderScope(child: child),
//     fontAssets: const <String, String>{
//       'Inter': 'assets/fonts/Inter-Variable.ttf',
//     },
//     bridgeChannel: AppConstants.channelName,
//     bridgeAnswers: const <String, Object?>{
//       'isListenerEnabled': false,
//       'overlayGranted': false,
//     },
//     setUpAll: () async {
//       Hive.init(Directory.systemTemp.createTempSync('shots').path);
//     },
//   );
//
//   final List<Shot> shots = <Shot>[
//     Shot(name: 'home', build: () => const HomeScreen()),
//     Shot(name: 'settings', build: () => const SettingsScreen()),
//     // The case that catches what a comfortable phone hides.
//     Shot(
//       name: 'settings-narrow',
//       build: () => const SettingsScreen(),
//       logicalSize: const Size(320, 1400),
//     ),
//   ];
import 'shot_framework.dart';

/// No shots yet - add the app's screens here.
final List<Shot> shots = <Shot>[];

/// A pass-through until you fill it in: with no app shell there is no theme, so
/// the first real shot needs the block in the comment above.
final ShotEnv env = ShotEnv(app: (shot, home) => home);
AGENT_PACK_SHOT_REGISTRY_DART_EOF

cat > "$stage/local_screenshots.py" <<'AGENT_PACK_LOCAL_SCREENSHOTS_PY_EOF'
#!/usr/bin/env python3
"""Render app screens to PNGs, locally, in seconds - no device and no CI.

    python3 tool/local_screenshots.py --list
    python3 tool/local_screenshots.py --shot settings
    python3 tool/local_screenshots.py --shot settings,about
    python3 tool/local_screenshots.py                  # every shot
    python3 tool/local_screenshots.py --shot about --open

Why this exists next to tool/see_screen.py: that one asks CI to build the web
app and photograph *routes*. It costs a run, and it cannot reach a screen you
have to tap into - a pushed detail screen, a settings sub-page. This renders the
widget in the test harness with the app's real theme and real fonts, so it takes
about a second, works offline, and photographs exactly what you named.

Two things keep it out of everybody else's way:

  * the runner lives in tool/, not test/, so a plain `flutter test` never
    discovers it - CI stays as fast as it was;
  * the runner is a no-op without --dart-define=SHOTS=1, so nothing starts
    writing PNGs by accident.

It is not a test. It writes throwaway evidence to .agent-screens/local/
(git-ignored), it compares nothing, and no test may read those files back.

Screens are named in tool/screenshots/shot_registry.dart - the one file in that
directory the pack owns no part of.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = "tool/screenshots/shot_runner_test.dart"
REGISTRY = ROOT / "tool" / "screenshots" / "shot_registry.dart"
OUT_DIR = ROOT / ".agent-screens" / "local"


def find_flutter() -> str:
    """PATH first, then the places an SDK normally lives."""
    on_path = shutil.which("flutter")
    if on_path:
        return on_path
    candidates = [
        os.environ.get("FLUTTER_ROOT", ""),
        "/var/tmp/flutter",
        os.path.expanduser("~/flutter"),
        os.path.expanduser("~/development/flutter"),
    ]
    for root in candidates:
        if not root:
            continue
        for candidate in (Path(root) / "bin" / "flutter", Path(root)):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    sys.exit(
        "local_screenshots: flutter not found.\n"
        "  Put it on PATH, set FLUTTER_ROOT, or install it:\n"
        "  bash <(curl -fsSL https://raw.githubusercontent.com/Keshab1997/"
        "flutter-bootstrap/main/setup.sh) --quiet --json"
    )


def known_shots() -> list[str]:
    """Read the registry rather than keeping a second list that can drift."""
    if not REGISTRY.exists():
        sys.exit(
            f"local_screenshots: {REGISTRY.relative_to(ROOT)} is missing. "
            "Re-run the agent-pack installer to create it."
        )
    source = REGISTRY.read_text(encoding="utf-8")
    # Strip comments first: the installed template ships a worked example inside
    # a block comment, and a commented-out shot is not a shot. Whole-line `//`
    # comments only, so a `//` inside a string stays put.
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    source = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("//")
    )
    # `name:` is a plain Dart argument, so either quote style is legal; the
    # registry is user-owned and must not silently drop double-quoted shots.
    return [
        m.group(1) if m.group(1) is not None else m.group(2)
        for m in re.finditer(r"\bname:\s*(?:'([^']+)'|\"([^\"]+)\")", source)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="local_screenshots.py",
        description="Render screens to PNGs locally, in seconds.",
    )
    parser.add_argument(
        "--shot",
        default="",
        help="comma-separated shot names (default: every shot in the registry)",
    )
    parser.add_argument("--list", action="store_true", help="print the shots and exit")
    parser.add_argument(
        "--open",
        action="store_true",
        help="open each PNG with the desktop viewer after rendering",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the PNGs of earlier runs (default: they are overwritten by name)",
    )
    args = parser.parse_args()

    shots = known_shots()
    if args.list:
        if not shots:
            print(
                "no shots yet - add entries to "
                "tool/screenshots/shot_registry.dart"
            )
            return 0
        print("shots:")
        for name in shots:
            print(f"  {name}")
        return 0

    if not shots:
        sys.exit(
            "local_screenshots: the registry has no shots yet. Add one:\n"
            "  Shot(name: 'home', build: () => const HomeScreen()),"
        )

    if args.shot:
        wanted = [s.strip() for s in args.shot.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in shots]
        if unknown:
            sys.exit(
                f"unknown shot(s): {', '.join(unknown)}\n"
                f"known: {', '.join(shots)}"
            )

    # Remember what was already there instead of deleting it: a run that fails
    # is exactly the moment the previous pictures are worth keeping. The stale
    # ones are removed after a run that worked.
    before = {path.name for path in OUT_DIR.glob("*.png")}
    started = time.time()

    flutter = find_flutter()
    command = [
        flutter,
        "test",
        RUNNER,
        "--update-goldens",
        "--dart-define=SHOTS=1",
        f"--dart-define=SHOT={args.shot}",
    ]
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    # What this run wrote, not what happens to be lying in the directory: a
    # `--shot home` run must not print last week's settings screen as if it had
    # just rendered it.
    written = sorted(
        path
        for path in OUT_DIR.glob("*.png")
        if path.name not in before or path.stat().st_mtime >= started - 1
    )
    if not args.keep:
        for stale in sorted(OUT_DIR.glob("*.png")):
            if stale not in written:
                stale.unlink()

    if not written:
        sys.exit(f"local_screenshots: no PNGs in {OUT_DIR} - did the run fail?")

    print("\nrendered:")
    for path in written:
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size // 1024} KB)")
    print("\nnow open them - do not guess what a screen looks like.")

    if args.open:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        for path in written:
            subprocess.run([opener, str(path)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
AGENT_PACK_LOCAL_SCREENSHOTS_PY_EOF

changes=()
conflicts=()
for name in preflight.py ci_watch.py agent_loop.py see_screen.py local_screenshots.py; do
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

# The harness lives in a subdirectory, and one file there is the project's:
# shot_registry.dart names the app's screens, so it is written once when absent
# and never replaced - not with --force either, because a force install must
# not quietly delete a list of screens someone wrote by hand.
shot_changes=()
shot_conflicts=()
registry_new=false
shots_dir="$repo_root/tool/screenshots"
for name in shot_framework.dart shot_runner_test.dart; do
  dest="$shots_dir/$name"
  if [ -e "$dest" ]; then
    if cmp -s "$stage/$name" "$dest"; then
      say "Already current: tool/screenshots/$name"
      continue
    fi
    shot_conflicts+=("$name")
    if [ "$force" = true ]; then
      say "Will replace (backup first): tool/screenshots/$name"
    else
      say "CONFLICT (left untouched): tool/screenshots/$name"
    fi
  else
    say "Will add: tool/screenshots/$name"
  fi
  shot_changes+=("$name")
done
if [ -e "$shots_dir/shot_registry.dart" ]; then
  say "Kept as-is (yours): tool/screenshots/shot_registry.dart"
else
  say "Will add: tool/screenshots/shot_registry.dart (template - list your screens)"
  registry_new=true
fi

if { [ "${#conflicts[@]}" -gt 0 ] || [ "${#shot_conflicts[@]}" -gt 0 ]; } && [ "$force" = false ]; then
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

# .gitignore: keep the pack's throwaway artifacts out of git. The two entries
# are added idempotently, so a rerun with both present says nothing at all.
gitignore_path="$repo_root/.gitignore"
gitignore_action="unchanged"
missing_gitignore=()
[ ! -L "$gitignore_path" ] || fail "$gitignore_path is a symlink; refusing to write through it."
if [ -e "$gitignore_path" ] && [ ! -f "$gitignore_path" ]; then
  fail "$gitignore_path is not a regular file; refusing to write to it."
fi
for entry in ".agent-screens/" ".agent-pack-backups/"; do
  if [ -f "$gitignore_path" ] && grep -qx -F -- "$entry" "$gitignore_path"; then
    continue
  fi
  missing_gitignore+=("$entry")
done
if [ "${#missing_gitignore[@]}" -gt 0 ]; then
  gitignore_action="updated"
fi

if [ "${#changes[@]}" -eq 0 ] && [ "${#shot_changes[@]}" -eq 0 ] \
   && [ "$registry_new" = false ] && [ "$agents_action" = "unchanged" ] \
   && [ "$gitignore_action" = "unchanged" ]; then
  say "Agent pack $PACK_VERSION is already installed; nothing changed."
  exit 0
fi

if [ "$gitignore_action" = "updated" ]; then
  say "Will update: .gitignore (ignore .agent-screens/, .agent-pack-backups/)"
fi

if [ "$dry_run" = true ]; then
  say "Dry run: no files were changed."
  exit 0
fi

if [ "$gitignore_action" = "updated" ]; then
  if [ ! -e "$gitignore_path" ]; then
    : > "$gitignore_path"
  fi
  for entry in "${missing_gitignore[@]}"; do
    # Never glue an entry onto a last line that has no trailing newline.
    if [ -s "$gitignore_path" ] && [ -n "$(tail -c 1 "$gitignore_path")" ]; then
      printf '\n' >> "$gitignore_path"
    fi
    printf '%s\n' "$entry" >> "$gitignore_path"
  done
  say "Updated: .gitignore"
fi

if [ "${#conflicts[@]}" -gt 0 ] || [ "${#shot_conflicts[@]}" -gt 0 ]; then
  backups="$repo_root/.agent-pack-backups"
  [ ! -L "$backups" ] || fail "$backups is a symlink; refusing to write through it."
  [ ! -e "$backups" ] || [ -d "$backups" ] || fail "$backups is not a directory."
  mkdir -p -- "$backups"
  backup_dir="$(mktemp -d "$backups/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXXXX")"
  # Guarded separately: either list can be empty under `set -u` on bash 3.2.
  if [ "${#conflicts[@]}" -gt 0 ]; then
    for name in "${conflicts[@]}"; do
      cp -p -- "$repo_root/tool/$name" "$backup_dir/$name"
    done
  fi
  if [ "${#shot_conflicts[@]}" -gt 0 ]; then
    for name in "${shot_conflicts[@]}"; do
      cp -p -- "$repo_root/tool/screenshots/$name" "$backup_dir/$name"
    done
  fi
  say "Originals backed up to: $backup_dir"
fi

mkdir -p -- "$repo_root/tool"
# Guarded, not `for name in "${changes[@]}"`: when every tool file is already
# current `changes` is an empty array, and macOS ships bash 3.2, where expanding
# an empty array under `set -u` aborts with "changes[@]: unbound variable". That
# is exactly the "only AGENTS.md changed" case, so the update dropped its last
# line and exited non-zero after writing the file.
if [ "${#changes[@]}" -gt 0 ]; then
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
fi

mkdir -p -- "$shots_dir"
if [ "${#shot_changes[@]}" -gt 0 ]; then
  for name in "${shot_changes[@]}"; do
    (
      temp="$(mktemp "$shots_dir/.$name.tmp.XXXXXX")"
      trap 'rm -f -- "$temp"' EXIT
      cp -- "$stage/$name" "$temp"
      chmod 644 "$temp"
      mv -f -- "$temp" "$shots_dir/$name"
    )
    say "Installed: tool/screenshots/$name"
  done
fi
if [ "$registry_new" = true ]; then
  (
    temp="$(mktemp "$shots_dir/.shot_registry.dart.tmp.XXXXXX")"
    trap 'rm -f -- "$temp"' EXIT
    cp -- "$stage/shot_registry.dart" "$temp"
    chmod 644 "$temp"
    mv -f -- "$temp" "$shots_dir/shot_registry.dart"
  )
  say "Installed: tool/screenshots/shot_registry.dart (yours from now on)"
fi

if [ "$agents_action" != "unchanged" ]; then
  say "Installed: AGENTS.md ($agents_action)"
fi

say "Done. Review the changes, then commit tool/ and AGENTS.md."
say "  Before a push :  python3 tool/preflight.py"
say "  After a push  :  python3 tool/ci_watch.py"
say "  Whole loop    :  python3 tool/agent_loop.py -m \"fix(x): what changed\""
say "  A screen      :  python3 tool/local_screenshots.py --list"
say "                   then: python3 tool/local_screenshots.py --shot home"
say "  Screenshots and backups are git-ignored (.agent-screens/, .agent-pack-backups/)."
say "  Pack docs     :  ${RAW_BASE}/README.md"
if [ -e "$repo_root/.agent-pack-backups" ]; then
  say "Note: .agent-pack-backups/ holds replaced files (git-ignored)."
fi
