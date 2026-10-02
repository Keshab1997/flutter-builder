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
