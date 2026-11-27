"""Tests for scripts/sync-pulse-config.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync-pulse-config.py"


class SyncPulseConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Path(self.temp.name) / "app"
        self.app.mkdir()

    def write_pubspec(self, version: str = "1.4.2+18") -> None:
        (self.app / "pubspec.yaml").write_text(
            f"name: sample_app\nversion: {version}\n",
            encoding="utf-8",
        )

    def write_pulse(self, data: dict) -> Path:
        path = self.app / "pulse.json"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return path

    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), "--root", str(self.app), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_skips_cleanly_when_pulse_json_absent(self) -> None:
        self.write_pubspec("1.0.0+1")
        res = self.run_tool()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("not found", res.stdout)
        self.assertFalse((self.app / "pulse.json").exists())

    def test_init_scaffolds_starter_pulse_json(self) -> None:
        self.write_pubspec("2.1.0+9")
        res = self.run_tool("--init")
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads((self.app / "pulse.json").read_text(encoding="utf-8"))
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["update"]["latestVersion"], "2.1.0")
        self.assertEqual(data["update"]["latestBuildNumber"], 9)
        self.assertFalse(data["maintenance"]["enabled"])

    def test_syncs_version_and_preserves_other_fields(self) -> None:
        self.write_pubspec("1.5.0+22")
        pulse = self.write_pulse(
            {
                "schemaVersion": 1,
                "update": {
                    "latestVersion": "1.4.0",
                    "latestBuildNumber": 20,
                    "minSupportedVersion": "1.0.0",
                    "androidUrl": "https://play.google.com/store/apps/details?id=x.y",
                },
                "maintenance": {"enabled": False, "title": "Back soon"},
                "notices": [{"id": "n1", "title": "Hi", "message": "Hello"}],
                "flags": {"show_ads": True, "limit": 5},
            }
        )

        # --check detects drift before syncing
        chk_before = self.run_tool("--check")
        self.assertEqual(chk_before.returncode, 1)
        self.assertIn("OUT OF SYNC", chk_before.stdout)

        # --dry-run does not modify file
        dry = self.run_tool("--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertEqual(
            json.loads(pulse.read_text(encoding="utf-8"))["update"]["latestVersion"],
            "1.4.0",
        )

        # Real sync updates only version fields
        res = self.run_tool()
        self.assertEqual(res.returncode, 0, res.stderr)
        updated = json.loads(pulse.read_text(encoding="utf-8"))
        self.assertEqual(updated["update"]["latestVersion"], "1.5.0")
        self.assertEqual(updated["update"]["latestBuildNumber"], 22)
        self.assertEqual(updated["update"]["minSupportedVersion"], "1.0.0")
        self.assertEqual(
            updated["update"]["androidUrl"],
            "https://play.google.com/store/apps/details?id=x.y",
        )
        self.assertEqual(updated["flags"], {"show_ads": True, "limit": 5})
        self.assertEqual(len(updated["notices"]), 1)

        # --check now passes
        chk_after = self.run_tool("--check")
        self.assertEqual(chk_after.returncode, 0, chk_after.stdout + chk_after.stderr)

    def test_supports_min_supported_and_whats_new_flags(self) -> None:
        self.write_pubspec("2.0.0+30")
        pulse = self.write_pulse({"schemaVersion": 1, "update": {}})
        res = self.run_tool(
            "--min-supported",
            "1.5.0+15",
            "--whats-new",
            "Faster offline sync",
            "--whats-new",
            "Bangla UI update",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        updated = json.loads(pulse.read_text(encoding="utf-8"))
        self.assertEqual(updated["update"]["latestVersion"], "2.0.0")
        self.assertEqual(updated["update"]["latestBuildNumber"], 30)
        self.assertEqual(updated["update"]["minSupportedVersion"], "1.5.0")
        self.assertEqual(updated["update"]["minSupportedBuildNumber"], 15)
        self.assertEqual(
            updated["update"]["whatsNew"],
            ["Faster offline sync", "Bangla UI update"],
        )

    def test_invalid_json_exits_nonzero(self) -> None:
        self.write_pubspec("1.0.0+1")
        (self.app / "pulse.json").write_text("{broken json", encoding="utf-8")
        res = self.run_tool()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("cannot parse", res.stderr)


if __name__ == "__main__":
    unittest.main()
