# AGENTS.md — {{APP_NAME}}

Playbook for AI agents working in this repository. Read it once at the start of
a session: everything here exists to keep the work moving without burning CI.

<!-- flutter-builder:agent-pack:start v1.12.1 -->
## Rule #1 — CI is manual; preflight is your check

This repository runs CI **only when the human dispatches it** (Actions → *Flutter
CI* → Run workflow). Nothing runs on a push. So:

- Work lands on `main` **directly** — no feature branch, no pull request.
- Do **not** wait for a run after pushing. Nothing started; waiting only wastes
  time.
- `tool/preflight.py` is your only automatic check. Run it before every push —
  it is seconds, not minutes, and catches the mistakes that would otherwise
  surface in the next manual CI run.
- Do **not** run `flutter test`, `flutter analyze`, `flutter build`,
  `dart analyze` or `gradlew` locally to "check quickly". The sandbox usually has
  no Flutter SDK, and a local pass would not match CI anyway.
- **When CI does run, it is the source of truth** — read its result before
  calling a batch done. But it runs when the human says so, not on your push.

```bash
python3 tool/preflight.py     # before every push: dead code / unused params / unused imports
python3 tool/agent_loop.py -m "fix(scope): what changed"   # preflight + commit + push, one call
```

## The batch loop — many small changes, one push, one CI run

Small edits are cheap; CI runs are not. So batch them instead of running CI per
change:

1. **Edit** the smallest diff that does one thing.
2. **`python3 tool/preflight.py`** — 1 second, no SDK. Fix what it reports.
3. **Commit and push to `main`.** `python3 tool/agent_loop.py -m "…"` does
   preflight, the secret guard, the commit and the push in one call. Repeat for
   each small change; every commit goes straight to `main`.
4. **Do not wait for CI.** Nothing started. Keep working.
5. **When the batch is ready, tell the human** to run CI once (Actions → *Flutter
   CI* → Run workflow). If a run is already in flight, `python3 tool/ci_watch.py`
   prints the conclusion of every workflow plus the interesting lines of the
   failed ones.

Rules of thumb: a CI run per push wastes the most time; push freely, run CI once
per batch. When a red run does arrive, read the log before editing — guessing at
a red build doubles the rounds.

### The same loop as one command

`tool/agent_loop.py` performs preflight, the secret guard, the commit and the
push in a single call:

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

You cannot run the app, but you can *see* it. `tool/see_screen.py` asks CI to
build the app for web and photograph the routes you name, waits for the run,
downloads the images and prints their paths. Then open them — with your image
tool, not your imagination:

```bash
python3 tool/see_screen.py --route /settings           # one screen
python3 tool/see_screen.py --route / --route /profile  # several, one build
python3 tool/see_screen.py --route /settings --wait-ms 12000   # slow first frame
```

* **Use it before and after a UI change.** Before: see what the screen looks
  like now. After: see what your change did. A green CI says the code compiles;
  only the picture says the layout is right.
* This is the one thing that does start a run — it dispatches the UI-screenshots
  workflow itself, so use it deliberately, not on every edit.
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

## What a push costs here

| Situation | What runs |
|---|---|
| Push to `main` (any change) | nothing — CI is manual |
| Docs-only change (`**.md`, `docs/**`, `distribution/**`) | nothing |
| You ask the human to run CI | CI once, for the whole batch |
| `see_screen.py` | the UI-screenshots workflow, once per call |

If you want a run right now, do **not** retrigger it with an empty commit — use
*Actions → Run workflow* (or ask the human to).

## CI map

| Workflow | Runs when | What it does |
|---|---|---|
| `ci.yml` → shared `flutter-build.yml` | **manual** (`workflow_dispatch`) | `dart format` check → `flutter analyze --fatal-infos` → `flutter test` + coverage |
| `web-preview.yml` | manual dispatch, branch delete | builds the web app, deploys `preview/<branch>/` to GitHub Pages |
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
- **Push straight to `main`.** No feature branch, no pull request. Batch small
  changes and let the human run CI once at the end.
- **Secrets never enter git:** `google-services.json`, `android/key.properties`,
  `*.jks` / `*.keystore`, `.pem`, tokens. CI receives them from repository
  secrets. Do not add them to the repo to "make CI pass".
- **Respect existing structure:** edit existing files over adding new ones, and
  read the file you are about to change (comments explain *why* the code is the
  way it is — keep that voice).

## Ask the human before

- running CI, when a batch is ready to be checked (they own the run button);
- **tagging a release**, or touching workflows / secrets / repository settings;
- force-pushing over history you do not own, or deleting branches, tags, or
  repository content;
- anything that publishes publicly, spends money, or is irreversible.

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
