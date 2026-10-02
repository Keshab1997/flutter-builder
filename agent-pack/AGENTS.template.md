# AGENTS.md — {{APP_NAME}}

Playbook for AI agents working in this repository. Read it once at the start of
a session: everything here exists to keep one change loop short.

<!-- flutter-builder:agent-pack:start v1.9.1 -->
## Rule #1 — CI verifies, you never push a guess

This sandbox usually has **no Flutter SDK**, and even when it does, the local
result would not match CI (SDK pin, Android SDK, Firebase secrets). So:

- Do **not** run `flutter test`, `flutter analyze`, `flutter build`,
  `dart analyze` or `gradlew` locally to "check quickly".
- Use the two zero-dependency tools in `tool/` instead — they are seconds, not
  minutes, and they catch the mistakes that actually turn pushes red.
- **CI is the single source of truth.** Read its result before calling a change
  done; a local impression is never verification.

```bash
python3 tool/preflight.py     # before pushing: dead code / unused params / unused imports
python3 tool/ci_watch.py      # after pushing: waits for CI, prints the failing lines
```

## The fast loop — one change, one push, one CI round

1. **Edit** the smallest diff that does one thing.
2. **`python3 tool/preflight.py`** — 1 second, no SDK. Fix what it reports.
3. **Commit.** While the branch is still yours, `git commit --amend` instead of
   piling "fix ci" commits on top.
4. **Push once.** Never push WIP "to see what happens". If you have several
   things to try, open the PR as a **draft** — drafts do not run CI, so iterate
   freely; mark *Ready for review* when you want the run.
5. **`python3 tool/ci_watch.py`** — it polls for you (no turn-by-turn waiting)
   and prints the conclusion of every workflow plus the interesting lines of
   the failed ones.
6. **Red?** Fix → `git commit --amend` → `git push --force-with-lease` →
   watch again. One more round, not five.

Rules of thumb: ten 30-second pushes waste more time than one 3-minute CI run.
Read the CI log before editing; guessing at a red build doubles the rounds.

## What a push costs here (and why it is already cheap)

| Situation | What runs |
|---|---|
| Push to a feature branch **with an open PR** | the PR event only — the push trigger is main-only, so no duplicate |
| Push to `main` | CI (+ Web Preview) once |
| **Draft** PR | nothing, until you press *Ready for review* |
| Docs-only change (`**.md`, `docs/**`, `distribution/**`) | nothing (excluded by `paths-ignore`) |
| Merge | CI on `main` + Web Preview deploy |

If a run is cancelled or skipped, do **not** retrigger it with an empty commit —
use *Actions → Run workflow* or the re-run API call.

## CI map

| Workflow | Runs when | What it does |
|---|---|---|
| `ci.yml` → shared `flutter-build.yml` | push to main, PRs | `dart format` check → `flutter analyze --fatal-infos` → `flutter test` + coverage |
| `web-preview.yml` | push to main, PRs | builds the web app, deploys `preview/<branch>/` to GitHub Pages (a branch delete removes its preview) |
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
- **Branch + PR** for anything non-trivial; keep the branch name descriptive.
  Docs-only fixes may go straight to `main` when the project allows it.
- **Merge only when green.** Delete the branch after merging — the preview
  cleanup runs automatically.
- **Secrets never enter git:** `google-services.json`, `android/key.properties`,
  `*.jks` / `*.keystore`, `.pem`, tokens. CI receives them from repository
  secrets. Do not add them to the repo to "make CI pass".
- **Respect existing structure:** edit existing files over adding new ones, and
  read the file you are about to change (comments explain *why* the code is the
  way it is — keep that voice).

## Ask the human before

- merging to `main` (when the project wants review), **tagging a release**, or
  touching workflows / secrets / repository settings;
- force-pushing a branch you do not own, rewriting published history, or
  deleting branches, tags, or repository content;
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
