#!/usr/bin/env bash
# Publish captured screenshots to a dedicated branch and post them into the PR.
#
# Why a branch: GitHub renders an image in a comment only from a URL, and the
# only URL a workflow can mint for free is raw.githubusercontent.com. Artifacts
# need a login and expire, so they stay as the download path while these copies
# are what makes the screenshots visible at a glance.
#
# Everything here is best-effort: a missing token, a protected branch or an
# unexpected API answer prints a warning and exits 0, because a screenshot
# comment must never turn a green build red.
#
#   SCREENSHOTS_BRANCH=ui-screenshots \
#   GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo \
#   bash scripts/embed-screenshots.sh --src ui-screenshots --comment-out /tmp/c.md
set -euo pipefail

BRANCH="${SCREENSHOTS_BRANCH:-ui-screenshots}"
SRC="ui-screenshots"
COMMENT_OUT=""
MARKER="<!-- flutter-builder-ui-screenshots -->"
IMAGE_WIDTH=320

usage() {
  cat <<'HELP'
Publish screenshots into a branch and comment them on the pull request.

  --src DIR           directory with the PNGs (default: ui-screenshots)
  --branch NAME       branch that holds the images (default: ui-screenshots)
  --comment-out FILE  also write the rendered markdown here
  -h, --help          this text

Environment: GITHUB_TOKEN, GITHUB_REPOSITORY (owner/repo), GITHUB_EVENT_PATH
(the pull request payload). Without a pull request context only the branch is
updated, nothing is commented.
HELP
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --src)         SRC="${2:?--src needs a value}"; shift 2 ;;
    --branch)      BRANCH="${2:?--branch needs a value}"; shift 2 ;;
    --comment-out) COMMENT_OUT="${2:?--comment-out needs a value}"; shift 2 ;;
    -h|--help)     usage; exit 0 ;;
    *) printf 'embed-screenshots: unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

warn() { printf 'embed-screenshots: %s\n' "$*" >&2; }

[ -d "$SRC" ] || { warn "$SRC does not exist; nothing to publish."; exit 0; }
shopt -s nullglob
pngs=("$SRC"/*.png)
[ "${#pngs[@]}" -gt 0 ] || { warn "no PNGs in $SRC; nothing to publish."; exit 0; }

: "${GITHUB_TOKEN:=}"
: "${GITHUB_REPOSITORY:=}"
if [ -z "$GITHUB_TOKEN" ] || [ -z "$GITHUB_REPOSITORY" ]; then
  warn "GITHUB_TOKEN/GITHUB_REPOSITORY are not set; skipping the upload."
  exit 0
fi
command -v git >/dev/null 2>&1 || { warn "git is not installed; skipping."; exit 0; }

# The token travels in a header, never in the remote URL: a URL ends up in git
# error messages and in the run log.
auth_header="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 | tr -d '\n')"
git_auth() { git -c "http.extraheader=$auth_header" "$@"; }

# One directory per branch so two open pull requests never fight over a file.
ref_name="${GITHUB_HEAD_REF:-${GITHUB_REF_NAME:-branch}}"
target="$(printf '%s' "$ref_name" | tr '[:upper:]' '[:lower:]' \
  | sed -e 's#[^a-z0-9._-]\+#-#g' -e 's#^-\{1,\}##' -e 's#-\{1,\}$##')"
short_sha="$(printf '%s' "${GITHUB_SHA:-manual}" | cut -c1-7)"
remote="https://github.com/${GITHUB_REPOSITORY}.git"

workdir="$(mktemp -d)"
cleanup() { rm -rf -- "$workdir"; }
trap cleanup EXIT

if git_auth clone --quiet --depth 1 --branch "$BRANCH" "$remote" "$workdir" 2>/dev/null; then
  :
else
  # First run in this repository: start an orphan branch so nothing from the
  # app's history is dragged along (these are build outputs, not source).
  git -c init.defaultBranch="$BRANCH" init --quiet "$workdir"
  git -C "$workdir" remote add origin "$remote"
  git -C "$workdir" checkout --quiet --orphan "$BRANCH"
  git -C "$workdir" rm -rf --quiet . >/dev/null 2>&1 || true
fi
git -C "$workdir" config user.name "ui-screenshots[bot]"
git -C "$workdir" config user.email "ui-screenshots@users.noreply.github.com"

mkdir -p "$workdir/$target"
rm -f -- "$workdir/$target"/*.png
cp -- "${pngs[@]}" "$workdir/$target/"

git -C "$workdir" add -A
if git -C "$workdir" diff --cached --quiet; then
  printf 'embed-screenshots: images unchanged for %s\n' "$target"
else
  git -C "$workdir" commit --quiet -m "ui: screenshots for ${ref_name} @ ${short_sha}"
  if git_auth -C "$workdir" push --quiet origin "HEAD:$BRANCH" 2>/dev/null; then
    printf 'embed-screenshots: pushed %s image(s) to %s/%s\n' "${#pngs[@]}" "$BRANCH" "$target"
  else
    warn "could not push to '$BRANCH' (protected branch, or the token lacks contents: write)."
    warn "the screenshots are still in the workflow artifact."
    exit 0
  fi
fi

# Markdown for the pull request comment.
comment_file="$(mktemp)"
{
  printf '%s\n' "$MARKER"
  printf '## 📱 UI screenshots (`%s`)\n\n' "$target"
  printf 'Built from `%s`. Click one to open it full size.\n\n' "$short_sha"
  printf '| screen | viewport | size | image |\n|---|---|---|---|\n'
  while IFS=$'\t' read -r name route viewport size; do
    [ -n "$name" ] || continue
    printf '| `%s` | %s | %s KB | <img src="https://raw.githubusercontent.com/%s/%s/%s/%s.png" width="%s" alt="%s"> |\n' \
      "$route" "$viewport" "$((size / 1024))" "$GITHUB_REPOSITORY" "$BRANCH" "$target" \
      "$name" "$IMAGE_WIDTH" "$name"
  done < "$SRC/manifest.tsv"
  printf '\n_Static capture of the web build; animations and platform plugins are not represented._\n'
} > "$comment_file"

if [ -n "$COMMENT_OUT" ]; then
  cp -- "$comment_file" "$COMMENT_OUT"
fi

# Comment (or update the previous comment) when a pull request triggered this.
pr_number=""
if [ -n "${GITHUB_EVENT_PATH:-}" ] && [ -f "${GITHUB_EVENT_PATH}" ]; then
  pr_number="$(python3 - "$GITHUB_EVENT_PATH" <<'PY'
import json, sys
try:
    payload = json.load(open(sys.argv[1]))
except Exception:
    print(""); raise SystemExit
pr = payload.get("pull_request") or {}
print(pr.get("number") or "")
PY
)"
fi
if [ -z "$pr_number" ]; then
  printf 'embed-screenshots: no pull request in this event; branch updated only.\n'
  exit 0
fi

python3 - "$GITHUB_REPOSITORY" "$pr_number" "$MARKER" "$comment_file" <<'PY' || warn "commenting failed; the branch still holds the images."
import json, os, sys, urllib.error, urllib.request

repo, pr_number, marker, comment_path = sys.argv[1:5]
token = os.environ["GITHUB_TOKEN"]
body = open(comment_path, encoding="utf-8").read()
api = f"https://api.github.com/repos/{repo}"
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "embed-screenshots.sh",
}


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(api + path, data=data, method=method,
                                 headers={**headers, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as error:
        return error.code, {"message": error.read().decode(errors="replace")[:200]}


status, comments = call("GET", f"/issues/{pr_number}/comments?per_page=100")
if status != 200 or not isinstance(comments, list):
    print(f"could not list comments (HTTP {status})", file=sys.stderr)
    raise SystemExit(1)
existing = next((c for c in comments if marker in (c.get("body") or "")), None)
if existing:
    status, _ = call("PATCH", f"/issues/comments/{existing['id']}", {"body": body})
    action = "updated"
else:
    status, _ = call("POST", f"/issues/{pr_number}/comments", {"body": body})
    action = "posted"
print(f"embed-screenshots: comment {action} on #{pr_number}" if status < 300
      else f"embed-screenshots: commenting failed (HTTP {status})")
PY
