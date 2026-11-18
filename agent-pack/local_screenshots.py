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
