// ============================================================================
// shim: part of the flutter-builder agent pack. DO NOT EDIT IN A PROJECT.
// Canonical copy: Keshab1997/flutter-builder (agent-pack/shot_runner_test.dart).
// ============================================================================
//
// The entry point the CLI runs:
//
//     python3 tool/local_screenshots.py --list
//     python3 tool/local_screenshots.py --shot settings
//
// All of the work is in shot_framework.dart; everything specific to this app is
// in shot_registry.dart. This file is deliberately two imports and four lines,
// because a project should never need to touch it - and if it does, the next
// installer run takes the change away.
//
// It lives in tool/, not test/, so a plain `flutter test` never discovers it:
// CI stays as fast as it was and cannot go red because a golden moved.
import 'shot_framework.dart';
import 'shot_registry.dart';

void main() {
  runShotSuite(shots: shots, env: env);
}
