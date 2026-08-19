# Flutter Builder

একটি reusable GitHub Actions workflow, যা বিভিন্ন Flutter project-এর জন্য একই central setup ব্যবহার করে:

- Dart format check
- `flutter analyze`
- `flutter test`
- Manual release APK build
- Signed release APK/AAB build
- APK/AAB artifact download
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
└── Flutter source + ছোট caller workflow

my-second-app (আলাদা repository)
└── Flutter source + একই caller workflow
```

## প্রথমবার setup

### ধাপ ১: Stable builder version ব্যবহার করুন

App project-এর caller workflow-তে tested tag pin করুন:

```yaml
uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.1.0
```

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

## Artifact download

Workflow সফল হলে:

```text
Actions → Workflow run → Artifacts
```

সেখানে `android-release-apk` অথবা `android-release-aab` পাওয়া যাবে। Artifact ZIP হিসেবে download হয়; unzip করলে APK/AAB পাওয়া যাবে।

GitHub Release-এ publish করা APK/AAB Actions artifact retention শেষ হলেও expire হয় না; Release delete না করা পর্যন্ত থাকে।

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
    uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.1.0
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
git tag v1.1.0
git push origin v1.1.0
```

Projectগুলো exact tag দিয়ে pin করতে পারে:

```yaml
uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.1.0
```

## প্রয়োজনীয় GitHub Secrets

Signed AAB অথবা GitHub Release publishing-এর জন্য app repository-তে প্রয়োজন:

```text
ANDROID_KEYSTORE_BASE64
KEYSTORE_PASSWORD
KEY_ALIAS
KEY_PASSWORD
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

এই workflow APK/AAB তৈরি করে, artifact সংরক্ষণ করে এবং optional GitHub Release publish করে। Google Play Console-এ automatic upload রাখা হয়নি—generated AAB Play Console-এ manually upload করতে হবে।
