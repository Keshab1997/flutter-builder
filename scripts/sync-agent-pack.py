#!/usr/bin/env python3
"""Embed the canonical agent-pack files into scripts/install-agent-pack.sh.

The installer has to stay self-contained (`curl … | bash` cannot fetch a second
file), so it carries a copy of every tool inside a quoted heredoc. Two copies
mean drift, and drift means a project installs something other than what the
repository reviews - which is why tests/test_agent_pack.py compares them byte
for byte, and why editing both by hand is the wrong habit.

Edit `agent-pack/`, then run this:

    python3 scripts/sync-agent-pack.py           # rewrite the embedded payload
    python3 scripts/sync-agent-pack.py --check   # exit 1 when out of sync (CI-safe)

Only the bodies of the five heredocs change; nothing else in the installer is
touched.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-agent-pack.sh"
PACK = ROOT / "agent-pack"

# canonical file -> heredoc token in the installer
PAYLOAD = {
    "preflight.py": "AGENT_PACK_PREFLIGHT_PY_EOF",
    "ci_watch.py": "AGENT_PACK_CI_WATCH_PY_EOF",
    "agent_loop.py": "AGENT_PACK_AGENT_LOOP_PY_EOF",
    "see_screen.py": "AGENT_PACK_SEE_SCREEN_PY_EOF",
    "AGENTS.template.md": "AGENT_PACK_AGENTS_MD_EOF",
}


def heredoc_pattern(token: str) -> re.Pattern[str]:
    return re.compile(rf"(<<'{re.escape(token)}'\n)(?P<body>.*?)(^{re.escape(token)}$)",
                      re.S | re.M)


def read_canonical(name: str) -> str:
    text = (PACK / name).read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    return text


def plan() -> list[tuple[str, str, str]]:
    """Return [(installer_text, token, desired_body)] with everything checked."""
    installer = INSTALLER.read_text(encoding="utf-8")
    out = []
    for name, token in PAYLOAD.items():
        pattern = heredoc_pattern(token)
        if not pattern.search(installer):
            raise SystemExit(f"sync-agent-pack: heredoc {token} is missing from {INSTALLER}")
        out.append((name, token, read_canonical(name)))
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="report drift and exit 1 instead of rewriting")
    args = parser.parse_args(argv[1:])

    installer = INSTALLER.read_text(encoding="utf-8")
    drifted: list[str] = []
    for name, token, body in plan():
        pattern = heredoc_pattern(token)
        match = pattern.search(installer)
        current = match.group("body")
        if current == body:
            continue
        drifted.append(name)
        if not args.check:
            installer = pattern.sub(lambda m: m.group(1) + body + m.group(3),
                                    installer, count=1)

    if args.check:
        if drifted:
            print("sync-agent-pack: the installer payload is out of sync with "
                  "agent-pack/ for: " + ", ".join(drifted))
            print("  fix: python3 scripts/sync-agent-pack.py")
            return 1
        print("sync-agent-pack: installer payload matches agent-pack/ "
              f"({len(PAYLOAD)} file(s)).")
        return 0

    if drifted:
        INSTALLER.write_text(installer, encoding="utf-8")
        print("sync-agent-pack: rewrote the payload for " + ", ".join(drifted))
    else:
        print("sync-agent-pack: already in sync; nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
