#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/git_push_no_proxy.sh -m "commit message" [options]

Options:
  -m, --message MESSAGE   Commit message (required)
  -r, --remote REMOTE     Git remote name (default: origin)
  -b, --branch BRANCH     Git branch name (default: current branch)
  -f, --force             Use git push --force
  --skip-curl-check       Skip curl connectivity check for Gitee
  -h, --help              Show this help
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

message=""
remote="origin"
branch=""
force_push="false"
skip_curl_check="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message)
      shift
      [[ $# -gt 0 ]] || { echo "Missing value for --message" >&2; exit 1; }
      message="$1"
      ;;
    -r|--remote)
      shift
      [[ $# -gt 0 ]] || { echo "Missing value for --remote" >&2; exit 1; }
      remote="$1"
      ;;
    -b|--branch)
      shift
      [[ $# -gt 0 ]] || { echo "Missing value for --branch" >&2; exit 1; }
      branch="$1"
      ;;
    -f|--force)
      force_push="true"
      ;;
    --skip-curl-check)
      skip_curl_check="true"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

[[ -n "$message" ]] || { echo "Commit message is required." >&2; usage >&2; exit 1; }

require_cmd git
require_cmd curl

if [[ -z "$branch" ]]; then
  branch="$(git branch --show-current)"
fi

[[ -n "$branch" ]] || { echo "Could not determine current branch." >&2; exit 1; }

echo "Clearing proxy environment variables..."
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

echo "Removing git proxy configuration if present..."
git config --global --unset http.proxy 2>/dev/null || true
git config --global --unset https.proxy 2>/dev/null || true

if [[ "$skip_curl_check" != "true" ]]; then
  echo "Checking HTTPS connectivity to Gitee..."
  curl -I --max-time 15 https://gitee.com >/dev/null
fi

echo "Staging changes..."
git add -A

if git diff --cached --quiet; then
  echo "No staged changes to commit."
else
  echo "Creating commit..."
  git commit -m "$message" -n
fi

push_args=(push "$remote" "$branch")
if [[ "$force_push" == "true" ]]; then
  push_args=(push --force "$remote" "$branch")
fi

echo "Pushing to $remote/$branch..."
git "${push_args[@]}"

echo "Done."
