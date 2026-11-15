// ============================================================================
// shim: part of the flutter-builder agent pack. DO NOT EDIT IN A PROJECT.
//
// Installed by scripts/install-agent-pack.sh into tool/screenshots/. The
// canonical copy lives in Keshab1997/flutter-builder (agent-pack/); a local
// edit is overwritten the next time the installer runs with --force, and the
// pack's own tests compare this file byte for byte with that copy.
//
// Everything a project has to say about itself lives in shot_registry.dart
// next door: this file must compile against any Flutter app, which is why it
// imports nothing from the app, no state-management package and no theme class.
// ============================================================================
//
// Render screens to PNGs, in the test harness, with the app's real theme and
// real fonts - no device, no CI run, no network.
//
// Why it exists next to tool/see_screen.py: that one asks CI to build the web
// app and photograph *routes*. It costs a run and it cannot reach a screen you
// have to tap into (any pushed detail screen). This renders the widget itself,
// so it takes about a second and photographs exactly what you named.
//
// The PNGs are throwaway evidence: they land in .agent-screens/local/
// (git-ignored) and nothing reads them back as a test fixture.
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

/// One screen, rendered the way a phone would render it.
class Shot {
  const Shot({
    required this.name,
    required this.build,
    this.preferences = const <String, Object>{},
    this.logicalSize = const Size(390, 844),
    this.dpr = 2,
    this.dark = true,
    this.textScale = 1,
  });

  /// What `--shot <name>` takes, and the PNG's file name. Kebab-case.
  final String name;
  final Widget Function() build;

  /// Values seeded into SharedPreferences before the pump - this is how a shot
  /// can show a Bengali session or a three-draft setting without anybody
  /// tapping anything.
  final Map<String, Object> preferences;

  /// Logical size. 390x844 is a modern phone; use 320x... to see what a narrow
  /// screen does to a layout, because that is where layouts break.
  final Size logicalSize;
  final double dpr;
  final bool dark;
  final double textScale;

  String get sizeLabel =>
      '${logicalSize.width.toInt()}x${logicalSize.height.toInt()}@${dpr}x';
}

/// Everything the framework needs to know about the app it is rendering.
///
/// This is the whole contract with a project, and it is deliberately small:
/// the app shell, a wrapper, font files, and the mocks a widget test needs. A
/// screenshot taken in a bare theme is a screenshot of a different app, so
/// [app] is required and there is no default.
class ShotEnv {
  const ShotEnv({
    required this.app,
    this.wrap = _noWrap,
    this.fontAssets = const <String, String>{},
    this.bridgeChannel,
    this.bridgeAnswers = const <String, Object?>{},
    this.seedPreferences,
    this.setUpAll,
    this.materialIconsFamily = 'MaterialIcons',
  });

  /// Builds the widget that goes above the screen: the app's own MaterialApp
  /// (or CupertinoApp), with its real theme and locale.
  ///
  /// It is a callback rather than a `ThemeData` field on purpose. Flutter has
  /// started moving material out of the framework into `package:material_ui`,
  /// where `ThemeData` is a *different type* than the one in
  /// `package:flutter/material.dart` - so a framework that named either import
  /// would fail to compile in half the projects that install it. Handing the
  /// shell back to the project keeps this file free of both, and lets a project
  /// add a locale, a golden-ratio fix or a ProviderScope without touching the,
  /// pack.
  final Widget Function(Shot shot, Widget home) app;

  /// ProviderScope, MultiBlocProvider, GetIt bootstrap - whatever the app puts
  /// above its widgets in main(). Identity by default, when there is nothing.
  final Widget Function(Widget child) wrap;

  /// Font family name -> asset path, e.g. {'Inter': 'assets/fonts/Inter.ttf'}.
  /// Without these every glyph renders as a solid box and the picture is worse
  /// than useless: it looks like a layout bug.
  final Map<String, String> fontAssets;

  /// The MethodChannel the app talks to its native side on, mocked for the
  /// duration of the run. Null means the app has no such channel.
  final String? bridgeChannel;

  /// method name -> the answer a "nothing is set up yet" install would give.
  /// A shot should show the honest empty state, not a red screen.
  final Map<String, Object?> bridgeAnswers;

  /// How to seed SharedPreferences from [Shot.preferences].
  ///
  /// The pack does not import shared_preferences: an app without that
  /// dependency would fail to compile, and the pack has to fit every project.
  /// Pass `(values) => SharedPreferences.setMockInitialValues(values)` (add the
  /// `// ignore: invalid_use_of_visible_for_testing_member`) or seed your own
  /// store instead. Leave it null only if no shot declares preferences.
  final Future<void> Function(Map<String, Object> values)? seedPreferences;

  /// Runs once before the first shot: Hive.init, temp directories, fake clocks.
  /// A widget that opens a local box throws without this, and the shot would be
  /// a red error page instead of a screen.
  final Future<void> Function()? setUpAll;

  /// The icon font family, which ships with the SDK rather than the repo.
  final String materialIconsFamily;

  static Widget _noWrap(Widget child) => child;
}

/// The two flags, read as strings.
///
/// `bool.fromEnvironment` only understands "true"/"false", so the documented
/// `--dart-define=SHOTS=1` would leave the whole tool silently off. Strings do
/// not have that trap.
const String _shotsFlag = String.fromEnvironment('SHOTS');
const String requestedShots = String.fromEnvironment('SHOT');

/// No define, no rendering: a direct run of the runner cannot start writing
/// PNGs by accident.
const bool shotsEnabled = _shotsFlag == '1' || _shotsFlag == 'true';

/// Where the PNGs go. Two spellings of one directory on purpose: Flutter
/// resolves a golden path against *the test file's* directory, while dart:io
/// creates directories against the *package root*.
const String goldenDir = '../../.agent-screens/local';
const String outputDir = '.agent-screens/local';

/// The widget the golden is taken of: everything the app drew, nothing else.
const ValueKey<String> shotRootKey = ValueKey<String>('agent-pack-shot-root');

/// `--dart-define=SHOT=a,b` selects; empty means every shot.
List<Shot> selectShots(List<Shot> shots, String requested) {
  final wanted = requested
      .split(',')
      .map((name) => name.trim())
      .where((name) => name.isNotEmpty)
      .toSet();
  if (wanted.isEmpty) return shots;
  return shots.where((shot) => wanted.contains(shot.name)).toList();
}

Future<void> _loadAppFonts(ShotEnv env) async {
  for (final entry in env.fontAssets.entries) {
    final file = File(entry.value);
    if (!file.existsSync()) {
      throw StateError(
        'shot fonts: "${entry.key}" points at ${entry.value}, which does not '
        'exist. Fix fontAssets in shot_registry.dart.',
      );
    }
    final bytes = file.readAsBytesSync();
    final loader = FontLoader(entry.key)
      ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
    await loader.load();
  }

  // Icons are a font too, and this one ships with the SDK, not the repo. Two
  // ways to find the SDK: the environment, and the running binary itself - a
  // test process lives at <sdk>/bin/cache/dart-sdk/bin/dart, so five parents up
  // is the SDK root. Never a hard-coded install path: that is one machine's
  // layout, and this file has to work on everybody's.
  final candidates = <String>[
    for (final root in <String>[
      Platform.environment['FLUTTER_ROOT'] ?? '',
      _sdkRootFromExecutable(),
    ])
      if (root.isNotEmpty)
        '$root/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
  ];
  final icons = candidates.map(File.new).where((f) => f.existsSync()).toList();
  if (icons.isEmpty) {
    throw StateError(
      'shot fonts: MaterialIcons not found (looked in $candidates). Icons '
      'would render as boxes, so this stops instead of writing a misleading '
      'screenshot. Set FLUTTER_ROOT if the SDK lives elsewhere.',
    );
  }
  final bytes = icons.first.readAsBytesSync();
  final loader = FontLoader(env.materialIconsFamily)
    ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
  await loader.load();
}

/// `<sdk>/bin/cache/dart-sdk/bin/dart` -> `<sdk>`, where the SDK keeps the
/// icon font. Empty when the binary does not sit inside an SDK (a `dart` from a
/// package manager, say) - then FLUTTER_ROOT has to answer.
String _sdkRootFromExecutable() {
  Directory dir = File(Platform.resolvedExecutable).parent;
  for (var i = 0; i < 5; i++) {
    dir = dir.parent;
  }
  return dir.path;
}

void _mockBridge(TestWidgetsFlutterBinding binding, ShotEnv env) {
  final name = env.bridgeChannel;
  if (name == null) return;
  final channel = MethodChannel(name);
  binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
    call,
  ) async {
    return env.bridgeAnswers[call.method];
  });
}

/// The whole suite. Call this from the runner; there is nothing else to it.
void runShotSuite({
  required List<Shot> shots,
  required ShotEnv env,
  String requested = requestedShots,
  bool enabled = shotsEnabled,
}) {
  if (!enabled) {
    test('screenshot runner is off (pass --dart-define=SHOTS=1)', () {});
    return;
  }

  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  final selected = selectShots(shots, requested);

  setUpAll(() async {
    await _loadAppFonts(env);
    _mockBridge(binding, env);
    await env.setUpAll?.call();
    Directory(outputDir).createSync(recursive: true);
  });

  if (selected.isEmpty) {
    test('no shot matched --dart-define=SHOT=$requested', () {
      fail(
        'Nothing matched. Known shots: '
        '${shots.map((shot) => shot.name).join(', ')}',
      );
    });
    return;
  }

  for (final shot in selected) {
    testWidgets('shot: ${shot.name} (${shot.sizeLabel})', (tester) async {
      final seed = env.seedPreferences;
      if (seed != null) {
        await seed(shot.preferences);
      } else if (shot.preferences.isNotEmpty) {
        // Fail loudly here rather than let the screen paint a MissingPlugin
        // red page: a silent empty store looks like a bug in the app.
        fail(
          'shot "${shot.name}" declares preferences but ShotEnv.seedPreferences '
          'is null - nothing was seeded.',
        );
      }

      tester.view.physicalSize = Size(
        shot.logicalSize.width * shot.dpr,
        shot.logicalSize.height * shot.dpr,
      );
      tester.view.devicePixelRatio = shot.dpr;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(
        env.wrap(
          MediaQuery(
            data: MediaQueryData(
              size: shot.logicalSize,
              textScaler: TextScaler.linear(shot.textScale),
              devicePixelRatio: shot.dpr,
            ),
            // The boundary is what gets photographed, and its key is what the
            // golden is asked for: the pack cannot say find.byType(MaterialApp)
            // without importing material, and it must not import material.
            child: RepaintBoundary(
              key: shotRootKey,
              child: env.app(shot, shot.build()),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Asset images decode on a real event loop, which the fake async of a
      // widget test never advances. Without this a logo or mascot photographs
      // as a coloured circle - a picture that lies about the app.
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 80)),
      );
      await tester.pump();

      // A layout exception is the most valuable thing a screenshot can tell
      // you, and it is invisible in the pixels. Fail loudly, with the name.
      expect(
        tester.takeException(),
        isNull,
        reason: '${shot.name} threw while rendering',
      );

      await expectLater(
        find.byKey(shotRootKey),
        matchesGoldenFile('$goldenDir/${shot.name}.png'),
      );
    });
  }
}
