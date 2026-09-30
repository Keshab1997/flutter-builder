# Flutter Builder

Flutter project-এর জন্য reusable GitHub Actions workflows। প্রতিটি app repository-তে ছোট caller workflow যোগ করলেই CI, Android build/release বা web preview চালানো যায়। এই repository-তে Flutter/Android SDK, keystore বা কোনো credential রাখা হয় না।

## কোন workflow কী করে?

| Workflow file | GitHub Actions-এ দেখানো নাম | কখন চলে / কী করে |
|---|---|---|
| `ci.yml` | **Flutter CI — Format, Analyze & Test** | Push, pull request ও manual run-এ Dart format, analyze, test/coverage চালায়; APK/AAB বানায় না। |
| `manual-build.yml` | **Build Android APK or AAB (Manual)** | Actions থেকে বেছে নিলে APK অথবা AAB build করে artifact দেয়। |
| `publish-release.yml` | **Publish Signed Android Release** | একবার signed APK/AAB build করে GitHub Release প্রকাশ করে; চাইলে একই AAB Google Play Internal testing-এ upload ও Play release notes পাঠায়। |
| `web-preview.yml` | **Deploy Flutter Web Preview (GitHub Pages)** | Push/PR-এ web build করে branch-ভিত্তিক Pages preview প্রকাশ করে; branch delete হলে সেই preview gh-pages থেকে মুছে দেয়। |


## দ্রুত setup (প্রস্তাবিত)

GitHub-এ থাকা Flutter app-এর directory থেকে Linux, macOS বা Windows Git Bash-এ চালান:

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.8.8/scripts/install.sh | bash
```

Installer `.github/workflows/`-এ চারটি caller workflow বসায়। Monorepo-তে app-এর directory নির্দিষ্ট করুন:

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.8.8/scripts/install.sh | bash -s -- --app-dir apps/mobile --app-name "My App"
```

Installer-এ Flutter SDK লাগে না। এটি git commit/push করে না, secrets তৈরি করে না, বা workflow run শুরু করে না। ফাইলগুলো দেখে তারপর commit/push করুন।

### Installer options

- `--app-dir DIR`: monorepo-তে Flutter app-এর path (repository root থেকে)
- `--app-name NAME`: release-এ দেখানোর app name; না দিলে `pubspec.yaml`-এর নাম
- `--ref v1.8.8`: reusable workflow version pin; default `v1.8.8`
- `--dry-run`: কোনো ফাইল না লিখে পরিবর্তন দেখায়
- `--force`: আলাদা/কাস্টম workflow backup নিয়ে replace করে

Installer existing workflow ভিন্ন হলে নিরাপত্তার জন্য থেমে যায়; `--force` ছাড়া replace করে না। আগে দেখে নিন, কারণ custom workflow replace হলে আচরণ বদলাতে পারে।

### আগে install করা project update করুন (bump-ref, v1.8.8+)

নতুন version tag এলে প্রতিটা project directory থেকে এক লাইন চালালেই সব caller-এর `@ref` নতুন tag-এ চলে যায়; custom job, comment আর inputs অক্ষত থাকে:

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.8.8/scripts/bump-ref.sh | bash
```

একসাথে অনেক project update করতে:

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.8.8/scripts/bump-ref.sh -o /tmp/bump-ref.sh
for d in ~/projects/*/; do (cd "$d" && bash /tmp/bump-ref.sh --dry-run); done   # আগে দেখুন
for d in ~/projects/*/; do (cd "$d" && bash /tmp/bump-ref.sh); done            # তারপর লিখুন
```

- `--ref TAG_OR_SHA`: নির্দিষ্ট pin দিন (default `v1.8.8`); `--dry-run`: কিছু না লিখে দেখায়
- শুধু `uses:` লাইনের `@ref` বদলায় — `install.sh --force`-এর মতো পুরো ফাইল replace করে না, তাই customize করা workflow-ও নিরাপদ
- কোনো flutter-builder pin না পেলে ভুল directory ধরে error দেয়

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

#### Branch delete হলে preview cleanup (v1.8.2+)

প্রতিটি preview gh-pages-এ ৩০–৬০ MB জায়গা নেয় আর branch মুছে গেলেও folder পড়ে থাকে। তাই `web-preview.yml`-এর install করা version-এ `delete` trigger সহ দুটি job থাকে: `preview` (push/PR) আর `cleanup` (branch delete)। Branch মুছে ফেললে `preview/<branch>` folder-টা gh-pages থেকে চলে যায়, ফলে gh-pages অকারণে বাড়ে না।

কেন দুটো job একই ফাইলে: `delete` event শুধু সেই repository-তেই fire করে যেখানে branch-টা ছিল, আর delete-triggered workflow সবসময় **default branch** থেকে চলে — তাই `cleanup` job caller ফাইলেই থাকতে হবে এবং merge হওয়ার পরেই কাজ করবে।

Reusable workflow-টা আলাদাভাবে ব্যবহার করতে চাইলে (installer ছাড়া):

```yaml
name: Web preview + cleanup
on:
  push:
  pull_request:
  delete:

permissions:
  contents: write
  pull-requests: write

concurrency:
  # একটাই gh-pages, তাই একটাই lane: deploy আর cleanup কখনো একসাথে push করে না।
  group: web-preview
  cancel-in-progress: false

jobs:
  preview:
    if: github.event_name != 'delete'
    uses: Keshab1997/flutter-builder/.github/workflows/web-preview.yml@v1.8.8
    with:
      working-directory: "."
      comment-on-pr: true
    secrets: inherit

  cleanup:
    if: github.event_name == 'delete' && github.event.ref_type == 'branch'
    uses: Keshab1997/flutter-builder/.github/workflows/preview-cleanup.yml@v1.8.8
    with:
      # delete event-এ payload called workflow-এ পড়া যায় না; তাই caller নিজেই
      # deleted ref-টা পাঠায় (এটা না দিলে cleanup চুপচাপ কিছুই মোছে না)।
      branch-name: ${{ github.event.ref }}
    permissions:
      contents: write
```

Cleanup যেভাবে branch name পরিষ্কার করে তা deploy-এর সাথে **হুবহু** একই (`Feature/New Thing` → `preview/feature-new-thing`) এবং একটা test দুটোকে মিলিয়ে রাখে। নিরাপত্তার জন্য `main`/`master` (`keep-branches` দিয়ে বদলানো যায়) skip হয়, tag delete-এ কিছু হয় না, pages root বা তার বাইরের path মুছতে **refuse** করে, আর preview না থাকলে চুপচাপ no-op। `destination-dir` কাস্টম হলে সেটাও সম্মান করে; `dry-run: true` দিয়ে আগে পরীক্ষা করা যায়। কী মুছল/কেন ছাড়ল তা step summary-তে লেখা থাকে। সব preview একটাই concurrency lane-এ (`group: web-preview`) চলে, কারণ gh-pages একটাই: deploy action compare-and-swap দিয়ে push করে, তাই দুই রান একসাথে লিখলে একটা reject হয় — আর branch update করলেই push ও pull_request দুটো ইভেন্ট একসাথে চলে, ফলে collision সহজ। Queue করার ফলে delete-এর cleanup কোনো চলমান deploy বাতিল করে না; reject হলে cleanup fetch + rebase করে ৫ বার চেষ্টা করে। এই ফিক্সগুলো **v1.8.6**-এ আছে। **গুরুত্বপূর্ণ:** delete event-এর payload called workflow-এর ভেতরে পড়া যায় না, আর delete event-এ `github.ref_name` হলো *default branch* — তাই আগে cleanup `main` ধরে নিয়ে keep-branches-এ skip হয়ে চুপচাপ কিছুই মোছেনি। এখন caller-ই deleted ref পাঠায় (`branch-name: ${{ github.event.ref }}`), আর reusable workflow `github.event.ref`-ও দেখে; কোনো ref না পেলে `::warning::` দিয়ে সেটা জানায় — নীরব no-op নয়।

### About → Website link নিজে সেট (v1.8.6+)

Repo-র পেজে **Settings → About → Website** ঘরে বসানো লিংকটা web preview hook করে রাখা যায়, যাতে প্রজেক্ট পেজ আর অ্যাপ দুটোই একই জায়গায় নিয়ে যায়। `set-about-link: true` দিলে default branch-এ push হলে (অর্থাৎ merge হলে) workflow নিজেই ওই ঘরটা আপডেট করে।

কেন একটা credential লাগে: repo settings বদলাতে GitHub API-তে **Administration: write** দরকার, যেটা Actions-এর নিজের `GITHUB_TOKEN`-এ **নেই**। তাই দুটো পথ:

**পথ ১ — GitHub App (টোকেন নিজে rotate হয়)**

```yaml
# caller-এ
    with:
      set-about-link: true
      app-id: ${{ vars.APP_ID }}
```
Repo-তে (Settings → Secrets and variables → Actions): secret `APP_PRIVATE_KEY` = app-এর private key (.pem), variable `APP_ID` = app id। App-টা যেন repo-তে installed থাকে আর তার `administration: write` permission থাকে।

**পথ ২ — Fine-grained PAT (ক্ষমতা সবচেয়ে কম)**

PAT বানান: [fine-grained token](https://github.com/settings/personal-access-tokens/new) → শুধু এই repo → permission **Administration: Read and write** (বাকি সব No access)। তারপর secret `ABOUT_LINK_TOKEN`-এ রাখুন। `app-id` খালি থাকলে workflow PAT-ই ব্যবহার করে।

নিরাপত্তার নিয়মগুলো:

- **শুধু default branch-এর push-এ চলে** → লিংক সবসময় stable `preview/main`-এর মতো, কোনো branch preview নয়
- **আপনার নিজের website কখনো মুছে দেয় না** — About খালি না থাকলে আর সেটা আমাদের preview না হলে skip + `::warning::`; `about-link-overwrite: true` দিলে তবেই বদলায়
- **আগে যাচাই করে URL লাইভ (HTTP 200)** — মরা লিংক বসায় না
- একই লিংক থাকলে কিছুই করে না (idempotent); কী বদলাল তা Step summary-তে দেখা যায়
- credential না থাকলে কিছুই বদলায় না, শুধু একটা `::notice::` দেখায়

## Reusable workflow নিজে যোগ করা

Installer ব্যবহার না করলে `examples/project-workflows/` থেকে দরকারি YAML app repository-র `.github/workflows/`-এ কপি করুন। Production ব্যবহারে reusable workflow-গুলোকে version tag-এ pin করুন, যেমন:

```yaml
uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.8.8
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
