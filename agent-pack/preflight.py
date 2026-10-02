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
