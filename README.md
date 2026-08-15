# Flutter Builder

একটি reusable GitHub Actions workflow, যা বিভিন্ন Flutter project-এর জন্য একই central setup ব্যবহার করে:

- Dart format check
- `flutter analyze`
- `flutter test`
- Manual release APK build
- Signed release AAB build
- APK/AAB artifact download
- Flutter ও Gradle cache

> এই repository-তে Flutter SDK, Android SDK, keystore অথবা password রাখা হয় না। GitHub Actions প্রয়োজনের সময় SDK setup করে।

## Repository design

```text
flutter-builder (এই public repository)
└── reusable build workflow

my-first-app (আলাদা repository)
└── Flutter source + ছোট caller workflow

my-second-app (আলাদা repository)
└── Flutter source + একই caller workflow
```

## প্রথমবার setup

### ধাপ ১: এই repository GitHub-এ দিন

GitHub-এ `flutter-builder` নামে একটি **Public** repository তৈরি করুন। এই folder-এর সব files সেখানে upload/push করুন। এরপর একটি stable version tag তৈরি করুন:

```bash
git tag v1
git push origin v1
```

Tag না বানানো পর্যন্ত caller file-এ সাময়িকভাবে `@main` ব্যবহার করা যায়। স্থিতিশীল ব্যবহারের জন্য `@v1` ভালো।

### ধাপ ২: App project-এ CI যোগ করুন

App repository-তে directory তৈরি করুন:

```text
.github/workflows/
```

এই repository-এর `examples/project-workflows/ci.yml` file copy করে app repository-তে রাখুন:

```text
.github/workflows/ci.yml
```

তারপর file-এর এই অংশ:

```yaml
uses: YOUR_USERNAME/flutter-builder/.github/workflows/flutter-build.yml@v1
```

নিজের GitHub username দিয়ে পরিবর্তন করুন:

```yaml
uses: আপনার-ইউজারনেম/flutter-builder/.github/workflows/flutter-build.yml@v1
```

এখন Pull Request বা `main` branch-এ push হলে format, analyze ও test চলবে। সাধারণ code change-এ APK/AAB build হবে না।

### ধাপ ৩: Manual APK/AAB build যোগ করুন

`examples/project-workflows/manual-build.yml` copy করে app repository-তে রাখুন:

```text
.github/workflows/manual-build.yml
```

এখানেও `YOUR_USERNAME` পরিবর্তন করুন। এরপর:

```text
App repository → Actions → Manual Android Build → Run workflow
```

- `apk`: ফোনে install/test করার release APK
- `aab`: Play Store-এর signed Android App Bundle

AAB-এর আগে [Android signing নির্দেশিকা](docs/ANDROID_SIGNING.md) অনুসরণ করুন।

### ধাপ ৪: Tag দিলে automatic AAB (ঐচ্ছিক)

`examples/project-workflows/release.yml` copy করুন। এরপর app repository-তে release tag push করলে AAB build হবে:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## Artifact download

Workflow সফল হলে:

```text
Actions → Workflow run → Artifacts
```

সেখানে `android-release-apk` অথবা `android-release-aab` পাওয়া যাবে। Artifact ZIP হিসেবে download হয়; unzip করলে APK/AAB পাওয়া যাবে।

## Test না থাকলে কী হবে?

`test/` folder-এ `*_test.dart` file থাকলে `flutter test` চলবে। Test file না থাকলে workflow পরিষ্কার message দিয়ে test step skip করবে। Analyze ও format check চলবে।

## Flutter app subfolder-এ থাকলে

Monorepo-তে app যদি `apps/mobile` folder-এ থাকে:

```yaml
jobs:
  build:
    uses: YOUR_USERNAME/flutter-builder/.github/workflows/flutter-build.yml@v1
    with:
      working-directory: apps/mobile
      build-apk: true
```

## Format check fail করলে

নিজের development machine-এ চালান:

```bash
dart format .
```

তারপর formatted code commit করুন। শুরুতে format check বন্ধ করতে caller workflow-এ দেওয়া যায়:

```yaml
run-format-check: false
```

তবে দীর্ঘমেয়াদে চালু রাখাই ভালো।

## Version update পদ্ধতি

Central workflow-তে পরীক্ষিত পরিবর্তনের পর নতুন tag দিন, যেমন:

```bash
git tag v1.1.0
git push origin v1.1.0
```

Projectগুলো exact tag দিয়ে pin করতে পারে:

```yaml
uses: YOUR_USERNAME/flutter-builder/.github/workflows/flutter-build.yml@v1.1.0
```

সহজ update-এর জন্য `@v1`, সর্বোচ্চ reproducibility/security-এর জন্য exact version বা commit SHA ব্যবহার করুন।

## প্রয়োজনীয় GitHub Secrets

শুধু signed AAB-এর জন্য app repository-তে প্রয়োজন:

```text
ANDROID_KEYSTORE_BASE64
KEYSTORE_PASSWORD
KEY_ALIAS
KEY_PASSWORD
```

APK, analyze ও test-এর জন্য এগুলো প্রয়োজন নেই। বিস্তারিত: [docs/ANDROID_SIGNING.md](docs/ANDROID_SIGNING.md)

## নিরাপত্তা

- GitHub token, keystore, `.env`, service-account JSON commit করবেন না।
- Personal Access Token chat-এ কাউকে দেবেন না।
- Reusable workflow-কে version tag বা commit SHA দিয়ে pin করুন।
- Project-specific signing secrets app project-এর repository-তেই রাখুন।

## বর্তমান scope

এই version APK/AAB তৈরি ও artifact হিসেবে দেয়। Google Play Console-এ automatic upload ইচ্ছাকৃতভাবে রাখা হয়নি—প্রথমে AAB manually upload করা সহজ ও নিরাপদ। পরে আলাদা optional release workflow হিসেবে যোগ করা যাবে।
