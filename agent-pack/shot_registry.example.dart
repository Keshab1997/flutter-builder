// The one file in tool/screenshots/ that belongs to THIS project.
//
// The installer writes this once, only when it is missing, and never touches it
// again - everything else in this directory is replaced by the pack. So: edit
// it freely, commit it, and treat it as app code.
//
// It has to compile in a project that has just installed the pack, which is why
// the shot list starts empty and the env is a placeholder. Fill both in:
//
//   1. env - the app's real theme (the same function main() gives MaterialApp),
//      the font files it ships, the MethodChannel it talks to Kotlin/Java on,
//      and whatever its widget tests have to initialise first (Hive, a clock).
//   2. shots - one entry per screen worth looking at, named in kebab-case.
//
// A worked example, from a real project:
//
//   final ShotEnv env = ShotEnv(
//     // The app's real shell. Note it is *your* import of Material/Cupertino:
//     // the pack names neither, because Flutter's material move makes
//     // package:flutter/material.dart and package:material_ui/material_ui.dart
//     // different ThemeData types.
//     app: (shot, home) => MaterialApp(
//       theme: shot.dark ? AppTheme.dark() : AppTheme.light(),
//       home: home,
//     ),
//     wrap: (child) => ProviderScope(child: child),
//     fontAssets: const <String, String>{
//       'Inter': 'assets/fonts/Inter-Variable.ttf',
//     },
//     bridgeChannel: AppConstants.channelName,
//     bridgeAnswers: const <String, Object?>{
//       'isListenerEnabled': false,
//       'overlayGranted': false,
//     },
//     setUpAll: () async {
//       Hive.init(Directory.systemTemp.createTempSync('shots').path);
//     },
//   );
//
//   final List<Shot> shots = <Shot>[
//     Shot(name: 'home', build: () => const HomeScreen()),
//     Shot(name: 'settings', build: () => const SettingsScreen()),
//     // The case that catches what a comfortable phone hides.
//     Shot(
//       name: 'settings-narrow',
//       build: () => const SettingsScreen(),
//       logicalSize: const Size(320, 1400),
//     ),
//   ];
import 'shot_framework.dart';

/// No shots yet - add the app's screens here.
final List<Shot> shots = <Shot>[];

/// A pass-through until you fill it in: with no app shell there is no theme, so
/// the first real shot needs the block in the comment above.
final ShotEnv env = ShotEnv(app: (shot, home) => home);
