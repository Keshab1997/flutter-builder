#!/usr/bin/env python3
"""check_toolchain.py — one Flutter pin, three Gradle numbers, checked together.

Why this exists
---------------
A consumer's APK build failed with:

    Your project's Android Gradle Plugin version (9.1.0) is lower than
    Flutter's minimum supported version (9.1.1)

Nothing in that message points at the actual cause: `.fvmrc` had moved to a new
Flutter while `android/` still carried the old template's AGP, Gradle and
Kotlin versions. Three files, one dependency between them, and the mismatch
only showed up after a full Gradle configuration run.

This script reads the pin and the three numbers and refuses to agree with a
split. It is safe to run in a bare sandbox (no SDK, no Gradle):

    python3 scripts/check_toolchain.py                    # repo root
    python3 scripts/check_toolchain.py --root ../my_app
    python3 scripts/check_toolchain.py --json
    FLUTTER_BUILDER_ROOT=../my_app python3 scripts/check_toolchain.py

Where the floors come from
--------------------------
1. The pinned Flutter SDK, when one is reachable (`$FLUTTER_ROOT`, then
   `flutter` on PATH): `packages/flutter_tools/gradle/src/main/kotlin/
   DependencyVersionChecker.kt` holds errorAGPVersion, warnAGPVersion,
   errorGradleVersion, warnGradleVersion and errorKGPVersion.
2. Otherwise the built-in table below, keyed by Flutter version.

When you bump a consumer to a newer Flutter, add its row here (or just let CI
read it from the SDK). An unknown version is a FAIL, never a pass: a silent
"looks fine" is how this broke the first time.

Exit status: 0 = consistent, 1 = at least one problem or unknown version.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(
    os.environ.get("FLUTTER_BUILDER_ROOT", "")
    or pathlib.Path(__file__).resolve().parent.parent)

# Flutter release -> the floors it enforces (error = build stops, warn = noise).
# Measured from flutter/flutter's DependencyVersionChecker.kt at each release.
KNOWN_FLUTTER: dict[str, dict[str, str]] = {
    "3.50.0": {
        "agp_min": "9.1.1",
        "agp_warn": "9.3.1",
        "gradle_min": "9.3.1",
        "gradle_warn": "9.5.0",
        "kotlin_min": "2.4.10",
    },
}


class V(tuple):
    """A dotted version that compares numerically, not as a string."""

    def __new__(cls, text: str):
        parts = [int(p) for p in re.findall(r"\d+", text)[:3]]
        while len(parts) < 3:
            parts.append(0)
        return super().__new__(cls, parts)

    def __str__(self) -> str:  # pragma: no cover - display only
        return ".".join(str(p) for p in self)


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def flutter_pin(root: pathlib.Path) -> tuple[str | None, str]:
    """(version, where it came from)."""
    for name in (".fvmrc", "fvm_config.json"):
        text = read_text(root / name)
        if text:
            match = re.search(r'"flutter"\s*:\s*"([^"]+)"', text)
            if match:
                return match.group(1), name

    # A repo without .fvmrc is still checkable while an SDK is around.
    flutter = shutil.which("flutter")
    if flutter:
        try:
            out = subprocess.run([flutter, "--version"], capture_output=True,
                                 text=True, timeout=120).stdout
            match = re.search(r"Flutter (\d+\.\d+\.\d+)", out)
            if match:
                return match.group(1), "flutter --version"
        except (OSError, subprocess.SubprocessError):
            pass
    return None, "not found"


def agp_version(root: pathlib.Path) -> str | None:
    text = read_text(root / "android/settings.gradle.kts")
    if not text:
        text = read_text(root / "android/settings.gradle")
    match = re.search(
        r'com\.android\.application"?\)?\s*version\s*"?([\d.]+)"?', text)
    return match.group(1) if match else None


def kotlin_version(root: pathlib.Path) -> str | None:
    text = read_text(root / "android/settings.gradle.kts")
    if not text:
        text = read_text(root / "android/settings.gradle")
    match = re.search(
        r'org\.jetbrains\.kotlin\.android"?\)?\s*version\s*"?([\d.]+)"?', text)
    return match.group(1) if match else None


def gradle_version(root: pathlib.Path) -> str | None:
    text = read_text(root / "android/gradle/wrapper/gradle-wrapper.properties")
    match = re.search(r"gradle-([\d.]+)-(?:all|bin)\.zip", text)
    return match.group(1) if match else None


def sdk_root() -> pathlib.Path | None:
    """$FLUTTER_ROOT first (what CI sets), then whatever `flutter` resolves to."""
    root = os.environ.get("FLUTTER_ROOT", "").strip()
    if root and (pathlib.Path(root) / "bin/flutter").exists():
        return pathlib.Path(root)
    flutter = shutil.which("flutter")
    if flutter:
        return pathlib.Path(flutter).resolve().parent.parent
    return None


def sdk_floor(version: str) -> dict[str, str] | None:
    """Ask the pinned Flutter SDK what it enforces."""
    sdk = sdk_root()
    if sdk is None:
        return None
    text = read_text(sdk / ("packages/flutter_tools/gradle/src/main/kotlin/"
                            "DependencyVersionChecker.kt"))
    if not text:
        return None

    def grab(pattern: str) -> str | None:
        match = re.search(pattern, text)
        return match.group(1) if match else None

    found = {
        "agp_min": grab(r"errorAGPVersion[^=]*=\s*AndroidPluginVersion\(([\d, ]+)\)"),
        "agp_warn": grab(r"warnAGPVersion[^=]*=\s*AndroidPluginVersion\(([\d, ]+)\)"),
        "gradle_min": grab(r"errorGradleVersion[^=]*=\s*Version\(([\d, ]+)\)"),
        "gradle_warn": grab(r"warnGradleVersion[^=]*=\s*Version\(([\d, ]+)\)"),
        "kotlin_min": grab(r"errorKGPVersion[^=]*=\s*Version\(([\d, ]+)\)"),
    }
    if not all(found.values()):
        return None
    dots = lambda s: ".".join(p.strip() for p in s.split(","))  # noqa: E731
    return {k: dots(v) for k, v in found.items()} | {"source": f"Flutter SDK at {sdk}"}


def check(root: pathlib.Path) -> dict:
    flutter, flutter_src = flutter_pin(root)
    agp, kotlin, gradle = (agp_version(root), kotlin_version(root),
                           gradle_version(root))

    floor = (sdk_floor(flutter) if flutter else None) or (
        dict(KNOWN_FLUTTER[flutter], source="built-in table")
        if flutter in KNOWN_FLUTTER else None)

    problems: list[str] = []
    notes: list[str] = []

    # A pin the project does not keep is not a mismatch. Most repos here never
    # commit .fvmrc and let the workflow's flutter-channel decide, and the
    # builder can generate android/ on the fly — failing those would break
    # every consumer for a file it chooses not to have.
    pinned = (root / ".fvmrc").exists() or (root / ".fvm").is_dir()
    if flutter is None:
        message = ('no Flutter version: no "flutter" key in .fvmrc and no '
                   "flutter on PATH")
        # Nothing to compare against when the project keeps no pin at all: the
        # workflow still works, so say so and move on instead of failing.
        (problems if pinned else notes).append(
            message if pinned else "no Flutter pin in this project, so the "
            "Android floors were not checked")
    has_android_settings = ((root / "android/settings.gradle.kts").exists()
                            or (root / "android/settings.gradle").exists())
    if agp is None and has_android_settings:
        problems.append("cannot read AGP from android/settings.gradle(.kts)")
    if gradle is None:
        problems.append("cannot read Gradle from the wrapper properties")
    if flutter and floor is None:
        problems.append(
            f"no constraint table for Flutter {flutter} — add it to "
            "KNOWN_FLUTTER in scripts/check_toolchain.py")

    if floor and agp and gradle:
        if V(agp) < V(floor["agp_min"]):
            problems.append(
                f"AGP {agp} is below Flutter {flutter}'s minimum "
                f"{floor['agp_min']} — the build stops before compiling any Dart")
        elif V(agp) < V(floor["agp_warn"]):
            notes.append(f"AGP {agp} works but is below the warn version "
                         f"{floor['agp_warn']}")
        if V(gradle) < V(floor["gradle_min"]):
            problems.append(
                f"Gradle {gradle} is below Flutter {flutter}'s minimum "
                f"{floor['gradle_min']}")
        elif V(gradle) < V(floor["gradle_warn"]):
            notes.append(f"Gradle {gradle} works but is below the warn version "
                         f"{floor['gradle_warn']}")
        if kotlin and V(kotlin) < V(floor["kotlin_min"]):
            problems.append(
                f"Kotlin plugin {kotlin} is below Flutter {flutter}'s minimum "
                f"{floor['kotlin_min']}")

        # JDK note: AGP >= 9.2 lints Kotlin sources and needs a JDK 21 runtime;
        # on 17 it dies with NoSuchMethodError: List.removeLast().
        if V(agp) >= V("9.2.0"):
            notes.append("AGP >= 9.2 lints plugin sources: the Gradle JVM must "
                         "be JDK 21 (pass java-version: \"21\" to the workflow)")

    return {
        "root": str(root),
        "flutter": flutter,
        "flutter_source": flutter_src,
        "agp": agp,
        "gradle": gradle,
        "kotlin": kotlin,
        "constraints": floor,
        "problems": problems,
        "notes": notes,
        "ok": not problems,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--root", default=None,
                        help="project to check (default: $FLUTTER_BUILDER_ROOT "
                             "or this repo)")
    args = parser.parse_args()

    global ROOT
    if args.root:
        ROOT = pathlib.Path(args.root).expanduser().resolve()
    if not (ROOT / "android").is_dir():
        print(f"toolchain: {ROOT} has no android/ directory", file=sys.stderr)
        return 1

    result = check(ROOT)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"flutter {result['flutter'] or '?'} "
              f"({result['flutter_source']}) in {ROOT}")
        print(f"  AGP     {result['agp'] or '?'}")
        print(f"  Gradle  {result['gradle'] or '?'}")
        print(f"  Kotlin  {result['kotlin'] or '?'}")
        floor = result["constraints"]
        if floor:
            print(f"  floors from {floor.get('source', '?')}: "
                  f"AGP >= {floor['agp_min']}, Gradle >= {floor['gradle_min']}, "
                  f"Kotlin >= {floor['kotlin_min']}")
        for note in result["notes"]:
            print(f"  note: {note}")
        for problem in result["problems"]:
            print(f"  FAIL {problem}")
        print("toolchain: " + ("consistent" if result["ok"]
                               else f"{len(result['problems'])} problem(s)"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
