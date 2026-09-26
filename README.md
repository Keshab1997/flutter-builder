# Flutter Builder

একটি reusable GitHub Actions workflow, যা বিভিন্ন Flutter project-এর জন্য একই central setup ব্যবহার করে:

- যেকোনো GitHub-hosted Flutter project-এ এক কমান্ডে caller workflow installer
- Dart format check
- `flutter analyze`
- `flutter test` (+ coverage report)
- Manual release APK build
- Signed release APK/AAB build
- APK/AAB artifact download
- Release hardening: obfuscation, symbol upload, per-ABI APK, size limit
- Safety net: test ad ID / `com.example` detection, versionCode bump check, `apksigner` verification
- Web build + GitHub Pages deploy
- Web preview: প্রতিটি push/PR-এ branch-অনুযায়ী GitHub Pages URL — APK install না করেই browser-এ app test
- `build_runner` / `gen-l10n` code generation, `.fvmrc` pinning, extra Flutter channel matrix
- Play Store track upload + Firebase App Distribution
- সুন্দর structured English release notes তৈরি
- Version tag ও GitHub Release স্বয়ংক্রিয়ভাবে publish
- Versioned APK/AAB এবং `SHA256SUMS.txt` release-এ upload
- Flutter ও Gradle cache

> এই repository-তে Flutter SDK, Android SDK, keystore অথবা password রাখা হয় না। GitHub Actions প্রয়োজনের সময় SDK setup করে।

## Repository design

```text
flutter-builder (এই public repository)
└── reusable build/release workflow

my-first-app (আলাদা repository)
└── Flutter source + ছোট caller workflow (publish-টাও এখন ৬ লাইন)

my-second-app (আলাদা repository)
└── Flutter source + একই caller workflow
```

## এক কমান্ডে setup (v1.8.1)

GitHub-এ host করা Flutter project-এর directory থেকে **Linux / macOS / Windows Git Bash**-এ চালান (Bash ও curl লাগে; Flutter SDK installer-এর জন্য লাগে না):

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.8.1/scripts/install.sh | bash
```

Script app-এর `pubspec.yaml` (dependency `sdk: flutter`) খুঁজে নিজে working directory নির্ধারণ করে। Git repository থাকলে **repo root**-এর `.github/workflows/`-এ পাঁচটি ছোট caller বসায়; Git না থাকলে বর্তমান directory-কে root ধরে। এগুলো একই **`@v1.8.1`** tag-এ reusable builder pin করে:

| ফাইল | কখন চলে |
|---|---|
| `ci.yml` | সব branch-এর push / PR / manual: format, analyze, test, coverage; APK/AAB নয় |
| `manual-build.yml` | Actions থেকে ম্যানুয়ালি APK বা AAB |
| `publish-release.yml` | Actions থেকে ম্যানুয়ালি signed APK/AAB + GitHub Release |
| `release.yml` | `v*` tag push হলে শুধু signed AAB artifact; GitHub Release নয় |
| `web-preview.yml` | সব branch-এর push / PR: web build করে GitHub Pages-এ বসায় — browser-এ URL খুলেই test, APK নয় |

**Monorepo-তে একাধিক Flutter app থাকলে** ইচ্ছামতো একটি বেছে দিন (path repo root থেকে):

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.8.1/scripts/install.sh | bash -s -- --app-dir apps/mobile --app-name "My App"
```

একাধিক app পেলে script আন্দাজ করে ভুলটা বেছে নেবে না; `--app-dir` চাইবে। `--app-name` না দিলে release title-এ `pubspec.yaml`-এর নাম ব্যবহার হয়। `--ref v1.4.0` দিয়ে পুরোনো tested version pin করা যায়; সাধারণত default tag-ই রাখুন। আগে কী লিখবে দেখতে `--dry-run` দিন।

**Existing workflow নিরাপদ:** একই নামের customized file পেলে **কোনো file-ই পরিবর্তন না করে** error দেয়। `--force` দিলে পুরোনোগুলো `.github/flutter-builder-backups/<timestamp>/`-এ backup রেখে replace করে; ব্যবহার করার আগে diff দেখে নিন। দ্বিতীয়বার চালালে ইতিমধ্যে identical file skip করে। ভিন্ন নামে থাকা আপনার existing workflow-ও inspect করুন, নাহলে একই push-এ দুটি CI চলতে পারে।

Installer নিজে secret তৈরি করে না, `git commit/push` করে না এবং release চালু করে না। Install-এর পর `.github/workflows/` review করে commit/push করুন। **AAB/Publish-এর আগে** [Android signing config ও চারটি keystore secret](docs/ANDROID_SIGNING.md) তৈরি করুন, `pubspec.yaml`-এ `version: name+code` ঠিক করুন, আর test AdMob ID / `com.example` placeholder বদলান। `android/` না থাকলে Android build-এর আগে Flutter-এ Android platform যোগ করতে হবে। Publish path-এর placeholder ও version-bump checks default-on; test ID থাকলে ইচ্ছাকৃতভাবে release fail করবে।

Remote shell script চালানোর আগে review করতে চাইলে [scripts/install.sh](scripts/install.sh) পড়ুন বা versioned URL থেকে download করে দেখে তারপর `bash install.sh` চালান। Script শুধুই caller YAML লেখে; app code বা keystore touch করে না।

## ম্যানুয়াল setup (installer ব্যবহার না করলে)

### ধাপ ১: Stable builder version ব্যবহার করুন

App project-এর caller workflow-তে tested tag pin করুন (`v1.8.1` = installer + wrapper `publish-release.yml` + `flutter-build.yml` একই pin):

```yaml
uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.8.1
```

Release publish করার জন্য `publish-release.yml@v1.8.1` ব্যবহার করলেই চলবে — সেটা ভেতরে `flutter-build.yml`-এর সেই একই ট্যাগ-পিন করা কল করে, তাই দুটো কখনো একে অপরের সাথে মিল না খেয়ে ফেলে থাকে না।

Development-এর সময় `@main` ব্যবহার করা গেলেও production release-এর জন্য exact version tag বা commit SHA ব্যবহার করা নিরাপদ।

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
    uses: Keshab1997/flutter-builder/.github/workflows/publish-release.yml@v1.8.1
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

এরপর app-এর `pubspec.yaml` version বাড়ান:

```yaml
version: 1.0.1+2
```

তারপর:

```text
App repository → Actions → Publish Android Release → Run workflow
```

Workflow স্বয়ংক্রিয়ভাবে:

1. signed APK ও AAB build করবে;
2. `pubspec.yaml` থেকে `v1.0.1` tag বানাবে;
3. আগের tag-এর পরের Git commit titleগুলো category অনুযায়ী সাজাবে;
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

Release notes পরিষ্কার English হওয়ার জন্য commit/PR title English-এ লেখা উচিত। কোনো external AI API key প্রয়োজন হয় না।

### ধাপ ৫: Tag দিলে automatic AAB (ঐচ্ছিক)

শুধু tag push-এর পরে AAB artifact build করতে `examples/project-workflows/release.yml` ব্যবহার করা যায়:

```bash
git tag v1.0.0
git push origin v1.0.0
```

এটি GitHub Release publish করে না; full release publishing-এর জন্য আগের `publish-release.yml` ব্যবহার করুন।

## Doctor — সমস্যা কোথায়, doctor বলে দেবে

Release-এর আগে একবার চালিয়ে নিন:

```bash
bash /path/to/flutter-builder/scripts/doctor.sh
# অথবা clone ছাড়াই:
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/main/scripts/doctor.sh | bash
```

**App repository-র root থেকে চালাতে হবে** (flutter-builder থেকে নয়)। এটি চেক করে:

| Section | যা যা দেখে |
|---|---|
| Environment | `gh`, `git`, `python3`, `openssl` — আর gh authenticated কিনা |
| Repository | Android/iOS module খোঁজে, `applicationId` বের করে |
| Android signing | `key.properties`-এর চারটি key, keystore file আছে কিনা, git-এ tracked কিনা |
| Firebase config | `google-services.json` valid JSON কিনা, package `applicationId`-এর সাথে মেলে কিনা, git-এ আছে কিনা |
| GitHub secrets | কোন secret/variable **missing** |
| Workflow wiring | builder `@v1.6.0+`, `with:`-এর ভিতরে `${{ secrets.* }}` আছে কিনা, Firebase secret forward হচ্ছে কিনা |
| Source hygiene | `lib/`-এ Google test ad ID, `com.example` placeholder, tracked secret file |

প্রতিটি সমস্যার পাশেই ঠিক কী করতে হবে লেখা থাকে, শেষে **"Fix these first"** তালিকা।
`0 failures` মানে release-এর জন্য প্রস্তুত; কোনো FAIL থাকলে exit code `1`।

> ⚠️ Doctor **empty secret** ধরতে পারে না — `gh` কখনো value পড়তে পারে না, আর
> empty সেট করলেও Updated timestamp আজকের হয়। Empty ধরতে হলে একটা real build
> চালিয়ে log-এ `OK: android/app/google-services.json is valid JSON` খুঁজতে হবে।

### Release-এ doctor স্বয়ংক্রিয়ভাবে (v1.7.0+)

`preflight` input দিলে AAB/APK build-এর **ঠিক আগে** doctor চলে — signing আর
Firebase config লেখার পরে, তাই সে exactly সেই tree দেখে যা compile হতে যাচ্ছে।

```yaml
jobs:
  publish:
    uses: Keshab1997/flutter-builder/.github/workflows/publish-release.yml@v1.8.1
    with:
      app-name: KeepIt
      working-directory: flutter_app
      preflight: true                  # release path-এ default-ই true
      preflight-require-firebase: true # ← empty Firebase secret এখন FAIL করবে
    secrets: inherit
```

| Input | Default (build / release) | কাজ |
|---|---|---|
| `preflight` | `false` / **`true`** | doctor চালিয়ে FAIL থাকলে build বন্ধ |
| `preflight-require-firebase` | `false` / `false` | `google-services.json` অনুপস্থিত থাকলে FAIL |

`preflight-require-firebase: true` মানেই: **`GOOGLE_SERVICES_JSON_BASE64` empty
হলে আর চুপচাপ offline-only app release হবে না** — build লাল হয়ে বলবে:

```text
FAIL  google-services.json ABSENT after injection —
      GOOGLE_SERVICES_JSON_BASE64 is empty or invalid.
```

যে app-এ Firebase দরকার নেই, সেখানে `preflight-require-firebase` বন্ধ রাখুন
(তখন file অনুপস্থিত থাকলে শুধু info)। Doctor বন্ধ করতে: `preflight: false`।

> 🔴 v1.7.0-এর আগে `publish-release.yml` ভিতরে `flutter-build.yml@v1.5.0` কল
> করত — কিন্তু Firebase injection v1.6.0-এ এসেছে। তার মানে **release path-এ
> `google-services.json` কখনো inject-ই হয়নি**, অথচ manual build-এ হয়েছিল।
> v1.7.0 সেটা ঠিক করে। তাই `@v1.7.0`-এ upgrade করা জরুরি।

## Web preview — APK না নামিয়ে browser-এ app দেখা (v1.8.0+)

প্রতিবার APK নামিয়ে install করে test না করে দ্রুত দেখতে: `web-preview.yml` caller প্রতিটি
push ও PR-এ app-টি web-এ build করে GitHub Pages-এ `preview/<branch>` path-এ বসিয়ে দেয়।
Actions run-এর step summary (আর PR হলে PR comment) থেকে URL নিয়ে browser-এ খুললেইই চলে:

```text
https://<username>.github.io/<repo>/preview/main/
```

একবারের setup: **Settings → Pages → Build and deployment → Deploy from a branch →
`gh-pages` (root)**। প্রথম run নিজেই `gh-pages` branch বানিয়ে নেয়। App-এ `web/` directory
না থাকলে একবার `flutter create --platforms web .` চালান।

জেনে রাখুন:

- এটা **build preview**, hot reload নয় — develop করার সময় live debug-এর জন্য locally
  `flutter run -d chrome` চালান (reload: terminal-এ `r`)।
- প্রতিটি branch-এর নিজের preview থাকে, তাই একাধিক branch পাশাপাশি দেখা যায়।
- Camera/Bluetooth-এর মতো web নেই এমন plugin preview-তে কাজ করবে না; final টেস্ট device-এই করুন।
- `flutter-build.yml`-এর `deploy-web-pages` (release web deploy) Pages-এর root পরিষ্কার করে
  দেয়, তাই ওটা চালালে preview মুছে যায় — পরের push-এ আবার ফিরে আসে।
- Caller-এ `comment-on-pr: false` দিলে PR comment বন্ধ।

## Build-time configuration (AdMob ID, API base URL ইত্যাদি)

Release build-এ যে মানগুলো compile-time-এ ঢোকাতে হয় — যেমন আসল AdMob ID — সেগুলো caller workflow-এর `dart-defines` input-এ দিন, প্রতি লাইনে একটি `KEY=VALUE`। প্রতিটি লাইন `flutter build apk/appbundle`-এ `--dart-define=KEY=VALUE` হয়ে যায়; খালি value দিলে সেই key skip হয় এবং app-এর নিজের default (যেমন Google-এর test ad unit) বহাল থাকে।

Gradle/`AndroidManifest.xml`-এর placeholder-এর মতো যে মানগুলো environment variable থেকে পড়া হয়, সেগুলো `build-env` input-এ একই ভাবে দিন — build step-গুলোর জন্য export হয়।

```yaml
jobs:
  publish:
    uses: Keshab1997/flutter-builder/.github/workflows/publish-release.yml@v1.8.1
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

মানগুলো caller repo-র **Settings → Secrets and variables → Actions → Variables**-এ রাখলে workflow file-এ hardcode করতে হয় না। মনে রাখবেন: dart-define-এর মান binary-র ভিতরে চলে যায় — AdMob ID public identifier, এতে সমস্যা নেই; কিন্তু API key/password এভাবে দেবেন না। AAB step-এর Gradle fallback-ও একই define পায়, তাই strip-workaround path দিয়ে গেলেও test ID দিয়ে bundle তৈরি হবে না।

`ANDROID_KEYSTORE_BASE64` secret থাকলে APK-only build-ও এখন upload key দিয়ে sign হয় (আগে শুধু AAB/Release-এ হত) — যে project-এর Gradle `key.properties` ছাড়া release build-ই করতে দেয় না, তার APK build এতে আর fail করে না।

## Firebase config file git-এ না রেখে build করা (v1.5.1+)

`google-services.json` / `GoogleService-Info.plist`-এর মান নিজে থেকে secret নয়, তবুও git-এ থাকলে যে কেউ সেই config দিয়ে নিজের build আপনার Firebase project-এর দিকে তাক করে Firestore/Auth-এ load দিতে পারে। তাই ফাইল দুটো base64 করে secret-এ রাখুন; build-এর আগে workflow সেগুলো লিখে দেবে।

```bash
base64 -w0 android/app/google-services.json | gh secret set GOOGLE_SERVICES_JSON_BASE64
base64 -w0 ios/Runner/GoogleService-Info.plist  | gh secret set GOOGLE_SERVICES_PLIST_BASE64
```

**দুটো রাস্তা আছে — যদি secret ব্যবহার করতে চান, দ্বিতীয়টি ব্যবহার করুন:**

```yaml
    # ১) Variable / plain value — with: input দিয়ে
    with:
      google-services-json-base64: ${{ vars.GOOGLE_SERVICES_JSON_BASE64 }}

    # ২) Secret — workflow-এর ভিতর থেকে পড়া হয় (secret সরাসরি with:-এ দেওয়া যায় না)
    secrets: inherit          # অথবা নিচের মতো explicit mapping
```

```yaml
    secrets:
      GOOGLE_SERVICES_JSON_BASE64: ${{ secrets.GOOGLE_SERVICES_JSON_BASE64 }}
      GOOGLE_SERVICES_PLIST_BASE64: ${{ secrets.GOOGLE_SERVICES_PLIST_BASE64 }}
```

> ⚠️ **GitHub Actions-এ `with:` input-এ `secrets` context পাওয়া যায় না।**
> `with: google-services-json-base64: ${{ secrets.X }}` লিখলে workflow টি কোনো job ছাড়াই
> fail হবে। Secret হলে `secrets:`/`secrets: inherit` ব্যবহার করুন, অথবা মানটি
> repository **Variable**-এ রাখুন।

| Input / secret | লেখা হয় |
|---|---|
| `google-services-json-base64` / `GOOGLE_SERVICES_JSON_BASE64` | `<working-directory>/android/app/google-services.json` |
| `google-services-plist-base64` / `GOOGLE_SERVICES_PLIST_BASE64` | `<working-directory>/ios/Runner/GoogleService-Info.plist` |

দুটো input-ই optional — খালি থাকলে step-টি skip হয় এবং checkout-এর ফাইল অপরিবর্তিত থাকে, তাই ফাইলটি এখনো git-এ track করা project-ও আগের মতো চলবে। Step-টি checkout-এর ঠিক পরে চলে, ফলে Gradle-এর `if (file("google-services.json").exists())` guard ঠিকমতো কাজ করে। Decode-এর পর JSON/plist validate করা হয়, তাই ভুল base64 দিলে build পরে না শেষে fail হবে — শুরুতেই ধরা পড়বে।

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
    uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.8.1
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
| `fail-on-placeholders` | `false` (wrapper-এ `true`) | Google test ad ID / `com.example.*` থাকলে fail; debug-signing fallback-এ warning |
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

সেখানে `android-release-apk` অথবা `android-release-aab` পাওয়া যাবে। Artifact ZIP হিসেবে download হয়; unzip করলে APK/AAB পাওয়া যাবে।

GitHub Release-এ publish করা APK/AAB Actions artifact retention শেষ হলেও expire হয় না; Release delete না করা পর্যন্ত থাকে।

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


## Release version নিয়ম

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

প্রতিটি Play Store upload-এর আগে version code অবশ্যই বাড়াতে হবে। একই GitHub tag আগে থেকে থাকলে release workflow ইচ্ছাকৃতভাবে fail করবে।

## Test না থাকলে কী হবে?

`test/` folder-এ `*_test.dart` file থাকলে `flutter test` চলবে। Test file না থাকলে workflow পরিষ্কার message দিয়ে test step skip করবে। Analyze ও format check চলবে।

## Flutter app subfolder-এ থাকলে

Monorepo-তে app যদি `apps/mobile` folder-এ থাকে:

```yaml
permissions:
  contents: read

jobs:
  build:
    uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.8.1
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

তারপর formatted code commit করুন। Manual build/release-এ প্রয়োজন হলে checks বন্ধ রাখা যায়:

```yaml
run-format-check: false
run-analyze: false
run-tests: false
```

তবে আলাদা CI workflow-এ validation চালু রাখাই ভালো।

## Version update পদ্ধতি

Central workflow-তে পরীক্ষিত পরিবর্তনের পর নতুন tag দিন, যেমন:

```bash
git tag v1.5.0
git push origin v1.5.0
```

wrapper (`publish-release.yml`) ভেতরে `flutter-build.yml`-কে নিজের ট্যাগেই পিন করে, তাই নতুন ট্যাগ দেওয়ার সময় wrapper-এর ভিতরের pin-টাও একই ট্যাগে বাড়াতে হবে — নাহলে পুরোনো builder চালু থাকবে।

Projectগুলো exact tag দিয়ে pin করতে পারে:

```yaml
uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.8.1
```

## প্রয়োজনীয় GitHub Secrets

Signed AAB অথবা GitHub Release publishing-এর জন্য app repository-তে প্রয়োজন:

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

### Agent দিয়ে secret সেট করান

হাতে না করে AI agent দিয়ে করাতে চাইলে [docs/AGENT_SECRETS_SETUP.md](docs/AGENT_SECRETS_SETUP.md)
টি agent-কে দিন — সে local file (`google-services.json`, keystore, `key.properties`)
খুঁজে নিয়ে base64 encode করে GitHub Actions-এ বসিয়ে দেবে, কোনো value chat-এ না
দেখিয়ে। দুটো জিনিসই সেখানে guard করা আছে:

- `base64 -w0` macOS-এ fail করে — ফলে **empty secret** সেট হয়। স্ক্রিপ্ট
  `openssl base64 -A` ব্যবহার করে (macOS + Linux দুটোতেই চলে)।
- 40 character-এর ছোট কোনো value সেট করতেই দেবে না।

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
- Reusable workflow-কে version tag বা commit SHA দিয়ে pin করুন।
- Project-specific signing secrets app project-এর repository-তেই রাখুন।
- Publish workflow APK এবং AAB—দুটিকেই একই configured release key দিয়ে sign করে।

## বর্তমান scope

এই workflow APK/AAB তৈরি করে, artifact সংরক্ষণ করে এবং optional GitHub Release publish করে। v1.4.0 থেকে `play-track` input দিয়ে AAB সরাসরি Google Play-এর internal/alpha/beta track-এ upload করা যায়, আর `firebase-groups` দিয়ে Firebase App Distribution-এ পাঠানো যায়। Play-এর **production** track deliberately বাদ — release-এর আগে staged rollout manually review করা safer।
