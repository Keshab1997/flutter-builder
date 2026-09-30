# Google Play Internal Testing-এ AAB পাঠানোর গাইড

এই setup-এ app repository-র **Publish Signed Android Release** workflow একবার signed AAB build করে একই artifact (১) GitHub Release-এ যোগ করবে এবং (২) Google Play Console-এর **Internal testing** track-এ upload করবে। আলাদা internal-upload workflow চালিয়ে দ্বিতীয়বার AAB build হবে না। এটি production release নয়। Secret-গুলো **আপনার Flutter app repository-তে** রাখতে হবে—`flutter-builder` repository-তে নয়। এই guide বা workflow file-এ কখনো secret value লিখবেন না।

## ১. Play Console-এ app ও testers প্রস্তুত করুন

1. Google Play Console-এ app তৈরি করা না থাকলে তৈরি করুন। Flutter-এর Android `applicationId`-ই app-এর package name; যেমন `com.example.myapp`। Play Console-এ package name একই হতে হবে।
2. Play Console-এ **Testing → Internal testing** খুলে tester email/list যোগ করুন। পরে এই track-এর opt-in link tester-দের দেবেন।
3. প্রথমে Play Console-এর **Setup → API access** (UI নাম/অবস্থান বদলাতে পারে) থেকে একটি Google Cloud project link করুন।

## ২. Play upload service account বানান

1. Linked Google Cloud project-এ **Google Play Android Developer API** enable করুন।
2. Google Cloud Console → **IAM & Admin → Service Accounts** থেকে service account তৈরি করুন। এটিকে আলাদা, automation-only account রাখুন।
3. Play Console-এর **Setup → API access**-এ service account-টি link/invite করুন। আপনার app-এর জন্য release-এ প্রয়োজনীয় permission দিন—সাধারণত app information দেখা ও releases manage করার permission। কেবল দরকারি app-এ access দিন; অপ্রয়োজনীয় account-wide permission দেবেন না।
4. Service account-এর **Keys → Add key → Create new key → JSON** থেকে JSON key download করুন। JSON key password/token-এর মতো secret: chat, source code, issue বা public repo-তে দেবেন না; local machine-এ নিরাপদে রাখুন।

## ৩. App repository-তে GitHub Secrets যোগ করুন

Flutter **app repository** খুলে **Settings → Secrets and variables → Actions → New repository secret**-এ যান। নিচের নামগুলো হুবহু ব্যবহার করুন:

| Secret name | Value |
|---|---|
| `PLAY_SERVICE_ACCOUNT_JSON` | ডাউনলোড করা service account JSON ফাইলের সম্পূর্ণ content |
| `ANDROID_KEYSTORE_BASE64` | signing/upload keystore-এর Base64 content |
| `KEYSTORE_PASSWORD` | keystore password |
| `KEY_ALIAS` | upload key-এর alias |
| `KEY_PASSWORD` | upload key password |

Signing keystore না বানিয়ে থাকলে [`ANDROID_SIGNING.md`](ANDROID_SIGNING.md)-এর ধাপগুলো আগে অনুসরণ করুন। একই app-এর সব update-এ একই upload key ব্যবহার করতে হবে। `key.properties`, `.jks`, `.keystore`, JSON key বা Base64 keystore commit করবেন না।

যদি app build-এর সময় `google-services.json` secret থেকে inject করে, `GOOGLE_SERVICES_JSON_BASE64`-ও app repository-তে secret হিসেবে রাখুন। এই উদাহরণ workflow সেটি optional secret হিসেবে reusable workflow-তে forward করে। Firebase ব্যবহার না করলে secret যোগ করার দরকার নেই।

> **কোথায় secret দেবেন?** যে app-এর AAB Play Store-এ যাবে, সেই app repository-তে। `Keshab1997/flutter-builder`-এর Settings-এ নয়—সেখানে রাখলে এই app workflow-তে credential পৌঁছাবে না।

## ৪. Workflow app repository-তে যোগ করুন

Flutter app repository-তে [`examples/project-workflows/publish-release.yml`](../examples/project-workflows/publish-release.yml) কপি করুন:

```text
.github/workflows/publish-release.yml
```

আগে থেকে `publish-release.yml` থাকলে নতুন করে duplicate workflow যোগ করবেন না; নিচের dispatch inputs ও `with:` settings তাতে যোগ করুন। Sample workflow-তে Play upload opt-in হিসেবে আছে—Actions-এ `upload_to_play_internal` true করলে একই release run-এ Play upload হবে।

Release notes-এর sample locale files-ও app repo-তে কপি করুন:

```text
distribution/whatsnew/whatsnew-en-US
distribution/whatsnew/whatsnew-bn-BD
```

প্রতিটি run-এর আগে এই ফাইলগুলোতে সেই release-এর আসল পরিবর্তন সংক্ষেপে লিখে commit/push করুন। Locale filename হবে `whatsnew-<BCP-47 locale>`—যেমন `whatsnew-en-US`। Notes directory workflow-তে `play-whats-new-directory` দিয়ে সেট করা আছে। Sample caller `@v1.8.7` pin করে — `play-whats-new-directory` input এই tag থেকেই আছে। পুরোনো tag (যেমন `@v1.8.6`)-এ এই input নেই, তাই caller ও wrapper সবসময় একই tag-এ pin করুন।

## ৫. একবারে GitHub Release + Play Internal testing

Sample `publish-release.yml`-তে Play upload option আগে থেকেই আছে। Actions → **Publish Signed Android Release → Run workflow** খুলুন, `upload_to_play_internal` true করুন, এবং `package_name`-এ Gradle-এর `applicationId`/Play Console-এর exact package name দিন—যেমন `com.yourcompany.myapp`। Release notes files commit করা আছে কি না নিশ্চিত করে workflow চালান।

Workflow একবার signed AAB build করবে। একই AAB GitHub Release-এ যোগ হবে এবং Google Play-এর `internal` track-এ upload হবে—**AAB দ্বিতীয়বার build হবে না**। `upload_to_play_internal` false রাখলে GitHub Release-ই হবে, Play upload হবে না।

`play-status: completed` ব্যবহার করায় upload শেষে release internal testers-এর জন্য প্রকাশিত হবে; production-এ যাবে না। Play Console → **Testing → Internal testing**-এ release দেখে tester-দের opt-in link দিন।

## পরের upload-এর আগে

- `pubspec.yaml`-এর Android build number/version code প্রতিবার বাড়ান; Play একই version code আবার গ্রহণ করবে না। উদাহরণ: `version: 1.2.4+5`।
- Package name Play Console-এর app-এর সঙ্গে হুবহু মিলতে হবে।
- Signed AAB-তে আগের upload key ব্যবহার করুন। Google Play App Signing সেটআপের সময় upload key এবং app signing key এক জিনিস নাও হতে পারে।
- Build বা upload fail হলে Actions log-এর error দেখুন; secret value log/chat-এ paste করবেন না। Common কারণ: ভুল package name, missing secret, invalid JSON/key, Play API disabled, service account permission না থাকা, version code duplicate।
