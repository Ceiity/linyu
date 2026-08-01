#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$SCRIPT_DIR/scripts/install-core.sh" ]]; then
  BOOTSTRAP_REPO="${ASTRBOT_DEPLOY_REPO:-https://github.com/Ceiity/linyu.git}"
  PREFIX="${INSTALL_PREFIX:-/opt/astrbot}"
  command -v git >/dev/null 2>&1 || { apt-get update -y && apt-get install -y git curl ca-certificates; }
  mkdir -p "$PREFIX"
  git_auth_args=()
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    git_auth_args=(-c "http.https://github.com/.extraheader=Authorization: Bearer ${GITHUB_TOKEN}")
  fi
  git_retry(){
    local attempt
    for attempt in 1 2 3; do
      "$@" && return 0
      [[ "$attempt" -lt 3 ]] && sleep "$((attempt * 3))"
    done
    return 1
  }
  if [[ -d "$PREFIX/AstrBot-Deploy/.git" ]]; then
    git_retry git "${git_auth_args[@]}" -C "$PREFIX/AstrBot-Deploy" pull --ff-only
  else
    git_retry git "${git_auth_args[@]}" clone "$BOOTSTRAP_REPO" "$PREFIX/AstrBot-Deploy"
  fi
  exec bash "$PREFIX/AstrBot-Deploy/scripts/install-core.sh"
fi
exec bash "$SCRIPT_DIR/scripts/install-core.sh"
