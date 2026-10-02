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
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.9.1/scripts/install.sh | bash
```

Installer `.github/workflows/`-এ চারটি caller workflow বসায়। Monorepo-তে app-এর directory নির্দিষ্ট করুন:

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.9.1/scripts/install.sh | bash -s -- --app-dir apps/mobile --app-name "My App"
```

Installer-এ Flutter SDK লাগে না। এটি git commit/push করে না, secrets তৈরি করে না, বা workflow run শুরু করে না। ফাইলগুলো দেখে তারপর commit/push করুন।

### Installer options

- `--app-dir DIR`: monorepo-তে Flutter app-এর path (repository root থেকে)
- `--app-name NAME`: release-এ দেখানোর app name; না দিলে `pubspec.yaml`-এর নাম
- `--ref v1.9.1`: reusable workflow version pin; default `v1.9.1`
- `--dry-run`: কোনো ফাইল না লিখে পরিবর্তন দেখায়
- `--force`: আলাদা/কাস্টম workflow backup নিয়ে replace করে

Installer existing workflow ভিন্ন হলে নিরাপত্তার জন্য থেমে যায়; `--force` ছাড়া replace করে না। আগে দেখে নিন, কারণ custom workflow replace হলে আচরণ বদলাতে পারে।

### আগে install করা project update করুন (bump-ref)

নতুন version tag এলে প্রতিটা project directory থেকে এক লাইন চালালেই সব caller-এর `@ref` নতুন tag-এ চলে যায়; custom job, comment আর inputs অক্ষত থাকে:

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.9.1/scripts/bump-ref.sh | bash
```

একসাথে অনেক project update করতে:

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.9.1/scripts/bump-ref.sh -o /tmp/bump-ref.sh
for d in ~/projects/*/; do (cd "$d" && bash /tmp/bump-ref.sh --dry-run); done   # আগে দেখুন
for d in ~/projects/*/; do (cd "$d" && bash /tmp/bump-ref.sh); done            # তারপর লিখুন
```

- `--ref TAG_OR_SHA`: নির্দিষ্ট pin দিন (default `v1.9.1`); `--dry-run`: কিছু না লিখে দেখায়
- v1.9.0 বা তার আগের bump-ref-এর default ছিল `v1.8.8` — তাই পুরোনো version থেকে চালালে `--ref` স্পষ্ট দিন
- শুধু `uses:` লাইনের `@ref` বদলায় — `install.sh --force`-এর মতো পুরো ফাইল replace করে না, তাই customize করা workflow-ও নিরাপদ
- কোনো flutter-builder pin না পেলে ভুল directory ধরে error দেয়

## Agent pack (v1.9.0+) — agent-দের কাজ দ্রুত করার জন্য

AI agent দিয়ে কাজ করালে সময় নষ্ট হয় দুটো জায়গায়: push করার **আগে** ভুল ধরা পড়ে না, আর push-এর **পরে** CI-র ফল জানতে বারবার হাতে চেক করতে হয়। এই pack দুটোই কমায় — Flutter SDK লাগে না, শুধু python3 (≥3.8):

```bash
curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-builder/v1.9.1/scripts/install-agent-pack.sh | bash
```

Repository root-এ যা বসে:

| ফাইল | কী করে |
|---|---|
| `tool/preflight.py` | Dart code-এ অব্যবহৃত private widget/function, অব্যবহৃত optional constructor parameter, অব্যবহৃত import, `print()` ছোঁয়া (avoid_print), একবারও ব্যবহার না হওয়া private field, orphan ফাইল ও একই নামের দুটো class একসাথে import — সব খুঁজে বের করে। খরচ ১ সেকেন্ড (SDK ছাড়া), অথচ ঠিক এই ভুলগুলোই push-কে লাল করে |
| `tool/ci_watch.py` | commit-এর GitHub Actions run-গুলো নিজে থেকে watch করে; শেষ হলে প্রতিটা workflow-র ফল আর fail করা job-এর আসল error লাইন ছাপায় (token: `--token-file`, `$GITHUB_TOKEN`/`$GH_TOKEN`, বা `gh auth token`) |
| `tool/agent_loop.py` | এক command-এ পুরো loop: preflight → secret guard → commit → push → CI watch। main-এ commit করা বা credential-এর মতো ফাইল (`keystore`, `.env`, `google-services.json`) stage করা **আগেই আটকে দেয়**, তাই agent ভুল করে একটা ধাপও বাদ দিতে পারে না |
| `AGENTS.md` | agent-দের playbook: এক change = এক push loop, CI map, CI log সস্তায় পড়া, secrets নিয়ম, আর কখন human-কে থামতে হবে |

```bash
python3 tool/preflight.py                                   # push-এর আগে, ১ সেকেন্ড
python3 tool/agent_loop.py -m "fix(profile): guard a null avatar"
python3 tool/agent_loop.py -m "..." --amend                 # আগের commit ঠিক করা
python3 tool/agent_loop.py -m "..." --draft-pr              # branch + draft PR (draft-এ CI চলে না)
python3 tool/agent_loop.py -m "..." --ready                 # draft প্রস্তুত → CI শুরু
python3 tool/agent_loop.py -m "..." --no-watch              # শুধু push
```

Exit code: `0` = push হয়েছে (আর watched হলে সব সবুজ), `1` = CI লাল বা push fail, `2` = কিছু বদলানোর আগেই আটকে দিয়েছে। `--amend` করলে push হয় `--force-with-lease` দিয়ে — কখনো খালি `--force` নয়।


`AGENTS.md` সবসময় **merge** হয়, replace নয়: `flutter-builder:agent-pack:start/end` marker-এর ভিতরের অংশটুকু update হয়, বাইরের সব লাইন (আপনার নিজের project notes) অপরিবর্তিত থাকে; ফাইল না থাকলে নতুন করে তৈরি হয়। Options: `--dry-run`, `--force`, `--help`।

### push-প্রতি duplicate run বন্ধ (নতুন caller templates)

একই commit আগে দুইবার validate হত: `push` আর `pull_request` আলাদা concurrency group-এ চলত, আর web preview lane (যা ইচ্ছাকৃতভাবে serialized) একটা আরেকটার পিছনে queue-তে দাঁড়াত। নতুন caller আর shared workflow-তে:

- `push:` শুধু `main`-এ — feature branch-এর কাজ `pull_request` event থেকেই হয় (এক run, দুটো নয়)
- **draft PR**-এ CI চলে না; *Ready for review* করলেই শুরু
- শুধু লেখা/মেটাডেটা বদলালে (`**.md`, `docs/**`, `distribution/**`) কিছুই চলে না
- shared `flutter-build.yml`-এ নতুন input `skip-draft-prs` (default `true`) — চাইলে caller থেকে বন্ধ করা যায়

আগে install করা project-এ এই আচরণ চাইলে caller-এর `on:`/`if:` অংশ hand-merge করুন বা `install.sh --force` (আগের ফাইল backup হয়); শুধু pin সরাতে চাইলে `bump-ref.sh`-ই যথেষ্ট।

## CI আরও দ্রুত — build cache (v1.10+)

Flutter SDK আর pub cache আগেই ছিল; কিন্তু Android build-এ সময় যেত **Gradle**-এর পিছনে, যা ওই cache-এর আওতায় পড়ে না। এখন:

- **Gradle dependency/wrapper cache** — `gradle/actions/setup-gradle@v4`; PR-এ শুধু পড়ে, main-এ লিখে (PR-গুলো যেন main-এর cache নষ্ট না করে)। সাধারণত **১–৩ মিনিট/রান** সাশ্রয়, তবে প্রথম রানটা ঠান্ডা — cache ভরে ওঠে main-এ একবার চালানোর পর।
- **Gradle build cache + parallel + jvmargs** — `android/gradle.properties`-এ না থাকলে নিজেই যোগ করে; আপনার নিজের লেখা কোনো লাইন কখনো বদলায় না। `configuration-cache` ইচ্ছাকৃতভাবে **যোগ করা হয় না** (কিছু plugin combo-তে ভাঙে) — চাইলে নিজের ফাইলে দিন।
- **`build_runner` output cache** — `codegen: build_runner` দিলে প্রতি রানে পূর্ণ codegen (৩০ সেকেন্ড–৩ মিনিট) না চালিয়ে `.dart_tool/build` reuse হয়; key হয় `pubspec.lock` + source hash, তাই পুরোনো generated code আটকে থাকার ঝুঁকি নেই।
- **`--no-pub`** — `flutter pub get` রানে একবারই চলে; analyze/test/build আর implicit resolve করে না।
- **`test-matrix` এখন PR-এ চলে না** (channel breakage ধরার lane main/nightly-তে যথেষ্ট) — চাইলে `test-matrix-on-pr: true`।

নতুন inputs (সবগুলোই opt-in, আগের আচরণ অপরিবর্তিত): `format-paths` (default `.`), `test-concurrency` (default 0 = Flutter-এর নিজের সেটিং), `build-mode` (default `release`; `profile` দিলে device test অনেক দ্রুত, তবে কখনো publish করার জন্য নয়), `target-platform` (যেমন `android-arm64`), `test-matrix-on-pr` (default false)।

## UI দেখা — তিন উপায় (v1.10+)

Agent কোড বদলাতে পারে, কিন্তু অ্যাপ চালিয়ে দেখতে পারে না — emulator বা হাতের ফোন তার নেই। তাই UI দেখার তিনটা রাস্তা:

| উপায় | কেমন | লাগে | খরচ |
|---|---|---|---|
| **1. Web preview** (আগেই আছে) | ব্রাউজারে **লাইভ লিংক** — ক্লিক করে ঘুরে দেখবেন | `web/` folder + Pages চালু | ~২–৪ মিনিট/run |
| **2. UI screenshots** (নতুন) | PR-এ **ছবি এমবেড** হয়ে যায়, স্ক্রল করেই দেখা যায় | `web/` folder + নিচের caller | ~২–৪ মিনিট/run |
| **3. আসল Android** | APK ফোনে বসিয়ে নিজের চোখে | signing secret | manual build + আপনার সময় |

### Web preview (লাইভ, ক্লিক করে)

```yaml
jobs:
  preview:
    uses: Keshab1997/flutter-builder/.github/workflows/web-preview.yml@v1.9.1
    with:
      working-directory: "."
      comment-on-pr: true
    secrets: inherit
```

হলো — ব্রাউজারে `preview/<branch>/` লিংক খুললে অ্যাপ চলে। এটা **interactive**, তাই এনিমেশন, স্ক্রল, টাইপ করা সব দেখা যায়। `web/` না থাকলে: `flutter create --platforms=web .` একবার চালালেই যোগ হবে।

### UI screenshots (PR-এর ভেতরে ছবি)

[`examples/project-workflows/ui-screenshots.yml`](examples/project-workflows/ui-screenshots.yml) কপি করে app repo-র `.github/workflows/`-এ বসান, ব্যাস। প্রতি PR-এ:

- web build → static server → headless Chromium → `routes` × `viewports` ধরে ছবি;
- ছবিগুলো PR-এ **comment** হয় (একই comment প্রতি push-এ update হয়, নতুন করে spam করে না), workflow artifact-এ download-ও করা যায়;
- ছবি থাকে `ui-screenshots` নামের একটা আলাদা branch-এ — GitHub markdown-এ ছবি এমবেড করতে হলে এমন public URL লাগে, artifact-এর লিংকে লগইন দরকার।

```yaml
    uses: Keshab1997/flutter-builder/.github/workflows/ui-screenshots.yml@v1.10.0
    with:
      routes: "/,/settings"          # hash strategy: '/settings' → '#/settings'
      viewports: "390x844,768x1024"  # ফোন + ছোট ট্যাবলেট
      wait-ms: 8000                  # অ্যাপ settle হওয়ার সময়
```

**যে কথা মনে রাখবেন (সৎ সীমাবদ্ধতা):**

- এটা **web build**, তাই Android-এর হুবহু চেহারা নয় — layout, রং, spacing, টেক্সট দেখা যায়; ফন্ট/platform widget একটু আলাদা লাগতে পারে।
- **Camera, Bluetooth, local notification** জাতীয় platform-only plugin web-এ চলে না। তখন ছবি ফাঁকা আসবে — script নিজেই "possibly a blank screen" warning দেয়, চুপ করে থাকে না।
- ছবি **স্থির** — এনিমেশন/transition বোঝা যাবে না। সেগুলোর জন্য web preview।
- `routes:` শুধু অ্যাপের নিজের route ধরতে পারে; গভীর flow (login → profile → edit) দেখাতে হলে `integration_test` লিখতে হবে — এখনো এটা সাপোর্টেড নয়।
- Fork থেকে আসা PR-এ comment করা যায় না (token-এর write নেই) — ছবি শুধু artifact-এ থাকবে।
- প্রথম run-এ Chromium নামে, তাই একটু ধীর; পরে cache হয়।
- Caller workflow-এ `contents: write` আর `pull-requests: write` লাগবে।

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
    uses: Keshab1997/flutter-builder/.github/workflows/web-preview.yml@v1.9.1
    with:
      working-directory: "."
      comment-on-pr: true
    secrets: inherit

  cleanup:
    if: github.event_name == 'delete' && github.event.ref_type == 'branch'
    uses: Keshab1997/flutter-builder/.github/workflows/preview-cleanup.yml@v1.9.1
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
uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.9.1
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
- `scripts/install-agent-pack.sh` — `tool/preflight.py`, `tool/ci_watch.py`, `tool/agent_loop.py` ও managed `AGENTS.md` block বসায় (SDK ছাড়া)
- `agent-pack/` — agent pack-এর canonical ফাইল, যা installer-এর ভিতরে embed করা (tests দুই কপি এক রাখে)
- `scripts/sync-agent-pack.py` — canonical ফাইল আর installer-এর embedded কপি এক রাখে (`--check` দিলে শুধু জানায়); সবসময় `agent-pack/` edit করে এটা চালান
- `scripts/capture-screenshots.sh` — web build-এর ছবি তোলে (Playwright চালায়; `ui-screenshots.yml` আর smoke test দুটোই এটাই চালায়)
- `scripts/embed-screenshots.sh` — ছবি `ui-screenshots` branch-এ push করে PR-এ comment দেয় (কিছু ব্যর্থ হলেও build লাল হয় না)
- `scripts/doctor.sh` — app configuration checker
- `examples/project-workflows/` — app repository-তে ব্যবহারের নমুনা workflow
- `docs/` — signing ও secret setup নির্দেশিকা
- `tests/` — installer, agent pack, preview cleanup ও CI trigger-এর unittest (Flutter SDK ছাড়াই চলে)

License: [MIT](LICENSE).
