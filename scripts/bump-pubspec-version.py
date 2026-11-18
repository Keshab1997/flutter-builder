#!/usr/bin/env python3
"""Compute the next pubspec `version:` for a release.

It prints `name=…`/`changed=…` lines for GITHUB_OUTPUT and exits non-zero with
an actionable message when the current version cannot be bumped safely. It
never rewrites the file and never auto-commits: bump in the pull request that
precedes the release (see publish-release.yml) and commit through the GitHub
API, so a bad regex can't mangle a pubspec.

Accepts the Flutter form `MAJOR.MINOR.PATCH+BUILD` (the `+BUILD` is the Android
versionCode and is required for `build`/`patch` bumps). On `major`, `minor` and
`patch` bumps any prerelease suffix (e.g. `-beta.1`) is dropped; `build` and
`none` keep it.
"""
import argparse
import os
import re
import sys

VERSION_RE = re.compile(
    r"^\s*version:\s*['\"]?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?P<pre>[-.][0-9A-Za-z.-]+)?"
    r"(?:\+(?P<build>\d+))?['\"]?\s*$",
    re.MULTILINE,
)


def find_version(text: str):
    m = VERSION_RE.search(text)
    if not m:
        sys.exit(
            "pubspec.yaml has no parseable `version: X.Y.Z+N` line. "
            "Add one, e.g. `version: 1.0.0+1`, or run with bump-type: none."
        )
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pubspec", default="pubspec.yaml")
    ap.add_argument("--bump", required=True, choices=["major", "minor", "patch", "build", "none"])
    args = ap.parse_args()

    try:
        text = open(args.pubspec, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"cannot read {args.pubspec}: {e}")

    m = find_version(text)
    major, minor, patch = int(m["major"]), int(m["minor"]), int(m["patch"])
    build = int(m["build"]) if m["build"] else None
    pre = m["pre"] or ""

    current = f"{major}.{minor}.{patch}{pre}" + (f"+{build}" if build is not None else "")

    if args.bump == "none":
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as f:
                f.write(f"name={current}\nchanged=false\n")
        print(f"name={current}")
        print(f"changed=false")
        print(f"reason=bump-type=none, publishing {current} as-is")
        return

    if args.bump in ("patch", "build") and build is None:
        sys.exit(
            f"bump-type={args.bump} needs a build number (version: {major}.{minor}.{patch}+N). "
            "SpeakEasy-style pubspecs have it; add `+N` or use minor/major."
        )

    if args.bump == "major":
        major, minor, patch = major + 1, 0, 0
        pre = ""  # a numbered release drops any prerelease suffix
    elif args.bump == "minor":
        minor, patch = minor + 1, 0
        pre = ""
    elif args.bump == "patch":
        patch += 1
        pre = ""

    if build is not None:
        build += 1  # every bump advances versionCode; a release is never rebuilt
    new = f"{major}.{minor}.{patch}{pre}" + (f"+{build}" if build is not None else "")

    if new == current:
        sys.exit("computed version equals the current one — refusing to commit a no-op")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"name={new}\nchanged=true\n")
    print(f"::notice::pubspec version {m.group(0).strip()} -> {new}")
    print(f"name={new}")
    print("changed=true")


if __name__ == "__main__":
    main()
