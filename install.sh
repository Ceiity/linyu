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
  # Pick the fastest route to GitHub (direct or a domestic proxy) by timing
  # a small request through each; NAILONG_MIRROR=off forces direct.
  fastest_repo(){
    local repo="$1" best="" best_t=999999 c t
    [[ "${NAILONG_MIRROR:-auto}" == "off" || -n "${GITHUB_TOKEN:-}" ]] && { echo "$repo"; return; }
    for c in "" https://ghfast.top/ https://gh-proxy.com/ https://ghproxy.net/; do
      t="$(curl -sS -o /dev/null --connect-timeout 3 --max-time 6 -w '%{http_code} %{time_total}' "${c}${repo%.git}/info/refs?service=git-upload-pack" 2>/dev/null || true)"
      [[ "${t%% *}" == "200" ]] || continue
      t="$(awk -v x="${t##* }" 'BEGIN{printf "%d", x*1000}')"
      echo "  GitHub ${c:-direct}: ${t} ms" >&2
      (( t < best_t )) && { best_t="$t"; best="$c"; }
    done
    echo "${best}${repo}"
  }
  dest="$PREFIX/AstrBot-Deploy"
  if [[ -d "$dest/.git" ]]; then
    src="$(fastest_repo "$BOOTSTRAP_REPO")"
    git_retry git "${git_auth_args[@]}" -C "$dest" fetch --depth 1 "$src" main && git -C "$dest" reset --hard FETCH_HEAD
  else
    src="$(fastest_repo "$BOOTSTRAP_REPO")"
    echo "Cloning from ${src}"
    git_retry git "${git_auth_args[@]}" clone --depth 1 "$src" "$dest"
    git -C "$dest" remote set-url origin "$BOOTSTRAP_REPO"
  fi
  exec bash "$PREFIX/AstrBot-Deploy/scripts/install-core.sh"
fi
exec bash "$SCRIPT_DIR/scripts/install-core.sh"
