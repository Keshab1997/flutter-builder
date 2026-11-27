# AGENTS.md — {{APP_NAME}}

Playbook for AI agents working in this repository. Read it once at the start of
a session: everything here exists to keep the work moving without burning CI.

<!-- flutter-builder:agent-pack:start v1.18.9 -->
## Captain task or independent work?

**Captain A/B/C assignment:** attach this **app repo** in Arena Agent Mode,
not `flutter-builder`. Read the pinned GitHub `BRIEF.md` and `task.json` from
this app repo, then follow [Captain Fast Lane](https://github.com/Keshab1997/agent-bootstrap/blob/main/captain/FASTLANE.md).
If the correct repo is not attached, report `BLOCKED` before editing; don't
use a separate clone or new pairing.

- Use the installed `tool/preflight.py` and the exact gate in `task.json`.
  For Dart, use the assigned SDK pin, lockfile and targeted test. Keep the
  app's existing `flutter-builder` pin; don't install or upgrade the pack
  just to follow a brief.
- Stay on the actual `arena/*` branch. Use Fast Lane to check and publish
  the checkpoint. Do not push `main`, run `tool/agent_loop.py`, dispatch CI
  (including via `tool/see_screen.py`), or open, merge or close a PR.
- After verifying the remote checkpoint, mention `@Keshab1997` in the
  approved tracking issue. If commenting is unavailable, report
  `MENTION PENDING` and the verified checkpoint in Arena.

The direct-to-`main` and one-command push examples below are only for
**independent work explicitly authorized to push to `main`**.

## Rule #1 — CI is one dispatch per batch; preflight is your check

This repository's CI is **manual** — a push never queues it (a push can still
start configured previews or checks). Since 2026-11-20 Keshab approves agents
dispatching it themselves once a batch is ready:
`python3 /home/user/agent-bootstrap/captain/ci_dispatch.py <owner>/<repo> --watch 900`
(button fallback: Actions → *Flutter CI* → Run workflow). Captain **workers**
never dispatch — they checkpoint their `arena/*` branch and report. So:

> **Name things as the project actually has them.** The workflow names in this
> file are the pack's defaults; a project may hand-roll its gates instead of
> copying the examples. Read `.github/workflows/` once per session and quote the
> real names — dispatching a workflow that does not exist wastes the human's
> turn, and assuming one covers your change is how a batch ships unchecked.

- For explicitly authorized independent work, push directly to `main`. A
  Captain worker only checkpoints its `arena/*` branch as above.
- Do **not** wait for CI mid-batch. Keep working; dispatch once, when the
  batch is ready (command above), and say *"batch ready"* in the report.
- `tool/preflight.py` is your only automatic check. Run it before every push —
  it is seconds, not minutes, and catches the mistakes that would otherwise
  surface in the next manual CI run.
- **Dart edits are checked on purpose, not by reflex.** Most changes have a
  matching test file: run the one that covers your edit
  (`flutter test test/<name>_test.dart`), not the whole suite. `flutter analyze`
  and the full `flutter test` are for diffs that touch a shared surface, for
  work that feels risky, or for when the human asks — repeating the full pair
  after every small edit is the fastest way to make the loop feel like a chore.
  Everything else (Markdown, YAML, scripts, docs) still ships on preflight
  alone. See *Checking Dart for real* below.
- **When CI does run, it is the source of truth** — read its result before
  calling a batch done. But it runs when the human says so, not on your push.

```bash
python3 tool/preflight.py     # before every push: dead code / unused params / unused imports
python3 tool/agent_loop.py -m "fix(scope): what changed"   # independent work explicitly authorized for main only
```

### What a check costs

| Check | Cost | When it is the right check |
|---|---|---|
| `python3 tool/preflight.py` | ~1 s | every change, before every push |
| `flutter test test/<file>_test.dart` (via flutter-bootstrap) | 40 s once per session, then seconds | the Dart change that file covers |
| `flutter analyze` or the full `flutter test` | ~20 s / 1–3 min | shared surfaces, risky diffs, or when the human asks |
| `python3 tool/local_screenshots.py --shot <name>` | one `flutter test` run, ~1 s per screen, no CI | every widget change you want to see |
| `python3 tool/see_screen.py` | one CI run | before and after a UI change |
| The human's CI run | the human's attention + a runner | once per finished batch — never per edit |

Pick the cheapest check that actually covers the change. Building the whole app
to answer a question `flutter analyze` can answer is the most common way to turn
a two-minute task into a twenty-minute one.

### Checking Dart for real (flutter-bootstrap)

The sandbox starts without a Flutter SDK, and one installed now is gone next
session. `flutter-bootstrap` installs a working SDK in ~40 seconds, with no
credentials and a sha256-verified download:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Keshab1997/flutter-bootstrap/main/setup.sh) --quiet --json
cd <app-dir> && flutter pub get && flutter analyze && flutter test
```

- When you run a Dart check at all, `flutter analyze` is the floor: it catches
  exactly what preflight cannot, in ~20 seconds. Worth it for a diff that
  reaches a shared surface, or one you cannot clear by reading it.
- A behaviour change with a matching test gets that **one file** run
  (`flutter test test/<name>_test.dart`). The full suite belongs to the human's
  CI run, unless the human asks for it locally.
- CI pins its own Flutter version: a local pass is *indicative*, not final. When
  the two disagree, CI wins — do not "fix" code to satisfy the local version
  without saying so in the commit message.
- Do **not** `flutter build apk` / `flutter build aab` / `flutter build web`
  locally "just to check". That is minutes per run for an artifact only the CI
  workflow needs to produce, and the signing secrets live in CI anyway.
- Re-running that one-liner later in the same session is safe and instant (~0.2 s
  when the SDK is already there).
- For authorized independent work, the companion repo `agent-bootstrap` can
  restore an approved GitHub session if existing access is insufficient. A
  Captain worker uses the attached repo’s native Arena access and does not pair.

## Independent work: the batch loop for an authorized `main` push

Small edits are cheap; CI runs are not. So batch them instead of running CI per
change:

1. **Edit** the smallest diff that does one thing.
2. **`python3 tool/preflight.py`** — 1 second, no SDK. Fix what it reports.
3. **Commit and push to `main`.** `python3 tool/agent_loop.py -m "…"` does
   preflight, the secret guard, the commit and the push in one call. Repeat for
   each small change; every commit goes straight to `main`.
4. **Do not wait for CI mid-batch.** Keep working.
5. **When the batch is ready, say *"batch ready"* and dispatch CI once** —
   `python3 /home/user/agent-bootstrap/captain/ci_dispatch.py <owner>/<repo> --watch 900`,
   or the button: Actions → *Flutter CI* → Run workflow. If a run is already
   in flight, `python3 tool/ci_watch.py` prints the conclusion of every
   workflow plus the interesting lines of the failed ones.

Rules of thumb: a CI run per push wastes the most time; push freely, run CI once
per batch. When a red run does arrive, read the log before editing — guessing at
a red build doubles the rounds.

### The same independent loop as one command

Never use this shortcut on a Captain assignment. `tool/agent_loop.py` performs
preflight, the secret guard, the commit and the push in a single call:

```bash
python3 tool/agent_loop.py -m "fix(profile): guard a null avatar"
python3 tool/agent_loop.py -m "fix(profile): drop the unused import" --amend
python3 tool/agent_loop.py -m "chore: wip" --no-push     # commit without pushing
python3 tool/agent_loop.py -m "…" --watch                # wait, only if a run is in flight
```

It refuses, before touching the repository, when

- a staged file looks like a credential (`.env`, `*.jks`, `*.keystore`, `*.pem`,
  `key.properties`, `google-services.json`, `secrets/**`, …) — a refusal costs
  one edit, a leaked keystore costs a rotation;
- `preflight.py` reports anything — use `--no-preflight` only when the findings
  are deliberate.

It commits on the current branch (normally `main`) and pushes there; no branch,
no pull request. Exit codes: `0` committed/pushed, `1` the push failed,
`2` refused before changing anything. An `--amend` push uses
`--force-with-lease`, never a bare `--force`.

## Seeing a screen — look, do not guess

You cannot run the app, but you can *see* it, and the fast way costs nothing on
GitHub: `tool/local_screenshots.py` renders the screens listed in
`tool/screenshots/shot_registry.dart` to PNGs with `flutter test`, offline.

```bash
python3 tool/local_screenshots.py --list               # the shots this project has
python3 tool/local_screenshots.py --shot home          # one
python3 tool/local_screenshots.py --shot home,settings # several, one run
python3 tool/local_screenshots.py                      # all of them
```

* `shot_registry.dart` is **your** file: it says which screens to photograph and
  how to dress them (the app's theme, its fonts, its native channel answered as
  "nothing granted yet", any local store initialised). Add a shot when you add a
  screen; keep it small and honest. The framework and the runner next to it are
  the pack's and are replaced when the pack updates — a fix belongs upstream.
* The pictures land in `.agent-screens/` (git-ignored). They are **evidence, not
  fixtures**: never read one back as a test input, never commit one, and never
  let CI pay for rendering.
* A shot that renders as a red error page is telling you the truth: a missing
  mock, a missing font, a missing `setUp`. Fix the shot, not the screenshot tool.

For independent work with the human's CI approval, `tool/see_screen.py` can
photograph the pushed web build instead of a local test. It dispatches CI,
waits for the run, downloads the images and prints their paths. Then open
those images to verify the screen:

```bash
python3 tool/see_screen.py --route /settings           # one screen
python3 tool/see_screen.py --route / --route /profile  # several, one build
python3 tool/see_screen.py --route /settings --wait-ms 12000   # slow first frame
```

* **Use it before and after a UI change.** Before: see what the screen looks
  like now. After: see what your change did. A green CI says the code compiles;
  only the picture says the layout is right.
* This starts the UI-screenshots workflow. It is not a Captain worker check.
  For a screen you can render in a test, use `tool/local_screenshots.py`
  without starting CI.
* The routes are the app's own (`/settings`, `/profile`) — the same names the
  app navigates to. A screen behind a login or several taps cannot be reached
  this way; ask the human for a screenshot of that one instead.
* It is the **web** build: layout, colours and text are faithful; fonts and
  platform widgets differ, and camera/bluetooth/notification plugins render as a
  blank screen. The script says so when the pixels are flat — believe it rather
  than "fixing" the capture.
* `--out` defaults to `.agent-screens/` (git-ignored). The images are throwaway
  artifacts: never commit them, and never use one as a test fixture.
* No token? `gh auth login` once, or pass `--token-file`.

## Four things that cost an hour here (do not do them)

1. **Waiting for manual CI after a push.** That run was not queued; see the
   table below.
2. **Running a full build to check a Dart edit.** `flutter build apk|aab|web`
   takes minutes and proves nothing `analyze` + `test` did not already prove.
3. **Asking the human for a CI run before preflight is green and the tests you
   chose to run pass.** A red run spends their attention and a runner, and tells
   you what a local check would have.
4. **Guessing at a red build.** Read the failing step's log first (below). A
   guess that misses doubles the rounds, which is the whole cost this file
   exists to avoid.

## What a push costs here

| Situation | What runs |
|---|---|
| Push to a non-Pages branch with app/code/assets/dependency changes | web preview refreshes; CI stays manual |
| Docs/Markdown/release-note/`.github/`-only push | nothing |
| You ask the human to run CI | CI once, for the whole batch |
| `flutter analyze` / `flutter test` (via flutter-bootstrap) | nothing on GitHub — 40 s to install once per session, then seconds to minutes |
| `local_screenshots.py` | nothing on GitHub — local `flutter test` only |
| `see_screen.py` | the UI-screenshots workflow, once per call |
| a workflow with a `paths:` filter that your change misses | **nothing** — see below |

A project's Dart job is often path-filtered (e.g. `paths: lib/features/x/**`)
so that a small batch does not spend a run. The trap: a change *outside* those
paths starts **no run at all**, and a green board afterwards means "nothing
was checked", not "nothing broke". When the diff is even slightly risky and no
workflow matches it, run the local pair once (`flutter analyze` + the relevant
`flutter test`) — that is the only check that diff will ever get.

If you want a run right now, do **not** retrigger it with an empty commit — use
*Actions → Run workflow* (or the `ci_dispatch.py` one-liner from Rule #1).

## CI map

The pack's standard set, for a project that copied `examples/project-workflows/`.
Confirm the list against `.github/workflows/` before quoting it — a project may
have fewer (or differently named) workflows:

| Workflow | Runs when | What it does |
|---|---|---|
| `ci.yml` → shared `flutter-build.yml` | **manual** (`workflow_dispatch`) | `dart format` check → `flutter analyze --fatal-infos` → `flutter test` + coverage |
| `web-preview.yml` | relevant branch push, manual dispatch, branch delete | builds the web app and replaces that branch's `preview/<branch>/` on GitHub Pages |
| `manual-build.yml` | manual dispatch | APK / AAB artifact |
| `publish-release.yml` | manual dispatch | signed build → tag → GitHub Release (+ Play internal if configured) |
| `release.yml` | `v*` tag push | signed AAB artifact for the tag |

The reusable workflows are pinned by tag; bump the pin in one place
(`.github/workflows/*.yml`) and every project picks the change up.

## Reading CI without wasting a turn

```bash
python3 tool/ci_watch.py                       # HEAD commit, waits, prints failures
python3 tool/ci_watch.py --branch main         # newest runs of a branch
python3 tool/ci_watch.py --once                # no waiting: current state only
python3 tool/ci_watch.py --sha <sha>           # a specific commit
python3 tool/ci_watch.py --token-file secrets/gh_token.txt
```

Token order: `--token-file`, then `$GITHUB_TOKEN` / `$GH_TOKEN`, then `gh auth
token`. Never print a token, and never paste one into a log or a commit.

Raw API equivalents, if you need them:

```bash
GET /repos/{owner}/{repo}/actions/runs?head_sha=<sha>     # run list + conclusions
GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs      # failing job and step
GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs      # plain-text log
```

The log endpoint answers with a **302 to blob storage**; the pre-signed URL
rejects a request that still carries the `Authorization` header
(`InvalidAuthenticationInfo`), so strip it on redirect — `ci_watch.py` does.

## Working rules

- **Small, focused diffs.** One concern per commit; conventional commit
  messages (`fix(profile): …`, `feat(cv): …`, `chore(ci): …`).
- **Use the authorized lane.** Captain workers checkpoint only `arena/*`.
  Independent work can push to `main` when explicitly authorized. Batch small
  changes and let the human run CI once at the end.
- **Secrets never enter git:** `google-services.json`, `android/key.properties`,
  `*.jks` / `*.keystore`, `.pem`, tokens. CI receives them from repository
  secrets. Do not add them to the repo to "make CI pass".
- **Respect existing structure:** edit existing files over adding new ones, and
  read the file you are about to change (comments explain *why* the code is the
  way it is — keep that voice).
- **Match the check to the change** — the cost table near the top of this file
  is the map. Cheap checks run every time; CI runs once, at the end.

## Companion Flutter packages — reuse, don't rebuild

Before writing boilerplate for cross-app features from scratch, check these
shared `Keshab1997` Dart packages (all install cleanly via `pubspec.yaml` `git:`
dependencies):

| Need | Package | Notes |
|---|---|---|
| Remote soft/force updates, maintenance screen, scheduled notices, feature flags | [`app_pulse_kit`](https://github.com/Keshab1997/app_pulse_kit) | Zero-cost `pulse.json` or Firestore (`CallbackPulseSource`), offline cache, built-in EN + বাংলা UI. Keep `pulse.json` aligned with `pubspec.yaml` via `scripts/sync-pulse-config.py` from `flutter-builder`. |
| Smart Play Store rating gate (4–5★ → In-App Review, 1–3★ → in-app feedback + auto diagnostics) | [`smart_review_feedback`](https://github.com/Keshab1997/smart_review_feedback) | Pluggable sinks (Webhook, Telegram, Email, Firestore `CallbackFeedbackSink`), built-in EN + বাংলা UI. |
| Firestore-backed admin API key pool (failover, cooldowns, health checks, admin UI) | [`admin_api_key_manager`](https://github.com/Keshab1997/admin_api_key_manager) | Shared Gemini / OpenRouter key rotation & management. |
| Shared OCR + AI extraction pipeline | [`smart_ocr_ai_bridge`](https://github.com/Keshab1997/smart_ocr_ai_bridge) | Reusable OCR-to-AI bridge for scanner apps. |
| 1-click new Flutter app template (pre-wired with `flutter-builder`, Agent Pack, `app_pulse_kit`, signing & Settings) | [`flutter-app-starter`](https://github.com/Keshab1997/flutter-app-starter) | Click **Use this template** → **Actions → Setup New App (1-Click)** to spin up a new app in ~30s. |

## Ask the human before

- running CI, when a batch is ready to be checked (they own the run button);
- **tagging a release**, or touching workflows / secrets / repository settings;
- force-pushing over history you do not own, or deleting branches, tags, or
  repository content;
- anything that publishes publicly, spends money, or is irreversible.

## মানুষের জন্য — এই ফাইলটা কী

- **যে যাচাইটা আসলে দরকার, শুধু সেটাই:** ছোট পরিবর্তনে শুধু `preflight.py`
  (~১ সেকেন্ড); Dart বদলালে সংশ্লিষ্ট একটা test ফাইল
  (`flutter test test/<name>_test.dart`) — পুরো `analyze` + `test` শুধু shared
  কিছু বদলালে বা আপনি বললে। প্রতিটা ছোট edit-এর পিছনে পুরো suite চালানো লাগে না।
- **Captain brief হলে** app repo Arena-তে attach করে শুধু `arena/*` branch-এ
  checkpoint দিন। আলাদা অনুমোদিত কাজেই সরাসরি `main`-এ push।
- **CI চালানোর বোতাম আপনারই** — একটা batch শেষ হলে একবার চালালেই যথেষ্ট।
- **UI বদলালে ছবি দেখে যাচাই** — আগে `python3 tool/local_screenshots.py --shot <নাম>` (ফ্রি, সেকেন্ডে), দরকার হলে `python3 tool/see_screen.py`।
- **agent আগে অনুমতি নেবে** — tag/release, secrets, store metadata, বা যা
  ফিরিয়ে আনা যায় না এমন কিছুর আগে।
- এই ব্লকটা `install-agent-pack.sh` চালালে নিজে থেকেই update হয়; নিচের
  আপনার নিজের notes কখনো মোছা হয় না।

<!-- flutter-builder:agent-pack:end -->

## Project notes — edit freely

Everything above the end marker is maintained by
`scripts/install-agent-pack.sh` (re-run the one-liner to update it; your text
down here is never touched).

- **App:** {{APP_NAME}} — one line about what it does.
- **App directory:** `.` (change this line if the Flutter app lives in a
  subdirectory).
- **Extra project rules:** _(fill in: invariants, store metadata that must stay
  in sync, screenshots that must be regenerated, …)_
- **Extra verification:** _(fill in: anything CI cannot see — copy changes,
  Play Console steps, manual checks …)_
