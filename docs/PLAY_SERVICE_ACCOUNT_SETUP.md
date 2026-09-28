# Google Play upload service account — ধাপে ধাপে

এই নির্দেশিকায় শুধু Google Play-এ upload করার **service account** তৈরি ও অনুমতি দেওয়ার ধাপ আছে। শেষে service account-এর JSON key-টি `PLAY_SERVICE_ACCOUNT_JSON` নামে **Flutter app repository-র GitHub Actions secret** হবে—`flutter-builder` repository-তে নয়।

## আগে জানুন: কোন Google Cloud project নেব?

আপনার নিয়ন্ত্রণে থাকা **যেকোনো Google Cloud project** ব্যবহার করা যায়—শর্ত হলো সেই project-এ Google Play Developer API enable করতে হবে এবং ওই project-এর service account-কে Play Console-এ উপযুক্ত permission দিতে হবে। এই কাজের জন্য আলাদা, পরিষ্কার নামের project (যেমন `my-app-play-upload`) বানানো ভালো; এতে অন্য cloud কাজের service account থেকে Play upload আলাদা থাকে।

Google-এর বর্তমান Getting Started নির্দেশনা অনুযায়ী Developer account-কে Cloud project-এর সঙ্গে link করা বাধ্যতামূলক নয়। মূল বিষয় হলো API enable করা এবং service account-কে Play Console-এ user হিসেবে যোগ করা। [Google-এর setup guide](https://developers.google.com/android-publisher/getting_started)

### অনেকগুলো app/repository হলে কী হবে?

- **Google Cloud-এ:** একই service account ও JSON key একাধিক app-এর জন্য ব্যবহার করা যায়। Play Console-এ ওই service account-কে প্রতিটি app-এ আলাদা করে permission দিতে হবে। একটি key ফাঁস হলে যত app-এ permission দেওয়া আছে সব ঝুঁকিতে পড়তে পারে; বেশি নিরাপত্তার জন্য app বা app-group অনুযায়ী আলাদা service account/key রাখুন।
- **GitHub-এ:** workflow যে repository-তে চলে, সেই repository-কে secret পেতে হবে। Personal account-এর আলাদা আলাদা app repository হলে `PLAY_SERVICE_ACCOUNT_JSON` প্রতিটিতে repository secret হিসেবে যোগ করুন। GitHub Organization-এর repositories হলে একই secret organization-level-এ রাখা যায় এবং access শুধু প্রয়োজনীয় app repositories-তে সীমিত করা যায়।
- Secret-টি `flutter-builder` public repository-তে বা সবার জন্য উন্মুক্ত কোনো shared repository-তে রাখবেন না।

## ধাপ ১ — Cloud project বাছুন বা তৈরি করুন

1. [Google Cloud Console](https://console.cloud.google.com/) খুলুন এবং Play Console-এর account পরিচালনার অনুমতি আছে এমন Google account দিয়ে sign in করুন।
2. উপরের project selector থেকে বিদ্যমান project বেছে নিন, অথবা **New project** করে dedicated project তৈরি করুন। Project-এর নাম ইচ্ছামতো হতে পারে; যেমন `my-app-play-upload`।
3. নিশ্চিত করুন, project-টি আপনার account-এ আছে এবং আপনি service account তৈরি ও API enable করার অনুমতি রাখেন।

## ধাপ ২ — Google Play Developer API enable করুন

1. Cloud Console-এ সদ্য বেছে নেওয়া project-টি active আছে কি না project selector-এ দেখুন। ভুল project-এ API enable করবেন না।
2. [Google Play Android Developer API](https://console.cloud.google.com/apis/library/androidpublisher.googleapis.com) খুলুন।
3. **Enable** চাপুন। যদি আগে থেকেই enabled থাকে, পরের ধাপে যান।

## ধাপ ৩ — Service account তৈরি করুন

1. [Google Cloud Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts) খুলুন—একই project নির্বাচিত থাকতে হবে।
2. **Create service account** চাপুন। নাম দিন, যেমন `github-play-uploader`; description-এ লিখতে পারেন `Uploads app releases to Play testing track from GitHub Actions`।
3. Service account তৈরি সম্পন্ন করুন। এই কাজের জন্য project-এ **Owner** বা broad IAM role দেওয়ার দরকার নেই; Play Console permission-ই upload authorization দেবে।
4. তৈরি হওয়া service account-এর email কপি করুন; দেখতে এমন হবে:

   ```text
   github-play-uploader@your-cloud-project.iam.gserviceaccount.com
   ```

## ধাপ ৪ — JSON key তৈরি ও নিরাপদে রাখুন

1. Service account-এর row-তে click করে **Keys** tab খুলুন।
2. **Add key → Create new key → JSON → Create** নির্বাচন করুন। Browser একটি `.json` key file download করবে।
3. JSON ফাইলটি password-এর মতো গোপন রাখুন। এটি chat-এ পাঠাবেন না, repository-তে commit করবেন না, public storage-এ রাখবেন না। JSON-টি **Base64 করার দরকার নেই**।
4. পরে GitHub secret তৈরি করার সময় JSON ফাইলের সম্পূর্ণ content secret value হিসেবে দেবেন। Secret-এর নাম হবে `PLAY_SERVICE_ACCOUNT_JSON`।

> Key তৈরি করার option না থাকলে আপনার Google Cloud organization-এর policy service-account key বন্ধ করে রাখতে পারে। Organization admin-এর সঙ্গে কথা বলুন; policy এড়িয়ে অন্য project বা ব্যক্তিগত credential ব্যবহার করবেন না।

## ধাপ ৫ — Play Console-এ service account-কে অনুমতি দিন

1. [Google Play Console](https://play.google.com/console/)-এ sign in করুন।
2. **Users and permissions** খুলে **Invite new users** নির্বাচন করুন।
3. Email field-এ ধাপ ৩-এ কপি করা `...iam.gserviceaccount.com` email দিন।
4. Account-wide permission না দিয়ে, সম্ভব হলে **App permissions**-এ শুধু যে app upload করবেন সেটি নির্বাচন করুন।
5. Internal testing-এ release upload করার জন্য **Release apps to testing tracks** permission দিন। এই permission testing track-এ release তৈরি/সম্পাদনা/roll out করতে দেয়; production publish করার অনুমতি দেয় না। Tester list-ও automation থেকে manage করতে চাইলে প্রয়োজনমতো **Manage testing tracks and edit tester lists** দিন—শুধু AAB upload-এর জন্য এটি দরকার নাও হতে পারে।
6. Invite/save করুন। Permission-এ পরিবর্তন কাজ করতে সামান্য সময় লাগতে পারে। Permission-এর নাম বা layout Play Console update অনুযায়ী সামান্য বদলাতে পারে। [Play Console permission definitions](https://support.google.com/googleplay/android-developer/answer/9844686?hl=en)

## শেষ ধাপ — JSON-কে GitHub Secret করুন

Flutter **app repository**-তে যান:

**Settings → Secrets and variables → Actions → New repository secret**

- **Name:** `PLAY_SERVICE_ACCOUNT_JSON`
- **Secret:** download করা `.json` ফাইলের সম্পূর্ণ text content

তারপর **Add secret** চাপুন। এটি `flutter-builder`-এর repository settings-এ দেবেন না। GitHub-এ repository secret যোগ করার ধাপ: [GitHub Docs](https://docs.github.com/actions/security-guides/using-secrets-in-github-actions#creating-secrets-for-a-repository).

## Permission যাচাইয়ের সহজ checklist

- [ ] সঠিক Google Cloud project নির্বাচিত ছিল।
- [ ] Google Play Developer API ওই project-এ enabled।
- [ ] Service account email Play Console-এর **Users and permissions**-এ যোগ করা।
- [ ] Service account-কে সঠিক app-এর **Release apps to testing tracks** permission দেওয়া।
- [ ] Raw JSON key app repository-তে `PLAY_SERVICE_ACCOUNT_JSON` নামে secret হয়েছে।
- [ ] JSON key কোনো code, issue, chat বা public repository-তে নেই।
