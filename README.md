# Flutter Builder

একটি reusable GitHub Actions workflow, যা বিভিন্ন Flutter project-এর জন্য একই central setup ব্যবহার করে:

- Dart format check
- `flutter analyze`
- `flutter test` (+ coverage report)
- Manual release APK build
- Signed release APK/AAB build
- APK/AAB artifact download
- Release hardening: obfuscation, symbol upload, per-ABI APK, size limit
- Safety net: test ad ID / `com.example` detection, versionCode bump check, `apksigner` verification
- Web build + GitHub Pages deploy
- `build_runner` / `gen-l10n` code generation, `.fvmrc` pinning, extra Flutter channel matrix
- Play Store track upload + Firebase App Distribution
- সুন্দর structured English release notes তৈরি
- Version tag ও GitHub Release স্বয়ংক্রিয়ভাবে publish
- Versioned APK/AAB এবং `SHA256SUMS.txt` release-এ upload
- Flutter ও Gradle cache

> এই repository-তে Flutter SDK, Android SDK, keystore অথবা password রাখা হয় না। GitHub Actions প্রয়োজনের সময় SDK setup করে।

## Repository design

```text
flutter-builder (এই public repository)
└── reusable build/release workflow

my-first-app (আলাদা repository)
└── Flutter source + ছোট caller workflow (publish-টাও এখন ৬ লাইন)

my-second-app (আলাদা repository)
└── Flutter source + একই caller workflow
```

## প্রথমবার setup

### ধাপ ১: Stable builder version ব্যবহার করুন

App project-এর caller workflow-তে tested tag pin করুন (`v1.4.0` = wrapper `publish-release.yml` + `flutter-build.yml` দুটোই নিয়েছে):

```yaml
uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.4.0
```

Release publish করার জন্য `publish-release.yml@v1.4.0` ব্যবহার করলেই চলবে — সেটা ভেতরে `flutter-build.yml`-এর সেই একই ট্যাগ-পিন করা কল করে, তাই দুটো কখনো একে অপরের সাথে মিল না খেয়ে ফেলে থাকে না।

Development-এর সময় `@main` ব্যবহার করা গেলেও production release-এর জন্য exact version tag বা commit SHA ব্যবহার করা নিরাপদ।

### ধাপ ২: App project-এ CI যোগ করুন

এই repository-এর `examples/project-workflows/ci.yml` app repository-তে copy করুন:

```text
.github/workflows/ci.yml
```

এখন Pull Request বা `main` branch-এ push হলে format, analyze ও test চলবে। সাধারণ code change-এ APK/AAB build হবে না।

### ধাপ ৩: Manual APK/AAB build যোগ করুন

`examples/project-workflows/manual-build.yml` copy করে app repository-তে রাখুন:

```text
.github/workflows/manual-build.yml
```

এরপর:

```text
App repository → Actions → Manual Android Build → Run workflow
```

- `apk`: ফোনে install/test করার release APK
- `aab`: Play Store-এর signed Android App Bundle

AAB-এর আগে [Android signing নির্দেশিকা](docs/ANDROID_SIGNING.md) অনুসরণ করুন।

### ধাপ ৪: Automatic GitHub Release ও English release notes

`examples/project-workflows/publish-release.yml` copy করে app repository-তে রাখুন:

```text
.github/workflows/publish-release.yml
```

**সবচেয়ে ছোট উপায় — publish-টাও reusable** (প্রতিটা project-এ ৩০ লাইনের caller কপি করার দরকার নেই):

```yaml
name: Publish Android Release

on:
  workflow_dispatch:
    inputs:
      draft:
        description: Create the GitHub Release as a draft?
        required: false
        type: boolean
        default: false
      prerelease:
        description: Mark this as a prerelease?
        required: false
        type: boolean
        default: false

permissions:
  contents: write

jobs:
  publish:
    uses: Keshab1997/flutter-builder/.github/workflows/publish-release.yml@v1.4.0
    with:
      app-name: SpeakEasy
      release-draft: ${{ inputs.draft }}
      release-prerelease: ${{ inputs.prerelease }}
    secrets: inherit
```

ব্যস — `build-apk`/`build-aab` default `true`, validation steps default off, `publish-github-release` সবসময় on। প্রয়োজনে override: `run-analyze: true`, `working-directory: apps/mobile`, `artifact-retention-days: 14`।

পুরনো পদ্ধতিটাও চলবে (সরাসরি `flutter-build.yml` কল করে প্রতিটা input নিজে লেখা) — যে project পুরো নিয়ন্ত্রণ চায় তার জন্য। নিচের বাকি অংশ সেটাতেই প্রযোজ্য:


Caller workflow-তে নিজের app-এর নাম দিন:

```yaml
release-name: My Flutter App
```

আর অবশ্যই write permission দিন:

```yaml
permissions:
  contents: write
```

এরপর app-এর `pubspec.yaml` version বাড়ান:

```yaml
version: 1.0.1+2
```

তারপর:

```text
App repository → Actions → Publish Android Release → Run workflow
```

Workflow স্বয়ংক্রিয়ভাবে:

1. signed APK ও AAB build করবে;
2. `pubspec.yaml` থেকে `v1.0.1` tag বানাবে;
3. আগের tag-এর পরের Git commit titleগুলো category অনুযায়ী সাজাবে;
4. Features, Bug Fixes, Performance, Maintenance, Documentation ইত্যাদি section-সহ English release notes লিখবে;
5. GitHub Release publish করবে;
6. versioned APK/AAB এবং `SHA256SUMS.txt` upload করবে।

উদাহরণ output:

```markdown
## ✨ Release Overview

This release delivers the latest stable Android build of My Flutter App.

## 🚀 New Features

- Add automatic Android release publishing

## 🐛 Bug Fixes

- Fix incorrect quiz result saving

## 📦 Android Downloads

| File | Purpose |
|---|---|
| `My-Flutter-App-v1.0.1.apk` | Direct installation and testing |
| `My-Flutter-App-v1.0.1.aab` | Upload to Google Play Console |
```

Release notes পরিষ্কার English হওয়ার জন্য commit/PR title English-এ লেখা উচিত। কোনো external AI API key প্রয়োজন হয় না।

### ধাপ ৫: Tag দিলে automatic AAB (ঐচ্ছিক)

শুধু tag push-এর পরে AAB artifact build করতে `examples/project-workflows/release.yml` ব্যবহার করা যায়:

```bash
git tag v1.0.0
git push origin v1.0.0
```

এটি GitHub Release publish করে না; full release publishing-এর জন্য আগের `publish-release.yml` ব্যবহার করুন।

## Build-time configuration (AdMob ID, API base URL ইত্যাদি)

Release build-এ যে মানগুলো compile-time-এ ঢোকাতে হয় — যেমন আসল AdMob ID — সেগুলো caller workflow-এর `dart-defines` input-এ দিন, প্রতি লাইনে একটি `KEY=VALUE`। প্রতিটি লাইন `flutter build apk/appbundle`-এ `--dart-define=KEY=VALUE` হয়ে যায়; খালি value দিলে সেই key skip হয় এবং app-এর নিজের default (যেমন Google-এর test ad unit) বহাল থাকে।

Gradle/`AndroidManifest.xml`-এর placeholder-এর মতো যে মানগুলো environment variable থেকে পড়া হয়, সেগুলো `build-env` input-এ একই ভাবে দিন — build step-গুলোর জন্য export হয়।

```yaml
jobs:
  publish:
    uses: Keshab1997/flutter-builder/.github/workflows/publish-release.yml@v1.4.0
    with:
      app-name: QuizBaaz
      dart-defines: |
        ADMOB_APP_ID=${{ vars.ADMOB_APP_ID }}
        ADMOB_BANNER_ID=${{ vars.ADMOB_BANNER_ID }}
        ADMOB_INTERSTITIAL_ID=${{ vars.ADMOB_INTERSTITIAL_ID }}
      build-env: |
        ADMOB_APP_ID=${{ vars.ADMOB_APP_ID }}
    secrets: inherit
```

মানগুলো caller repo-র **Settings → Secrets and variables → Actions → Variables**-এ রাখলে workflow file-এ hardcode করতে হয় না। মনে রাখবেন: dart-define-এর মান binary-র ভেতরে চলে যায় — AdMob ID public identifier, এতে সমস্যা নেই; কিন্তু API key/password এভাবে দেবেন না। AAB step-এর Gradle fallback-ও একই define পায়, তাই strip-workaround path দিয়ে গেলেও test ID দিয়ে bundle তৈরি হবে না।

`ANDROID_KEYSTORE_BASE64` secret থাকলে APK-only build-ও এখন upload key দিয়ে sign হয় (আগে শুধু AAB/Release-এ হত) — যে project-এর Gradle `key.properties` ছাড়া release build-ই করতে দেয় না, তার APK build এতে আর fail করে না।

## v1.4.0 — smart features

v1.4.0-এ builder-টা শুধু build করেই থেমে থাকে না, release-এর আগে ঝুঁকি ধরতে পারে। সব input backward compatible — কিছু না দিলে পুরোনো আচরণই থাকে।

### Quality gates

| Input | Default | কী করে |
|---|---|---|
| `code-coverage` | `false` | `flutter test --coverage` চালিয়ে line coverage % summary-তে দেখায় |
| `upload-coverage-codecov` | `false` | `lcov.info` Codecov-এ upload করে (private repo-তে `CODECOV_TOKEN` লাগে) |
| `max-artifact-size-mb` | `0` | APK/AAB এই সাইজের বেশি হলে build fail (Play Store-এর ১৫০ MB AAB limit মিস করার বিপদ কমে) |
| `verify-signing` | `true` | `apksigner verify --print-certs` দিয়ে APK, `META-INF` চেক দিয়ে AAB — unsigned/corrupt artifact publish হওয়া থেকে আটকায় |
| `test-matrix` | `""` | comma-separated extra channel (যেমন `stable,beta`) — format+analyze+test আলাদা job-এ চলে |

```yaml
jobs:
  ci:
    uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.4.0
    with:
      working-directory: flutter_app
      code-coverage: true
      upload-coverage-codecov: true
      max-artifact-size-mb: 150
      test-matrix: stable,beta
```

### Release safety net

| Input | Default | কী করে |
|---|---|---|
| `fail-on-placeholders` | `false` (wrapper-এ `true`) | Google test ad ID, `com.example.*`, debug signing থাকলে fail |
| `check-version-bump` | `false` (wrapper-এ `true`) | `pubspec.yaml` শেষ release tag-এর চেয়ে নতুন না হলে fail |
| `obfuscate` | `false` | `--obfuscate --split-debug-info` দিয়ে build |
| `upload-symbols` | `true` | obfuscation symbol গুলো artifact হিসেবে রাখে (crash de-obfuscate করার জন্য দরকার) |
| `split-per-abi` | `false` | fat APK-এর বদলে per-ABI APK |

**`fail-on-placeholders` কেন দরকার:** AdMob-এর test ID (`ca-app-pub-3940256099942544`) production build-এ চুপচাপ ঢুকে গেলে app-এ Google-এর demo ad দেখায় এবং কিছুই earn হয় না। এই check release path-এ by default on:

```
::error::A Google test ad unit ID (ca-app-pub-3940256099942544) is still in the source...
::error::A placeholder application id (com.example.*) is still configured.
::warning::The release build type can fall back to the debug signing key...
```

**`check-version-bump`:** `git describe` দিয়ে শেষ tag-এর `pubspec.yaml` পড়ে `versionCode` তুলনা করে। Play Store একই versionCode দ্বিতীয়বার নেয় না, তাই release-এর আগেই ধরা পড়ে:

```
::error::versionCode 1 is not greater than 1. Play Store rejects an upload that does not raise versionCode.
```

### Build hardening ও extra target

| Input | Default | কী করে |
|---|---|---|
| `obfuscate` | `false` | Flutter release hardening + symbol artifact |
| `split-per-abi` | `false` | per-ABI APK (ছোট download) |
| `build-web` | `false` | `flutter build web --release`, artifact হিসেবে upload |
| `deploy-web-pages` | `false` | web build GitHub Pages-এ deploy (caller-এ `contents: write` দরকার) |
| `codegen` | `none` | `none` / `build_runner` / `gen-l10n` / `both` — analyze/test-এর আগে চলে |
| `use-fvm` | `false` | project-এর `.fvmrc` থেকে Flutter version pin করে |

```yaml
with:
  build-web: true
  deploy-web-pages: true
  codegen: build_runner
  obfuscate: true
```

### Distribution

| Input | Secret | কী করে |
|---|---|---|
| `play-track` (+ `play-package-name`, `play-status`) | `PLAY_SERVICE_ACCOUNT_JSON` | AAB সরাসরি Google Play-এর internal/alpha/beta track-এ upload |
| `firebase-groups` (+ `firebase-app-id`) | `FIREBASE_SERVICE_CREDENTIALS` | APK/AAB Firebase App Distribution-এ tester group-কে পাঠায় |
| `pr-comment` | — | PR-তে build summary comment (update হয়, বারবার নয়) |
| `notify-webhook` | — | Discord/Slack webhook-এ build status পাঠায় |

```yaml
with:
  play-track: internal
  play-package-name: com.keshabstudios.keepit
```

### Step summary

প্রতিটা run শেষে Actions-এর summary-তে এটা জোড়ায়:

```markdown
## Flutter build summary

| | |
|---|---|
| Workflow | Flutter CI |
| Commit | `21b5001` |
| Job status | **success** |
| Coverage | 402 / 611 lines (65.8%) |
| `app-release.apk` | 22.41 MB |
| `app-release.aab` | 19.87 MB |
```

### Notun secrets

```text
CODECOV_TOKEN                  Codecov (private repo-তে)
PLAY_SERVICE_ACCOUNT_JSON      Google Play upload
FIREBASE_SERVICE_CREDENTIALS   Firebase App Distribution
```

## Artifact download

Workflow সফল হলে:

```text
Actions → Workflow run → Artifacts
```

সেখানে `android-release-apk` অথবা `android-release-aab` পাওয়া যাবে। Artifact ZIP হিসেবে download হয়; unzip করলে APK/AAB পাওয়া যাবে।

GitHub Release-এ publish করা APK/AAB Actions artifact retention শেষ হলেও expire হয় না; Release delete না করা পর্যন্ত থাকে।

## Version bump (প্রয়োজনে)

`publish-release.yml` ইচ্ছাকৃতভাবে version বাড়ায় না। build job ওই SHA-টাই checkout করে যেটা workflow ট্রিগার করেছে — রানের মাঝে নতুন commit করলে সেটা release-এ ঢুকবে না, উল্টো `pubspec.yaml` আর tag-এর version নিয়ে গোলমাল হবে।

তাই SpeakEasy যেমন করে ঠিক তেমনি — release-এর আগের PR-এ-ই bump:

```text
chore: bump version to 1.0.37+37
```

এই repo-র helper পরের version ছাপে (commit করার দায়িত্ব আপনার):

```bash
python3 scripts/bump-pubspec-version.py --pubspec pubspec.yaml --bump build
# name=1.0.37+38
```

`--bump major|minor|patch|build|none`। `patch`/`build`-এ `+N` না থাকলে actionable message দিয়ে exit 1, কারণ Android versionCode ছাড়া Play Store-এ আপলোড যায় না।


## Release version নিয়ম

Flutter version format:

```yaml
version: VERSION_NAME+VERSION_CODE
```

উদাহরণ:

```yaml
version: 1.0.15+15
```

- GitHub tag হবে `v1.0.15`
- Android `versionName` হবে `1.0.15`
- Play Store `versionCode` হবে `15`

প্রতিটি Play Store upload-এর আগে version code অবশ্যই বাড়াতে হবে। একই GitHub tag আগে থেকে থাকলে release workflow ইচ্ছাকৃতভাবে fail করবে।

## Test না থাকলে কী হবে?

`test/` folder-এ `*_test.dart` file থাকলে `flutter test` চলবে। Test file না থাকলে workflow পরিষ্কার message দিয়ে test step skip করবে। Analyze ও format check চলবে।

## Flutter app subfolder-এ থাকলে

Monorepo-তে app যদি `apps/mobile` folder-এ থাকে:

```yaml
permissions:
  contents: read

jobs:
  build:
    uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.4.0
    with:
      working-directory: apps/mobile
      generate-android-platform: true
      build-apk: true
```

## Format check fail করলে

নিজের development machine-এ চালান:

```bash
dart format .
```

তারপর formatted code commit করুন। Manual build/release-এ প্রয়োজন হলে checks বন্ধ রাখা যায়:

```yaml
run-format-check: false
run-analyze: false
run-tests: false
```

তবে আলাদা CI workflow-এ validation চালু রাখাই ভালো।

## Version update পদ্ধতি

Central workflow-তে পরীক্ষিত পরিবর্তনের পর নতুন tag দিন, যেমন:

```bash
git tag v1.4.0
git push origin v1.4.0
```

wrapper (`publish-release.yml`) ভেতরে `flutter-build.yml`-কে নিজের ট্যাগেই পিন করে, তাই নতুন ট্যাগ দেওয়ার সময় wrapper-এর ভেতরের pin-টাও একই ট্যাগে বাড়াতে হবে — নাহলে পুরোনো builder চালু থাকবে।

Projectগুলো exact tag দিয়ে pin করতে পারে:

```yaml
uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.4.0
```

## প্রয়োজনীয় GitHub Secrets

Signed AAB অথবা GitHub Release publishing-এর জন্য app repository-তে প্রয়োজন:

```text
ANDROID_KEYSTORE_BASE64
KEYSTORE_PASSWORD
KEY_ALIAS
KEY_PASSWORD
```

v1.4.0-er distribution feature-er jonno aro:

```text
CODECOV_TOKEN                  private repo-te coverage upload
PLAY_SERVICE_ACCOUNT_JSON      Google Play track upload
FIREBASE_SERVICE_CREDENTIALS   Firebase App Distribution upload
```

বিস্তারিত: [docs/ANDROID_SIGNING.md](docs/ANDROID_SIGNING.md)

## GitHub permissions

সাধারণ CI/manual artifact build-এর জন্য:

```yaml
permissions:
  contents: read
```

GitHub Release publish করার জন্য:

```yaml
permissions:
  contents: write
```

`contents: write` না থাকলে workflow build শেষ করার পরে release publish step-এ fail করবে।

## নিরাপত্তা

- GitHub token, keystore, `.env`, service-account JSON commit করবেন না।
- Personal Access Token chat-এ কাউকে দেবেন না।
- Reusable workflow-কে version tag বা commit SHA দিয়ে pin করুন।
- Project-specific signing secrets app project-এর repository-তেই রাখুন।
- Publish workflow APK এবং AAB—দুটিকেই একই configured release key দিয়ে sign করে।

## বর্তমান scope

এই workflow APK/AAB তৈরি করে, artifact সংরক্ষণ করে এবং optional GitHub Release publish করে। v1.4.0 থেকে `play-track` input দিয়ে AAB সরাসরি Google Play-এর internal/alpha/beta track-এ upload করা যায়, আর `firebase-groups` দিয়ে Firebase App Distribution-এ পাঠানো যায়। Play-এর **production** track deliberately বাদ — release-এর আগে staged rollout manually review করা safer।
