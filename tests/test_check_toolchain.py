"""Tests for scripts/check_toolchain.py.

The failure this guards against is real: a consumer's Flutter pin moved to
3.50.0 while android/ still had AGP 9.1.0, and the APK build died after a full
Gradle run with a message that named Gradle, not the pin. The checker has to
catch that in a bare checkout, with no SDK, no Gradle and no network.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
CHECKER = REPO / "scripts" / "check_toolchain.py"

SETTINGS = """pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}

plugins {
    id("dev.flutter.flutter-plugin-loader") version "1.0.0"
    id("com.android.application") version "%s" apply false
    id("org.jetbrains.kotlin.android") version "%s" apply false
}

include(":app")
"""

WRAPPER = """distributionBase=GRADLE_USER_HOME
distributionPath=wrapper/dists
zipStoreBase=GRADLE_USER_HOME
zipStorePath=wrapper/dists
distributionUrl=https\\://services.gradle.org/distributions/gradle-%s-all.zip
"""


class ToolchainCheck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.root = pathlib.Path(self.dir)
        self.write(agp="9.3.1", gradle="9.5.0", kotlin="2.4.20", flutter="3.50.0")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, agp, gradle, kotlin, flutter):
        (self.root / "android/gradle/wrapper").mkdir(parents=True, exist_ok=True)
        (self.root / "android/settings.gradle.kts").write_text(
            SETTINGS % (agp, kotlin))
        (self.root / "android/gradle/wrapper/gradle-wrapper.properties").write_text(
            WRAPPER % gradle)
        (self.root / ".fvmrc").write_text('{\n  "flutter": "%s"\n}\n' % flutter)

    def run_check(self):
        env = dict(os.environ)
        env.pop("FLUTTER_ROOT", None)  # the built-in table, not a stray SDK
        out = subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root),
                              "--json"], capture_output=True, text=True, env=env)
        return out.returncode, json.loads(out.stdout)

    def test_matching_toolchain_passes(self):
        code, result = self.run_check()
        self.assertEqual(code, 0, result["problems"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["agp"], "9.3.1")

    def test_agp_below_flutter_minimum_fails(self):
        self.write(agp="9.1.0", gradle="9.5.0", kotlin="2.4.20", flutter="3.50.0")
        code, result = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("9.1.1", " ".join(result["problems"]))

    def test_gradle_below_flutter_minimum_fails(self):
        self.write(agp="9.3.1", gradle="9.0.0", kotlin="2.4.20", flutter="3.50.0")
        code, result = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("Gradle 9.0.0", " ".join(result["problems"]))

    def test_kotlin_below_flutter_minimum_fails(self):
        self.write(agp="9.3.1", gradle="9.5.0", kotlin="2.3.0", flutter="3.50.0")
        code, result = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("Kotlin", " ".join(result["problems"]))

    def test_version_between_minimum_and_warn_only_notes(self):
        # Works, but on a rung the Flutter plugin already warns about.
        self.write(agp="9.2.0", gradle="9.4.0", kotlin="2.4.20", flutter="3.50.0")
        code, result = self.run_check()
        self.assertEqual(code, 0, result["problems"])
        self.assertTrue(result["notes"])

    def test_unknown_flutter_is_a_failure_not_a_pass(self):
        self.write(agp="9.3.1", gradle="9.5.0", kotlin="2.4.20", flutter="9.99.99")
        code, result = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("no constraint table", " ".join(result["problems"]))

    def test_missing_android_directory_is_reported(self):
        shutil.rmtree(self.root / "android")
        out = subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root)],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)
        self.assertIn("no android/ directory", out.stderr)

    def test_flutter_version_compares_numerically(self):
        # 9.10.0 > 9.9.0; a string compare would call it smaller.
        self.write(agp="9.10.0", gradle="9.10.0", kotlin="2.4.20", flutter="3.50.0")
        code, result = self.run_check()
        self.assertEqual(code, 0, result["problems"])

    def test_sdk_constraints_are_read_from_the_flutter_tree(self):
        sdk = self.root / "sdk"
        (sdk / "bin").mkdir(parents=True)
        (sdk / "bin/flutter").write_text("#!/bin/sh\n")
        (sdk / "bin/flutter").chmod(0o755)
        checker = sdk / ("packages/flutter_tools/gradle/src/main/kotlin/"
                         "DependencyVersionChecker.kt")
        checker.parent.mkdir(parents=True)
        checker.write_text(
            "internal val warnGradleVersion: Version = Version(9, 5, 0)\n"
            "internal val errorGradleVersion: Version = Version(9, 3, 1)\n"
            "internal val warnAGPVersion: AndroidPluginVersion = "
            "AndroidPluginVersion(9, 3, 1)\n"
            "internal val errorAGPVersion: AndroidPluginVersion = "
            "AndroidPluginVersion(9, 1, 1)\n"
            "internal val errorKGPVersion: Version = Version(2, 4, 10)\n")
        env = dict(os.environ, FLUTTER_ROOT=str(sdk))
        out = subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root),
                              "--json"], capture_output=True, text=True, env=env)
        result = json.loads(out.stdout)
        self.assertIn("Flutter SDK", result["constraints"]["source"])
        self.assertEqual(result["constraints"]["agp_min"], "9.1.1")


class WorkflowWiring(unittest.TestCase):
    """The checker is fetched into RUNNER_TEMP, so the step must point it at the
    project — the first release of this check failed its own consumers because
    it inspected the temp directory instead."""

    def test_step_passes_root_dot(self):
        workflow = (REPO / ".github/workflows/flutter-build.yml").read_text()
        self.assertIn("check_toolchain.py --root .", workflow,
                      "the fetched checker needs --root . to see the project")

    def test_input_is_on_by_default(self):
        import yaml  # noqa: PLC0415 - optional dependency, only this test
        data = yaml.safe_load((REPO / ".github/workflows/flutter-build.yml").read_text())
        spec = (data.get(True) or data.get("on"))["workflow_call"]["inputs"]["check-toolchain"]
        self.assertTrue(spec["default"])


if __name__ == "__main__":
    unittest.main()
