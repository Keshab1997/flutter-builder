# Flutter Builder

Flutter project-এর জন্য reusable GitHub Actions workflows। প্রতিটি app repository-তে ছোট caller workflow যোগ করলেই CI, Android build/release বা web preview চালানো যায়। এই repository-তে Flutter/Android SDK, keystore বা কোনো credential রাখা হয় না।

## কোন workflow কী করে?

| Workflow file | GitHub Actions-এ দেখানো নাম | কখন চলে / কী করে |
|---|---|---|
| `ci.yml` | **Flutter CI — Format, Analyze & Test** | Push, pull request ও manual run-এ Dart format, analyze, test/coverage চালায়; APK/AAB বানায় না। |
| `manual-build.yml` | **Build Android APK or AAB (Manual)** | Actions থেকে বেছে নিলে APK অথবা AAB build করে artifact দেয়। |
| `publish-release.yml` | **Publish Signed Android Release** | একবার signed APK/AAB build করে GitHub Release প্রকাশ করে; চাইলে একই AAB Google Play Internal testing-এ upload ও Play release notes পাঠায়। |
| `web-preview.yml` | **Deploy Flutter Web Preview (GitHub Pages)** | Push/PR-এ web build করে branch-ভিত্তিক Pages preview প্রকাশ করে। |


## দ্রুত setup (প্রস্তাবিত)

GitHub-এ থাকা Flutter app-এর directory থেকে Linux, macOS বা Windows Git Bash-এ চালান:

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.8.1/scripts/install.sh | bash
```

Installer `.github/workflows/`-এ চারটি caller workflow বসায়। Monorepo-তে app-এর directory নির্দিষ্ট করুন:

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.8.1/scripts/install.sh | bash -s -- --app-dir apps/mobile --app-name "My App"
```

Installer-এ Flutter SDK লাগে না। এটি git commit/push করে না, secrets তৈরি করে না, বা workflow run শুরু করে না। ফাইলগুলো দেখে তারপর commit/push করুন।

### Installer options

- `--app-dir DIR`: monorepo-তে Flutter app-এর path (repository root থেকে)
- `--app-name NAME`: release-এ দেখানোর app name; না দিলে `pubspec.yaml`-এর নাম
- `--ref v1.8.1`: reusable workflow version pin; default `v1.8.1`
- `--dry-run`: কোনো ফাইল না লিখে পরিবর্তন দেখায়
- `--force`: আলাদা/কাস্টম workflow backup নিয়ে replace করে

Installer existing workflow ভিন্ন হলে নিরাপত্তার জন্য থেমে যায়; `--force` ছাড়া replace করে না। আগে দেখে নিন, কারণ custom workflow replace হলে আচরণ বদলাতে পারে।

## Build ও release

- **CI**: format, analyze ও tests চালায়—সাধারণত pull request review-এর জন্য।
- **Manual APK**: ফোনে install করে পরীক্ষা করার artifact। Actions → **Build Android APK or AAB (Manual)** → Run workflow → `apk` বাছুন।
- **Manual AAB**: Play Store-এ upload করার Android App Bundle। একই workflow-তে `aab` বাছুন।
- **Publish release**: Actions → **Publish Signed Android Release** → Run workflow। এটি version/tag ও GitHub Release প্রকাশ করে, তাই আগে `pubspec.yaml`-এ version বাড়ান।

### Android signing (AAB/release-এর জন্য)

Repository → Settings → Secrets and variables → Actions-এ signing secrets যোগ করুন। বিস্তারিত ও keystore তৈরির ধাপ: [`docs/ANDROID_SIGNING.md`](docs/ANDROID_SIGNING.md).

```text
ANDROID_KEYSTORE_BASE64
KEYSTORE_PASSWORD
KEY_ALIAS
KEY_PASSWORD
```

`pubspec.yaml`-এ version-এর উদাহরণ:

```yaml
version: 1.2.3+4
```

`1.2.3` হলো user-facing version; `4` হলো Android version code এবং প্রতিটি Play Store release-এ বাড়তে হবে। Release workflow-তে placeholder app ID (`com.example.*`) বা Google test ad ID থাকলে build বন্ধ হতে পারে—publish-এর আগে সেগুলো বদলান।

### Play Store Internal testing (optional)

দুটি আলাদা AAB build workflow লাগবে না: `publish-release.yml`-এ Play upload option চালু করলে একই signed AAB GitHub Release-এ যোগ হবে এবং Google Play Internal testing-এও যাবে। App repo-তে `PLAY_SERVICE_ACCOUNT_JSON` ও signing secrets দিন, তারপর caller workflow-তে Play option/package name সেট করুন। `distribution/whatsnew/`-এ locale notes থাকলে সেগুলোও Play-এ যাবে। পূর্ণ ধাপ: [`docs/PLAY_INTERNAL_TESTING.md`](docs/PLAY_INTERNAL_TESTING.md)। Secret কখনো public builder repository-তে দেবেন না.

### Web preview (optional)

`web-preview.yml` push/PR-এ Flutter web build deploy করে। App-এ `web/` folder থাকতে হবে। একবার repository-তে **Settings → Pages → Build and deployment → Deploy from a branch → `gh-pages` (root)** নির্বাচন করুন। Preview URL Actions run summary-তে দেখা যায়। এটি hot reload নয়; web support নেই এমন plugin-ও কাজ নাও করতে পারে.

## Reusable workflow নিজে যোগ করা

Installer ব্যবহার না করলে `examples/project-workflows/` থেকে দরকারি YAML app repository-র `.github/workflows/`-এ কপি করুন। Production ব্যবহারে reusable workflow-গুলোকে version tag-এ pin করুন, যেমন:

```yaml
uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.8.1
```

`@main` development-এর জন্য চললেও release workflow-তে version tag বা commit SHA বেশি নির্ভরযোগ্য।

## অতিরিক্ত সুবিধা

Reusable build workflow-তে প্রয়োজনমতো format/analyze/test, coverage, test matrix, `build_runner`/`gen-l10n`, FVM, APK/AAB, per-ABI APK, obfuscation, symbol upload, size limit, signing verification, web build/deploy এবং Play/Firebase distribution চালু করা যায়। উদাহরণ ও সব input-এর বিবরণ: [`flutter-build.yml`](.github/workflows/flutter-build.yml).

Build-time value-এর জন্য `dart-defines` ব্যবহার করা যায়। Secret কখনও workflow YAML-এ লিখবেন না; GitHub Actions secrets ব্যবহার করুন। `google-services.json`/Firebase config secret থেকে inject করার পদ্ধতি এবং release preflight-এর বিবরণ: [`docs/AGENT_SECRETS_SETUP.md`](docs/AGENT_SECRETS_SETUP.md).

## Troubleshooting / প্রস্তুতি যাচাই

Flutter app repository-র root থেকে doctor চালান:

```bash
bash /path/to/flutter-builder/scripts/doctor.sh
```

এটি GitHub CLI authentication, Android/signing config, Firebase config, workflow setup ও কিছু placeholder পরীক্ষা করে। Doctor pass করলেই build নিশ্চিত সফল হবে এমন নয়; প্রকৃত build চালিয়ে Actions log দেখুন।

## Security

- Keystore ও credentials এই repository-তে রাখবেন না; GitHub Actions secrets ব্যবহার করুন।
- `secrets/`, `.jks`, `.keystore`, private key বা token commit করবেন না।
- Release ও repository write permission শুধু প্রয়োজনীয় workflow-কে দিন।
- Release-এর আগে workflow YAML, permissions, app ID, version ও signing configuration review করুন।

## Repository contents

- `.github/workflows/flutter-build.yml` — reusable CI/build workflow
- `.github/workflows/publish-release.yml` — reusable signed release workflow
- `.github/workflows/web-preview.yml` — reusable web preview deployment
- `scripts/install.sh` — caller workflow installer
- `scripts/doctor.sh` — app configuration checker
- `examples/project-workflows/` — app repository-তে ব্যবহারের নমুনা workflow
- `docs/` — signing ও secret setup নির্দেশিকা

License: [MIT](LICENSE).
