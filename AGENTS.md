# AGENTS.md — working on `flutter-builder`

**This is the playbook for agents editing *this* repository.**

If you are an agent inside a *Flutter app project* and you are looking for the
playbook that `install-agent-pack.sh` put there, you want the installed
`AGENTS.md` in that project (canonical source: `agent-pack/AGENTS.template.md`).
This file is not it.

---

## The contract in one line

This repo ships reusable GitHub Actions workflows and an agent pack. Projects
consume them **by tag** (`@v1.13.1`), so **`main` is staging**: push to it
freely, tag it deliberately.

```bash
# the whole loop. this is not a simplification.
python3 -m pytest tests/ -q          # ~5 s, 177 tests — the real gate
git commit -am "fix(scope): what changed" && git push origin main
```

No feature branch. No pull request. No waiting. **Nothing in this repository
triggers on `push`, `pull_request` or tags**: five workflows are `workflow_call`
(they run only when a consumer project calls them), one is a weekly `schedule`,
and the rest are `workflow_dispatch` (manual). So a push to `main` starts
nothing — waiting for a run that was never queued is the most expensive mistake
available here.

---

## The 60-second rule

Any change in this repository can be verified in **under a minute**, with no
SDK installed, on any machine. If you find yourself waiting longer than that,
you have taken a wrong turn — stop and re-read this table.

| You changed | Minimum sufficient check | Time |
|---|---|---|
| A `**.md` file | nothing (optionally `bash -n` if it contains a snippet) | 0 s |
| Spelling, comment, log text | nothing | 0 s |
| A shell script | `bash -n <file>` then `shellcheck <file>` | <1 s |
| A Python tool (`agent-pack/*.py`, `scripts/*.py`) | `python3 -m pytest tests/ -q` | ~5 s |
| Anything under `agent-pack/` | see *The sync rule* below | ~6 s |
| Anything at all, when unsure | `python3 -m pytest tests/ -q` | ~5 s |

The repository's own suite is **fast on purpose**. Run the whole thing; do not
run a subset to save seconds.

---

## Five things that cost an hour here (do not do them)

1. **Do not install Flutter, Dart, or the Android SDK.** This repository
   contains no Flutter/Dart application code. `flutter analyze`, `flutter test`
   and `flutter build` have nothing to act on — installing a 2.5 GB SDK to
   "verify" a YAML or Bash change is pure loss. The CI runners install the SDKs
   for you when a workflow actually needs them.
2. **Do not wait for CI after a push.** Nothing is triggered (see above). If you
   want a run, ask the human to dispatch it — that is their button, not yours.
3. **Do not verify by re-running the installer end to end.** `tests/` already
   covers `install.sh`, `install-agent-pack.sh`, `bump-ref.sh` and the pack. An
   end-to-end run adds minutes and finds nothing the suite missed.
4. **Do not clone a consumer app to test a workflow change.** The workflows
   here are libraries; their correctness is exercised by `flutter-smoke-test.yml`
   on a runner, not by a local app.
5. **Do not push to more than one place for safety.** `main` is the only branch.
   Nothing is waiting on it. Waiting for "a second opinion" from a branch or a
   draft PR just moves the same diff through two more steps.

---

## The sync rule — the one real trap in this repo

`agent-pack/` is **canonical**. `scripts/install-agent-pack.sh` carries a copy of
every file inside quoted heredocs (it must stay self-contained for
`curl … | bash`), and `tests/test_agent_pack.py` compares the two **byte for
byte**.

```bash
# right: edit the canonical files, then re-embed
$EDITOR agent-pack/AGENTS.template.md
python3 scripts/sync-agent-pack.py            # rewrite the embedded payload
python3 -m pytest tests/test_agent_pack.py -q # ✓ now in sync

# wrong: hand-editing the heredoc copy inside scripts/install-agent-pack.sh
python3 scripts/sync-agent-pack.py --check    # exit 1 when out of sync (CI-safe)
```

- `PACK_VERSION` (top of `install-agent-pack.sh`) is the marker consumers see
  in their managed block — but it is **not** a "content changed" counter, and
  bumping it here alone breaks the build: three pin-drift tests
  (`test_preview_hub.py`, `test_build_caching.py`, `test_ui_screenshots.py`)
  require every `ref: vX.Y.Z` checkout inside the workflows and examples to be
  **>= PACK_VERSION**, because a caller that checks out a tag is asking for the
  scripts that tag contains. So the order is: land content on `main` → the
  human decides the next version → bump `PACK_VERSION`, the workflow pins, the
  example pins and the tag together. Editing the template does not bump a
  version; releasing does.
- `flutter-builder-manual-ci.patch` is a review diff of the "make CI manual"
  change and nothing in the repository reads it. It is generated with
  `diff -ruN a/ b/`; regenerate rather than hand-edit, and keep it out of the
  way of real work.

---

## Tags are the public API

| | |
|---|---|
| Consumers pin | `uses: Keshab1997/flutter-builder/.github/workflows/flutter-build.yml@v1.13.1` and `install.sh --ref v1.13.1` |
| `main` | staging — your landing zone, safe to push |
| A tag | the release — **every project's CI changes at once** |

So: landing a change on `main` is low-risk and expected. **Reaching users is
the deliberate act.** Concretely:

- Docs, comments, refactors, new optional inputs → push to `main`, done.
- A **breaking** change (removing/renaming a workflow input, a required secret,
  a permission) → still lands on `main`, but say so loudly: `feat!:`/`fix!:` in
  the commit, a paragraph in the body, and tell the human a major tag is due.
- Never push a `v*` tag yourself. Nothing in *this* repository fires on a tag,
  but a tag is the version every project will pin — a public promise. That is
  the human's call.

---

## Reading a red run cheaply (only when the human ran one)

```bash
# the repo's own token, if the session paired via agent-bootstrap:
python3 /path/to/agent-bootstrap/gh_app.py api GET \
  '/repos/Keshab1997/flutter-builder/actions/runs?per_page=5'

# or with the GitHub CLI:
gh run list -R Keshab1997/flutter-builder -L 5
gh run view <run-id> --log-failed
```

For a consumer project's run, the installed `tool/ci_watch.py` is the cheap
path (`--once` to avoid waiting at all). In both cases: read the failing step's
log **before** editing. Guessing at a red build doubles the rounds — which is
exactly the hour this file exists to prevent.

---

## Working rules

- **Small, focused diffs.** One concern per commit; conventional messages
  (`fix(ui): …`, `chore(release): …`, `docs: …`).
- **Push straight to `main`.** No branch, no PR.
- **Respect the existing voice.** Comments explain *why* the code is the way it
  is; keep that. Read the file before changing it.
- **Secrets never enter git.** `.jks`, `.keystore`, `*.pem`, `key.properties`,
  `google-services.json`, tokens. This repo ships none, and adding one "to make
  CI pass" is never the fix.
- **Prefer editing an existing file** over adding a new one; every new file is
  another thing to keep in sync.

## Ask the human before

- **pushing a `v*` tag, or creating a release** (public, irreversible, affects
  every consumer);
- force-pushing over history, deleting branches or tags;
- touching repository secrets or settings, or the Pages configuration;
- anything that publishes publicly or spends money.

## When to write to `main` versus when to think first

| Change | Do it | Think, then do it |
|---|---|---|
| Docs, comments, README, this file | ✅ push immediately | |
| New optional workflow input, new script, new test | ✅ push immediately | |
| Refactor inside a script, keeping behaviour | ✅ push immediately (tests cover it) | |
| Renamed/removed input, changed required secret, changed permissions | | ✅ push, mark breaking, tell the human a tag is due |
| Anything under `agent-pack/` | | ✅ push *after* `sync-agent-pack.py` + the pack test |

---

## মানুষের জন্য — এই ফাইলটা কী

**এটা `flutter-builder` repo-র ভিতরের playbook।** যে agent এই repo-টা edit
করবে, সে repo-র root থেকে `AGENTS.md` নিজে থেকেই পড়ে নেবে (Codex, Cursor,
Claude ইত্যাদি সবই এটা খোঁজে)।

- **এখানে "test করতে করতে ঘণ্টা" লাগার কোনো কারণ নেই** — পুরো test suite
  **৫ সেকেন্ডে** চলে (`python3 -m pytest tests/ -q`), কোনো Flutter SDK ছাড়াই।
- **CI ম্যানুয়াল** — push করলে কিছুই চলে না, তাই push করে অপেক্ষা করার মানে
  শুধু সময় নষ্ট। তাই এখানে সরাসরি `main`-এ push করাটাই নিয়ম।
- **tag = release** — `main`-এ push নিরাপদ (consumer-রা `@v1.13.1` pin করে),
  কিন্তু নতুন tag দিলে সবার CI একসাথে বদলে যায় — তাই tag আপনার সিদ্ধান্ত।
- **আপনার app project-গুলো** (quizbaaz ইত্যাদি) যে `AGENTS.md` পায় সেটা এই
  ফাইল না — সেটা `agent-pack/AGENTS.template.md` থেকে
  `install-agent-pack.sh` বসায়। পুরোনো project-এ নতুন করে ওই installer
  চালালেই managed block update হয় (বাইরের আপনার নিজের notes অটুট থাকে)।
