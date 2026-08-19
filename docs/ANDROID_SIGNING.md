# Android signing সেটআপ — বাংলা নির্দেশিকা

Play Store-এর AAB ফাইলকে একটি **Upload Key** দিয়ে sign করতে হয়। Key নিজে তৈরি করবেন এবং নিরাপদে রাখবেন। কোনো password, token বা keystore chat, source code কিংবা public repository-তে দেবেন না।

## ১. Upload keystore তৈরি

JDK/Java install থাকা computer-এর Terminal-এ চালান:

```bash
keytool -genkeypair -v -keystore upload-keystore.jks -storetype JKS -keyalg RSA -keysize 2048 -validity 10000 -alias upload
```

Windows Command Prompt-এ command-টি এক লাইনেই চালানো যাবে। এটি password, নাম, organization, city, state ও country code চাইবে। Country code হিসেবে `IN` দেওয়া যায়।

ফলাফল:

```text
upload-keystore.jks
```

ফাইল ও password দুটির অন্তত দুইটি নিরাপদ backup রাখুন।

## ২. Keystore-কে Base64 করা

### Windows PowerShell

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("upload-keystore.jks")) | Set-Content keystore-base64.txt
```

### Linux

```bash
base64 -w 0 upload-keystore.jks > keystore-base64.txt
```

### macOS

```bash
base64 upload-keystore.jks > keystore-base64.txt
```

## ৩. Project repository-তে GitHub Secrets যোগ করা

App-এর repository খুলে যান:

```text
Settings → Secrets and variables → Actions → New repository secret
```

এই চারটি secret বানান:

| Secret-এর নাম | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | `keystore-base64.txt`-এর সম্পূর্ণ লেখা |
| `KEYSTORE_PASSWORD` | Keystore password |
| `KEY_ALIAS` | `upload` (অথবা তৈরির সময় ব্যবহৃত alias) |
| `KEY_PASSWORD` | Key password |

`keystore-base64.txt` repository-তে commit করবেন না। Secret যোগ করার পর local text file-টিও নিরাপদে delete বা encrypted backup-এ রাখুন।

## ৪. Flutter project-এ signing configuration

Central workflow build-এর সময় স্বয়ংক্রিয়ভাবে নিচের দুটি temporary file তৈরি করবে:

```text
android/key.properties
android/app/upload-keystore.jks
```

কিন্তু Flutter app-এর Gradle file-কে `key.properties` পড়তে হবে। নতুন Flutter project-এ file সাধারণত `android/app/build.gradle.kts`; পুরোনো project-এ `android/app/build.gradle` হতে পারে।

### Kotlin DSL: `android/app/build.gradle.kts`

File-এর শুরুতে যোগ করুন:

```kotlin
import java.util.Properties
import java.io.FileInputStream

val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}
```

`android {}` block-এর মধ্যে যোগ/সমন্বয় করুন:

```kotlin
signingConfigs {
    create("release") {
        keyAlias = keystoreProperties["keyAlias"] as String?
        keyPassword = keystoreProperties["keyPassword"] as String?
        storeFile = keystoreProperties["storeFile"]?.let { file(it) }
        storePassword = keystoreProperties["storePassword"] as String?
    }
}

buildTypes {
    release {
        signingConfig = signingConfigs.getByName("release")
    }
}
```

যদি `release` block আগে থেকেই থাকে, দ্বিতীয়টি বানাবেন না; existing block-এর signing line পরিবর্তন করুন।

### Groovy DSL: `android/app/build.gradle`

File-এর শুরুতে যোগ করুন:

```groovy
def keystoreProperties = new Properties()
def keystorePropertiesFile = rootProject.file('key.properties')
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(new FileInputStream(keystorePropertiesFile))
}
```

`android {}` block-এর মধ্যে যোগ/সমন্বয় করুন:

```groovy
signingConfigs {
    release {
        keyAlias keystoreProperties['keyAlias']
        keyPassword keystoreProperties['keyPassword']
        storeFile keystoreProperties['storeFile'] ? file(keystoreProperties['storeFile']) : null
        storePassword keystoreProperties['storePassword']
    }
}

buildTypes {
    release {
        signingConfig signingConfigs.release
    }
}
```

## ৫. `.gitignore` পরীক্ষা

Flutter project-এর `.gitignore`-এ নিশ্চিত করুন:

```gitignore
android/key.properties
android/app/upload-keystore.jks
*.jks
*.keystore
```

## ৬. AAB build অথবা GitHub Release publish

শুধু AAB artifact বানাতে app repository-এর **Actions → Manual Android Build → Run workflow → aab** নির্বাচন করুন।

Signed APK, signed AAB, automatic English release notes এবং GitHub Release একসঙ্গে publish করতে **Actions → Publish Android Release → Run workflow** নির্বাচন করুন। Publish workflow-এ `permissions: contents: write` থাকতে হবে।

Secrets বা Gradle signing ভুল হলে workflow AAB/Release publish করার আগেই fail করবে।

## জরুরি নিরাপত্তা

- একই app-এর পরবর্তী release-এ একই upload key ব্যবহার করুন।
- GitHub Personal Access Token কখনো chat-এ বা code-এ paste করবেন না।
- Play App Signing চালু রাখলে upload key হারালে Google Play Console থেকে reset request করা যায়।
- প্রতিটি গুরুত্বপূর্ণ app-এর জন্য আলাদা upload keystore রাখা উত্তম।
