#!/usr/bin/env python3
"""Keep an app's `pulse.json` (`app_pulse_kit`) in sync with `pubspec.yaml`.

Apps that adopt `app_pulse_kit` host a small JSON config (typically `pulse.json`
at the repo root) so remote updates, maintenance screens, notices, and feature
flags work at zero server cost. During a release it is easy to bump
`pubspec.yaml` and forget to update `update.latestVersion` /
`update.latestBuildNumber` in `pulse.json`.

Usage:
    python3 scripts/sync-pulse-config.py
        Read `version: X.Y.Z+N` from `pubspec.yaml` and update `pulse.json` in
        place (only `update.latestVersion` and `update.latestBuildNumber` are
        changed; maintenance, notices, flags, and store URLs stay untouched).
        Exits 0 cleanly if `pulse.json` does not exist yet.

    python3 scripts/sync-pulse-config.py --check
        Verify `pulse.json` matches `pubspec.yaml`. Exit 0 if in sync (or if
        `pulse.json` is absent), exit 1 if drifted.

    python3 scripts/sync-pulse-config.py --init
        Create a starter `pulse.json` seeded from `pubspec.yaml`.

Stdlib only, Python >= 3.8.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

VERSION_RE = re.compile(
    r"^\s*version:\s*['\"]?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?P<pre>[-.][0-9A-Za-z.-]+)?"
    r"(?:\+(?P<build>\d+))?['\"]?\s*$",
    re.MULTILINE,
)

RAW_VERSION_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?P<pre>-[0-9A-Za-z.-]+)?"
    r"(?:\+(?P<build>\d+))?$"
)


def parse_version_string(raw: str) -> tuple[str, int | None]:
    """Parse `1.2.3+12` (or `v1.2.3-beta.1+4`) into `(version_name, build)`."""
    m = RAW_VERSION_RE.match(raw.strip())
    if not m:
        raise ValueError(f"Invalid version string: {raw!r} (expected X.Y.Z or X.Y.Z+N)")
    pre = m.group("pre") or ""
    version_name = f"{int(m['major'])}.{int(m['minor'])}.{int(m['patch'])}{pre}"
    build = int(m["build"]) if m["build"] is not None else None
    return version_name, build


def read_pubspec_version(pubspec_path: Path) -> tuple[str, int | None]:
    """Read `version: X.Y.Z+N` from `pubspec.yaml`."""
    if not pubspec_path.is_file():
        raise FileNotFoundError(f"pubspec not found: {pubspec_path}")
    text = pubspec_path.read_text(encoding="utf-8")
    m = VERSION_RE.search(text)
    if not m:
        raise ValueError(
            f"{pubspec_path} has no parseable `version: X.Y.Z+N` line"
        )
    pre = m.group("pre") or ""
    version_name = f"{int(m['major'])}.{int(m['minor'])}.{int(m['patch'])}{pre}"
    build = int(m["build"]) if m["build"] is not None else None
    return version_name, build


def starter_pulse_config(version_name: str, build: int | None) -> dict[str, object]:
    """Return a clean starter `pulse.json` compatible with `app_pulse_kit`."""
    update: dict[str, object] = {
        "latestVersion": version_name,
        "minSupportedVersion": version_name,
        "androidUrl": "",
        "whatsNew": [],
    }
    if build is not None:
        update["latestBuildNumber"] = build
        update["minSupportedBuildNumber"] = 1
    return {
        "schemaVersion": 1,
        "update": update,
        "maintenance": {
            "enabled": False,
            "allowRetry": True,
        },
        "notices": [],
        "flags": {},
    }


def _emit_output(changed: bool, version_name: str, build: int | None) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
            fh.write(f"latest_version={version_name}\n")
            if build is not None:
                fh.write(f"latest_build={build}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Sync app_pulse_kit pulse.json version fields with pubspec.yaml."
    )
    ap.add_argument("--root", default=".", help="Flutter app root directory (default: .)")
    ap.add_argument("--pubspec", default=None, help="Path to pubspec.yaml (default: <root>/pubspec.yaml)")
    ap.add_argument("--pulse", default=None, help="Path to pulse.json (default: <root>/pulse.json)")
    ap.add_argument("--version", default=None, help="Explicit version X.Y.Z[+N] instead of reading pubspec.yaml")
    ap.add_argument("--min-supported", default=None, help="Optionally set update.minSupportedVersion[+Build]")
    ap.add_argument("--whats-new", action="append", default=None, help="Replace update.whatsNew (repeatable)")
    ap.add_argument("--init", action="store_true", help="Create pulse.json if missing")
    ap.add_argument("--check", action="store_true", help="Exit 1 if pulse.json is out of sync; do not write")
    ap.add_argument("--dry-run", action="store_true", help="Show planned changes without writing")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    pubspec_path = Path(args.pubspec) if args.pubspec else root / "pubspec.yaml"
    pulse_path = Path(args.pulse) if args.pulse else root / "pulse.json"

    try:
        if args.version:
            version_name, build = parse_version_string(args.version)
        else:
            version_name, build = read_pubspec_version(pubspec_path)
    except (OSError, ValueError) as exc:
        print(f"sync-pulse-config: ERROR: {exc}", file=sys.stderr)
        return 2

    if not pulse_path.is_file():
        if args.init:
            data = starter_pulse_config(version_name, build)
            rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            if args.dry_run or args.check:
                print(f"sync-pulse-config: would create {pulse_path} (v{version_name}"
                      + (f"+{build}" if build is not None else "") + ")")
                return 1 if args.check else 0
            pulse_path.parent.mkdir(parents=True, exist_ok=True)
            pulse_path.write_text(rendered, encoding="utf-8")
            print(f"sync-pulse-config: created {pulse_path} (latestVersion={version_name}"
                  + (f", latestBuildNumber={build}" if build is not None else "") + ")")
            _emit_output(True, version_name, build)
            return 0
        print(f"sync-pulse-config: {pulse_path} not found — skipping.")
        _emit_output(False, version_name, build)
        return 0

    try:
        raw_text = pulse_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"sync-pulse-config: ERROR: cannot parse {pulse_path}: {exc}", file=sys.stderr)
        return 2

    if not isinstance(data, dict):
        print(f"sync-pulse-config: ERROR: {pulse_path} root must be a JSON object", file=sys.stderr)
        return 2

    update = data.get("update")
    if update is None:
        update = {}
        data["update"] = update
    if not isinstance(update, dict):
        print(f"sync-pulse-config: ERROR: {pulse_path} 'update' field must be a JSON object", file=sys.stderr)
        return 2

    changes: list[str] = []

    if update.get("latestVersion") != version_name:
        changes.append(f"latestVersion: {update.get('latestVersion')!r} -> {version_name!r}")
        update["latestVersion"] = version_name

    if build is not None and update.get("latestBuildNumber") != build:
        changes.append(f"latestBuildNumber: {update.get('latestBuildNumber')!r} -> {build!r}")
        update["latestBuildNumber"] = build

    if args.min_supported:
        try:
            min_ver, min_build = parse_version_string(args.min_supported)
        except ValueError as exc:
            print(f"sync-pulse-config: ERROR: {exc}", file=sys.stderr)
            return 2
        if update.get("minSupportedVersion") != min_ver:
            changes.append(
                f"minSupportedVersion: {update.get('minSupportedVersion')!r} -> {min_ver!r}"
            )
            update["minSupportedVersion"] = min_ver
        if min_build is not None and update.get("minSupportedBuildNumber") != min_build:
            changes.append(
                f"minSupportedBuildNumber: {update.get('minSupportedBuildNumber')!r} -> {min_build!r}"
            )
            update["minSupportedBuildNumber"] = min_build

    if args.whats_new is not None:
        cleaned = [item.strip() for item in args.whats_new if item.strip()]
        if update.get("whatsNew") != cleaned:
            changes.append(f"whatsNew: {len(cleaned)} item(s)")
            update["whatsNew"] = cleaned

    if not changes:
        print(f"sync-pulse-config: {pulse_path.name} already in sync (v{version_name}"
              + (f"+{build}" if build is not None else "") + ").")
        _emit_output(False, version_name, build)
        return 0

    summary = ", ".join(changes)
    if args.check:
        print(f"sync-pulse-config: OUT OF SYNC ({summary})")
        return 1

    if args.dry_run:
        print(f"sync-pulse-config: [dry-run] would update {pulse_path.name}: {summary}")
        return 0

    rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    pulse_path.write_text(rendered, encoding="utf-8")
    print(f"sync-pulse-config: updated {pulse_path.name} ({summary})")
    _emit_output(True, version_name, build)
    return 0


if __name__ == "__main__":
    sys.exit(main())
