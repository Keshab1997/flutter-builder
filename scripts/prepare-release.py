#!/usr/bin/env python3
"""Keep every release-coupled pin in this repository on one tag.

A release here means editing the same version string in ~25 places (the
installer's DEFAULT_REF, the workflow checkout refs, the example caller pins,
the agent-pack start marker, the docs, the test constants ...). Doing it by
hand is how one lagging pin sneaks into a release, and a single lagging pin
means some consumer installs a mix of two releases.

This helper is the one place that knows where those pins live:

    python3 scripts/prepare-release.py --check
        Read the current version from PACK_VERSION in
        scripts/install-agent-pack.sh and verify every release-coupled pin
        matches it. Exit 0 when consistent, exit 1 listing every drifted
        file/location. Also re-checks the embedded installer payload via
        scripts/sync-agent-pack.py --check.

    python3 scripts/prepare-release.py --version v1.17.0 [--dry-run]
        Rewrite every release-coupled occurrence of the *current* version to
        the new tag (historical "introduced in v1.10.0" references are
        different strings and are left untouched), then re-sync the embedded
        installer payload via scripts/sync-agent-pack.py. --dry-run prints
        what would change and writes nothing.

Safety: this tool only edits files under --root. It never runs git commit,
git tag, git push, or gh release - committing, tagging, and releasing remain
the human's deliberate step.

Stdlib only, Python >= 3.8.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# v1.2.3 - the exact shape every release tag in this repository takes.
VERSION = r"v[0-9]+\.[0-9]+\.[0-9]+"
CURRENT_TAG = re.compile(r"^" + VERSION + r"$")

INSTALLER = "scripts/install-agent-pack.sh"
TEMPLATE = "agent-pack/AGENTS.template.md"
PROSE_FILES = ("AGENTS.md", "README.md", "docs/PLAY_INTERNAL_TESTING.md")
WORKFLOW_DIRS = (".github/workflows", "examples/project-workflows")
TEST_DIR = "tests"
REQUIRED_FILES = (
    INSTALLER, TEMPLATE,
    "scripts/install.sh", "scripts/bump-ref.sh", "scripts/bump-consumers.sh",
    "scripts/sync-agent-pack.py", "tests/test_agent_pack.py",
) + PROSE_FILES

PACK_VERSION_RE = re.compile(rf"^PACK_VERSION=({VERSION})[ \t]*$", re.M)


def _rules() -> dict:
    """file -> [(label, regex-with-one-group, required_match)] for pins.

    A required rule must match at least once and every match must carry the
    current version; a plain rule (required=False) only constrains matches
    that exist, so heterogeneous files (some workflows carry no pins at all)
    do not false-positive.
    """
    curl = rf"flutter-builder/({VERSION})/scripts/"
    return {
        INSTALLER: [
            ("PACK_VERSION", re.compile(rf"^PACK_VERSION=({VERSION})[ \t]*$", re.M), True),
            (f"installer curl example", re.compile(f"{curl}install-agent-pack\\.sh"), True),
            ("embedded agent-pack start marker",
             re.compile(rf"agent-pack:start ({VERSION})"), True),
        ],
        TEMPLATE: [
            ("agent-pack start marker", re.compile(rf"agent-pack:start ({VERSION})"), True),
        ],
        "scripts/install.sh": [
            ("DEFAULT_REF", re.compile(rf"^DEFAULT_REF=({VERSION})[ \t]*$", re.M), True),
            (f"installer curl example", re.compile(f"{curl}install\\.sh"), True),
            ("usage default tag", re.compile(rf"\(default: ({VERSION})\)"), True),
        ],
        "scripts/bump-ref.sh": [
            ("DEFAULT_REF", re.compile(rf"^DEFAULT_REF=({VERSION})[ \t]*$", re.M), True),
            (f"bump-ref curl example", re.compile(f"{curl}bump-ref\\.sh"), True),
            ("usage/error example tag", re.compile(rf"\(e\.g\. ({VERSION})\)"), True),
            ("usage default tag", re.compile(rf"\(default: ({VERSION})\)"), True),
        ],
        "scripts/bump-consumers.sh": [
            ("comment example --ref tag",
             re.compile(rf"bump-consumers\.sh --ref ({VERSION})"), True),
            ("usage/error example tag", re.compile(rf"\(e\.g\. ({VERSION})\)"), True),
        ],
        "tests/test_agent_pack.py": [
            ("VERSION constant", re.compile(rf'^VERSION = "({VERSION})"[ \t]*$', re.M), True),
        ],
    }


# Workflow YAMLs are heterogeneous: a caller pin, a checkout ref, or a usage
# example anywhere in them must carry the current tag, but a file with none
# of them (a pure app workflow) is fine.
WORKFLOW_RULES = [
    ("workflow caller pin",
     re.compile(rf"Keshab1997/flutter-builder/[^@\r\n]+@({VERSION})"), False),
    ("checkout ref", re.compile(rf"ref:[ \t]*({VERSION})[ \t]*$", re.M), False),
    ("usage example tag", re.compile(rf"\(e\.g\. ({VERSION})\)"), False),
]


def coupled_files(root: Path) -> list:
    """Every file a release touches, resolved against --root."""
    files = [root / name for name in
             (INSTALLER, TEMPLATE, "scripts/install.sh", "scripts/bump-ref.sh",
              "scripts/bump-consumers.sh", "tests/test_agent_pack.py")]
    files += [root / name for name in PROSE_FILES]
    for rel in WORKFLOW_DIRS:
        files += sorted((root / rel).glob("*.yml"))
    files += sorted((root / TEST_DIR).glob("test_*.py"))
    return files


def rules_for(root: Path, rel: str) -> list:
    table = _rules()
    if rel in table:
        return table[rel]
    for workdir in WORKFLOW_DIRS:
        if rel.startswith(workdir + "/"):
            return WORKFLOW_RULES
    return []


def prose(rel: str) -> bool:
    return rel in PROSE_FILES


def current_version(root: Path):
    """(version, drift_line) from the installer's PACK_VERSION, or None."""
    path = root / INSTALLER
    if not path.is_file():
        return None, f"missing {INSTALLER}"
    match = PACK_VERSION_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        return None, f"PACK_VERSION not found in {INSTALLER}"
    return match.group(1), None


def check(root: Path) -> int:
    version, problem = current_version(root)
    print(f"prepare-release: current release is {version or '?'} "
          f"(from {INSTALLER})")
    if problem:
        print(f"prepare-release: ERROR: {problem}")
        return 1

    drifted = []          # (rel, label, found, line)
    checked = 0
    for path in coupled_files(root):
        rel = path.relative_to(root).as_posix()
        if not path.is_file():
            if rel in REQUIRED_FILES:
                drifted.append((rel, "file", "missing", 0))
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        checked += 1
        rules = rules_for(root, rel)
        if rules:
            for label, regex, required in rules:
                matches = list(regex.finditer(text))
                if not matches:
                    if required:
                        drifted.append((rel, label, "(no match)", 0))
                    continue
                for match in matches:
                    if match.group(1) != version:
                        line = lines[: match.start()].count("\n") + 1
                        drifted.append((rel, label, match.group(1), line))
        elif prose(rel) and version not in text:
            drifted.append((rel, "current pin reference", "(none found)", 0))

    # Embedded installer payload parity: the installer carries a copy of
    # agent-pack/AGENTS.template.md (with the start marker), so its sync check
    # is part of "all pins consistent".
    sync = subprocess.run(
        [sys.executable, str(root / "scripts" / "sync-agent-pack.py"), "--check"],
        capture_output=True, text=True)
    if sync.returncode != 0:
        for out_line in (sync.stdout + sync.stderr).splitlines():
            if out_line.strip():
                drifted.append((INSTALLER, "embedded payload drift", out_line.strip(), 0))

    if drifted:
        for rel, label, found, line in drifted:
            where = f" (line {line})" if line else ""
            print(f"prepare-release: DRIFT in {rel}: [{label}] expected "
                  f"{version}, found {found}{where}")
        bad_files = sorted({rel for rel, _, _, _ in drifted})
        print(f"prepare-release: {len(drifted)} drifted location(s) across "
              f"{len(bad_files)} file(s); current release is {version}. "
              f"Bump with: python3 scripts/prepare-release.py --version <tag>")
        return 1

    print(f"prepare-release: checked {checked} file(s); all release pins "
          f"match {version} (embedded payload in sync).")
    return 0


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".prepare-release-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _replace_version(text: str, old: str, new: str) -> str:
    # Whole-token replacement: v1.16.1 must not match inside v1.16.10, and a
    # letter before the v (part of another word) is not a version.
    pattern = re.compile(rf"(?<![\w.]){re.escape(old)}(?!\d)")
    return pattern.sub(new, text)


def _version_tuple(tag: str):
    return tuple(int(part) for part in tag[1:].split("."))


def remap(root: Path, new: str, dry_run: bool) -> int:
    version, problem = current_version(root)
    if problem:
        print(f"prepare-release: ERROR: {problem}")
        return 1
    if new == version:
        print(f"prepare-release: already at {version}; nothing to do.")
        return 0

    print(f"prepare-release: {'dry run: ' if dry_run else ''}"
          f"{version} -> {new}")
    changed = []
    for path in coupled_files(root):
        rel = path.relative_to(root).as_posix()
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        new_text = _replace_version(text, version, new)
        if new_text != text:
            count = text.count(version)
            changed.append((rel, count))
            if not dry_run:
                _atomic_write(path, new_text)

    if not changed:
        print(f"prepare-release: no occurrence of {version} left to move; "
              f"nothing to do.")
        return 0

    for rel, count in changed:
        print(f"prepare-release:   {rel} ({count} occurrence(s))")
    if dry_run:
        print(f"prepare-release: dry run: {len(changed)} file(s) would change; "
              f"nothing was written.")
        print(_reminder())
        return 0

    # Re-embed the (now updated) agent-pack/ files into the self-contained
    # installer so the embedded start marker matches too.
    sync = subprocess.run(
        [sys.executable, str(root / "scripts" / "sync-agent-pack.py")],
        capture_output=True, text=True)
    for out_line in (sync.stdout + sync.stderr).splitlines():
        if out_line.strip():
            print(f"prepare-release: {out_line.strip()}")
    parity = subprocess.run(
        [sys.executable, str(root / "scripts" / "sync-agent-pack.py"), "--check"],
        capture_output=True, text=True)
    if parity.returncode != 0:
        for out_line in (parity.stdout + parity.stderr).splitlines():
            if out_line.strip():
                print(f"prepare-release: {out_line.strip()}")
        print(f"prepare-release: ERROR: embedded payload is out of sync after "
              f"the bump; fix before tagging.")
        return 1

    print(f"prepare-release: rewrote {len(changed)} file(s) to {new}.")
    print(_reminder())
    return 0


def _reminder() -> str:
    return ("prepare-release: done. Committing, tagging, pushing, and "
            "creating the release are deliberately NOT done here - they stay "
            "your step: git add/commit, git tag <tag>, git push --tags, then "
            "publish the GitHub release.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check or bump every release-coupled pin in this repo.")
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--root", default=str(default_root),
                        help="repository root (default: the repo containing "
                             "this script)")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true",
                        help="verify every release pin matches PACK_VERSION")
    action.add_argument("--version", metavar="TAG",
                        help="bump every release pin to TAG (vX.Y.Z)")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --version: print what would change, write nothing")
    parser.add_argument("--allow-downgrade", action="store_true",
                        help="allow --version to an older tag")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not (root / INSTALLER).is_file():
        print(f"prepare-release: {root} does not look like the repository root "
              f"(missing {INSTALLER})")
        return 1

    if args.check:
        return check(root)

    if not CURRENT_TAG.match(args.version):
        print(f"prepare-release: invalid tag {args.version!r}; want vX.Y.Z "
              f"(for example v1.17.0)")
        return 1
    version, problem = current_version(root)
    if problem:
        print(f"prepare-release: ERROR: {problem}")
        return 1
    if _version_tuple(args.version) < _version_tuple(version) \
            and not args.allow_downgrade:
        print(f"prepare-release: refusing downgrade {version} -> "
              f"{args.version} (pass --allow-downgrade to force)")
        return 1
    return remap(root, args.version, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
