#!/usr/bin/env bash
# Open (or refresh) one pull request per connected project, moving the
# Keshab1997/flutter-builder pin forward to a newly released tag.
#
# "Connected" means the repository references a reusable workflow from this
# project under .github/workflows/. Discovery is automatic; pass --repos to
# update a fixed list instead.
#
# Nothing is merged. Each project gets its own branch and PR so a human reviews
# the pin bump the way they review any other change, and CI on that project runs
# on the PR before anyone merges it.
#
# Needs a token that can push a branch and open a pull request in every
# connected repository (GH_TOKEN). A fine-grained PAT with Contents: Read and
# write + Pull requests: Read and write on those repositories is enough; the
# token never lands in git.
#
# Usage:
#   GH_TOKEN=... bash scripts/bump-consumers.sh --ref v1.18.4
#   GH_TOKEN=... bash scripts/bump-consumers.sh --ref v1.18.4 --dry-run
#   GH_TOKEN=... bash scripts/bump-consumers.sh --ref v1.18.4 --repos app-a,app-b
set -euo pipefail

REUSABLE_PREFIX='Keshab1997/flutter-builder/.github/workflows/'
DEFAULT_OWNER="${GITHUB_REPOSITORY_OWNER:-Keshab1997}"
BRANCH_PREFIX='chore/flutter-builder-'
COMMIT_NAME='github-actions[bot]'
COMMIT_EMAIL='41898282+github-actions[bot]@users.noreply.github.com'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
BUMP_REF="$SCRIPT_DIR/bump-ref.sh"

say()  { printf '[bump-consumers] %s\n' "$*"; }
fail() { printf '[bump-consumers] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'HELP'
Move every connected project onto a new flutter-builder tag, as a pull request.

Options:
  --ref REF          New pin: a version tag (e.g. v1.18.4) or a 40-character
                     commit SHA. Required.
  --owner OWNER      GitHub user or organisation that owns the projects
                     (default: $GITHUB_REPOSITORY_OWNER, else Keshab1997).
  --repos a,b,c      Update exactly these repositories instead of discovering
                     every repository that references a reusable workflow.
  --dry-run          List what would move without pushing or opening a PR.
  --with-agent-pack  Also refresh each connected repo's agent pack with
                     install-agent-pack.sh --force when its root AGENTS.md
                     already carries the flutter-builder managed block.
  -h, --help         This text.

Environment:
  GH_TOKEN (or GITHUB_TOKEN)   Token that can push branches and open pull
                               requests in the connected repositories.
HELP
}

ref=''
owner="$DEFAULT_OWNER"
repos=''
dry_run=false
with_agent_pack=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --ref)
      [ "$#" -ge 2 ] && [ -n "$2" ] || fail "--ref requires a nonempty value."
      ref="$2"; shift 2 ;;
    --owner)
      [ "$#" -ge 2 ] && [ -n "$2" ] || fail "--owner requires a nonempty value."
      owner="$2"; shift 2 ;;
    --repos)
      [ "$#" -ge 2 ] && [ -n "$2" ] || fail "--repos requires a nonempty value."
      repos="$2"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --with-agent-pack) with_agent_pack=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1 (try --help)." ;;
  esac
done

dry_run_args=()
[ "$dry_run" = true ] && dry_run_args=(--dry-run)

[ -n "$ref" ] || fail "--ref is required (a vX.Y.Z tag; try --help)."
# Same rule as bump-ref.sh: a version tag or a full commit SHA, so no branch
# name or expression can end up inside a consumer's workflow file.
if [[ ! "$ref" =~ ^v[0-9]+(\.[0-9]+){1,2}(-[A-Za-z0-9][A-Za-z0-9.-]*)?$ &&
      ! "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
  fail "Invalid --ref '$ref'. Use a version tag (e.g. v1.18.4) or a 40-character commit SHA."
fi

command -v gh  >/dev/null 2>&1 || fail "GitHub CLI (gh) is required."
command -v git >/dev/null 2>&1 || fail "git is required."
[ -f "$BUMP_REF" ] || fail "bump-ref.sh was not found next to this script ($BUMP_REF)."

token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
[ -n "$token" ] || fail "Set GH_TOKEN to a token that can push and open pull requests in the connected projects."
export GH_TOKEN="$token"

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT

# Isolate git auth from the caller: a private, mode-600 config inside $work,
# removed with the trap. ~/.gitconfig is never mutated for auth and the token
# does not survive the run on disk.
GIT_CONFIG_GLOBAL="$work/git-config"
touch "$GIT_CONFIG_GLOBAL"
chmod 600 "$GIT_CONFIG_GLOBAL"
export GIT_CONFIG_GLOBAL
git config --global user.name "$COMMIT_NAME"
git config --global user.email "$COMMIT_EMAIL"
git config --global url."https://x-access-token:${token}@github.com/".insteadOf "https://github.com/"

say "Owner: $owner"
say "Target pin: @$ref"

# --- discovery ---------------------------------------------------------------

list_repos() {
  if [ -n "$repos" ]; then
    printf '%s\n' "$repos" | tr ',' '\n' | tr -d ' ' | sed '/^$/d'
    return
  fi
  gh repo list "$owner" --limit 500 --json name,isArchived \
    --jq '.[] | select(.isArchived | not) | .name'
}

default_branch() {
  gh api "repos/$owner/$1" --jq '.default_branch' 2>/dev/null || true
}

# Print the workflow paths that reference a reusable workflow from this project
# (empty output means the repository is not connected).
connected_paths() {
  local name="$1" branch="$2" path
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    if gh api -H 'Accept: application/vnd.github.raw' \
         "repos/$owner/$name/contents/$path?ref=$branch" 2>/dev/null \
       | grep -qF "$REUSABLE_PREFIX"; then
      printf '%s\n' "$path"
    fi
  done < <(gh api "repos/$owner/$name/contents/.github/workflows?ref=$branch" \
             --jq '.[].path' 2>/dev/null || true)
}

pr_body() {
  cat <<EOF
This moves the reusable workflow pin(s) under \`.github/workflows/\` to \`${ref}\`.

Opened automatically because this repository references
\`Keshab1997/flutter-builder\`. Only the \`@ref\` on \`uses:\` lines changes:
custom jobs, comments and inputs are left exactly as they are.

- Merge when you are ready to move CI onto \`${ref}\`.
- Close it to stay on the current pin; nothing is merged automatically.
EOF
}

# --- main loop ---------------------------------------------------------------

moved=0
skipped=0
failed=0
branch="$BRANCH_PREFIX$ref"

while IFS= read -r name; do
  [ -n "$name" ] || continue
  base="$(default_branch "$name")"
  if [ -z "$base" ]; then
    say "skip $name (could not read its default branch)"
    skipped=$((skipped + 1))
    continue
  fi
  if [ -z "$(connected_paths "$name" "$base")" ]; then
    say "skip $name (does not reference $REUSABLE_PREFIX)"
    skipped=$((skipped + 1))
    continue
  fi

  clone="$work/$name"
  rm -rf -- "$clone"
  if ! git clone --quiet --depth 1 --branch "$base" \
       "https://github.com/$owner/$name.git" "$clone" 2>/dev/null; then
    say "FAILED $name (clone failed)"
    failed=$((failed + 1))
    continue
  fi

  # Rewrite the workflow pins. In dry-run mode bump-ref only reports; in
  # real mode the working tree diff tells us whether anything changed.
  if ! out="$(cd "$clone" && bash "$BUMP_REF" --ref "$ref" "${dry_run_args[@]}" </dev/null 2>&1)"; then
    say "skip $name (no pins to rewrite)"
    skipped=$((skipped + 1))
    continue
  fi

  workflows_changed=false
  pack_changed=false

  if [ "$dry_run" = true ]; then
    [ "$(printf '%s\n' "$out" | grep -c 'would update' || true)" -gt 0 ] \
      && workflows_changed=true
  elif ! git -C "$clone" diff --quiet -- .github/workflows; then
    workflows_changed=true
  fi

  # Opt-in agent-pack sync: only repos whose root AGENTS.md already carries
  # the flutter-builder managed block get the pack; everything else stays
  # workflow-only. The pack install writes to the clone's working tree and
  # never commits, so it is safe to combine with the pin bump in one PR.
  if [ "$with_agent_pack" = true ] && [ -e "$clone/AGENTS.md" ] \
     && grep -qF '<!-- flutter-builder:agent-pack:start' "$clone/AGENTS.md" 2>/dev/null; then
    agent_args=(--force)
    [ "$dry_run" = true ] && agent_args+=(--dry-run)
    if ! pack_out="$(cd "$clone" && bash "$SCRIPT_DIR/install-agent-pack.sh" "${agent_args[@]}" </dev/null 2>&1)"; then
      [ ! -L "$clone/.agent-pack-backups" ] && rm -rf -- "$clone/.agent-pack-backups"
      first_line="$(printf '%s\n' "$pack_out" | head -n 1)"
      say "FAILED $name (agent-pack sync failed: ${first_line:-unknown error})"
      failed=$((failed + 1))
      continue
    fi
    # Never leave replaced originals behind in the consumer clone.
    [ ! -L "$clone/.agent-pack-backups" ] && rm -rf -- "$clone/.agent-pack-backups"
    if [ "$dry_run" = true ]; then
      printf '%s\n' "$pack_out" | grep -qE 'Will (add|update|replace)' && pack_changed=true
    else
      pack_paths=()
      [ -e "$clone/AGENTS.md" ] && pack_paths+=(AGENTS.md)
      [ -d "$clone/tool" ] && pack_paths+=(tool)
      [ -e "$clone/.gitignore" ] && pack_paths+=(.gitignore)
      if [ "${#pack_paths[@]}" -gt 0 ] \
         && [ -n "$(git -C "$clone" status --porcelain -- "${pack_paths[@]}")" ]; then
        pack_changed=true
      fi
    fi
  fi

  if [ "$workflows_changed" = false ] && [ "$pack_changed" = false ]; then
    say "skip $name (already at $ref)"
    skipped=$((skipped + 1))
    continue
  fi

  if [ "$dry_run" = true ]; then
    what="workflows"
    if [ "$workflows_changed" = true ] && [ "$pack_changed" = true ]; then
      what="workflows + agent pack"
    elif [ "$pack_changed" = true ]; then
      what="agent pack"
    fi
    say "$name: would open a PR ($what -> @$ref)"
    moved=$((moved + 1))
    continue
  fi

  git -C "$clone" checkout --quiet -b "$branch"
  [ "$workflows_changed" = true ] && git -C "$clone" add -- .github/workflows
  if [ "$pack_changed" = true ]; then
    [ -e "$clone/AGENTS.md" ] && git -C "$clone" add -- AGENTS.md
    [ -d "$clone/tool" ] && git -C "$clone" add -- tool
    [ -e "$clone/.gitignore" ] && git -C "$clone" add -- .gitignore
  fi
  files="$(git -C "$clone" diff --cached --name-only | tr '\n' ' ')"
  say "$name: ${files% } -> @$ref"
  git -C "$clone" commit --quiet -m "chore(ci): bump flutter-builder to ${ref}"

  # Re-running updates the branch (and therefore the open PR) instead of
  # failing: fetch the remote branch first so --force-with-lease has something
  # to compare against, rather than a plain, unsafe --force.
  git -C "$clone" fetch --quiet origin "$branch" 2>/dev/null || true
  if ! git -C "$clone" push --quiet --force-with-lease origin "$branch" 2>/dev/null; then
    say "FAILED $name (could not push $branch)"
    failed=$((failed + 1))
    continue
  fi

  body="$(pr_body)"
  if [ "$pack_changed" = true ]; then
    body="$body
The agent pack was also refreshed in this pull request:
install-agent-pack.sh --force ran inside the clone, so the
flutter-builder:agent-pack block in AGENTS.md and the files under tool/ now
match the pack shipped with this flutter-builder release."
  fi

  url="$(gh pr list --repo "$owner/$name" --head "$branch" --state open \
           --json url --jq '.[0].url // ""' 2>/dev/null || true)"
  if [ -n "$url" ]; then
    say "refreshed the open PR: $url"
  elif url="$(gh pr create --repo "$owner/$name" --base "$base" --head "$branch" \
                 --title "chore(ci): bump flutter-builder to ${ref}" \
                 --body "$body" 2>&1)"; then
    say "opened: $url"
  else
    say "FAILED $name (could not open a PR: $url)"
    failed=$((failed + 1))
    continue
  fi
  moved=$((moved + 1))

  # Supersede earlier chore/flutter-builder-* PRs for this project so
  # pin-bump PRs don't pile up across releases. Close each superseded PR with
  # a comment linking the new PR and delete its head branch. Best-effort: a
  # close failure warns but never fails the newly opened PR, and only
  # chore/flutter-builder-* PRs are ever touched.
  while IFS=$'\t' read -r number other_url head_ref; do
    [ -n "$number" ] || continue
    [ "$head_ref" = "$branch" ] && continue
    [[ "$head_ref" == "$BRANCH_PREFIX"* ]] || continue
    say "$name: superseding stale PR $head_ref ($other_url)"
    if ! gh pr comment "$number" --repo "$owner/$name" --body \
          "Superseded by $url — this pin-bump PR is stale; $url replaces it." 2>/dev/null; then
      say "$name: warn (could not comment on $head_ref)"
    fi
    if ! gh pr close "$number" --repo "$owner/$name" --delete-branch 2>/dev/null; then
      say "$name: warn (could not close/delete $head_ref)"
    fi
  done < <(gh api "repos/$owner/$name/pulls?state=open&per_page=100" \
             --jq '.[] | select(.head.repo.full_name == .base.repo.full_name) | [.number, .html_url, .head.ref] | @tsv' 2>/dev/null || true)
done < <(list_repos)

if [ "$dry_run" = true ]; then
  say "Dry run: $moved project(s) would get a PR, $skipped skipped. Nothing was pushed."
else
  say "Done: $moved project(s) updated, $skipped skipped, $failed failed."
fi

[ "$failed" -eq 0 ]
