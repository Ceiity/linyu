#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export INSTALL_PREFIX="$tmp/install" LOG_DIR="$tmp/logs" MIRROR_DISCOVERY=off
source "$ROOT/lib/common.sh"
source "$ROOT/lib/mirror.sh"

# A generic HTTP-200 homepage is not a valid Docker registry.
(
  curl(){
    local headers="" url=""
    while (( $# )); do
      case "$1" in -D) headers="$2"; shift 2 ;; *) url="$1"; shift ;; esac
    done
    if [[ "$url" == https://registry.example/v2/ ]]; then
      printf 'HTTP/2 401\r\nDocker-Distribution-Api-Version: registry/2.0\r\n' > "$headers"
      printf '401 0.125'
    else
      printf 'HTTP/2 200\r\nContent-Type: text/html\r\n' > "$headers"
      printf '200 0.010'
    fi
  }
  [[ "$(mirror_probe https://registry.example/v2/ '200 401')" == 125 ]]
  if mirror_probe https://homepage.example/v2/ '200 401'; then
    echo 'Accepted a fake registry homepage' >&2; exit 1
  fi
)

# Deterministic bounded races: duplicate entries, rejected hosts, ordering, cap.
mirror_probe(){
  case "$1" in
    https://slow.example/*) echo 300 ;;
    https://fast.example/*) echo 20 ;;
    *) return 1 ;;
  esac
}
results="$(mirror_race test /v2/ '200 401' https://slow.example https://slow.example https://fast.example https://bad.example)"
[[ "$results" == $'20 https://fast.example\n300 https://slow.example' ]]
MIRROR_MAX_CANDIDATES=1
[[ "$(mirror_race test /v2/ '200' https://slow.example https://fast.example)" == '300 https://slow.example' ]]
unset MIRROR_MAX_CANDIDATES

# Use a real temporary JSON config but never restart the actual Docker daemon.
export DOCKER_DAEMON_CONFIG="$tmp/daemon.json" DOCKER_MIRRORS=https://first.example
calls="$tmp/restarts"
have_cmd(){
  case "$1" in docker) return 0 ;; dockerd) return 1 ;; *) command -v "$1" >/dev/null 2>&1 ;; esac
}
restart_docker_for_mirrors(){ echo restart >> "$calls"; }
printf '{ "log-driver": "json-file" }\n' > "$DOCKER_DAEMON_CONFIG"
setup_docker_mirrors
[[ "$(wc -l < "$calls" | tr -d ' ')" == 1 ]]
setup_docker_mirrors
[[ "$(wc -l < "$calls" | tr -d ' ')" == 1 ]]
python3 - "$DOCKER_DAEMON_CONFIG" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d['log-driver'] == 'json-file'
assert d['registry-mirrors'] == ['https://first.example']
PY

# Failed restart restores byte-for-byte config and attempts recovery once.
cp "$DOCKER_DAEMON_CONFIG" "$tmp/before"
export DOCKER_MIRRORS=https://second.example
: > "$calls"
restart_docker_for_mirrors(){
  echo restart >> "$calls"
  [[ "$(wc -l < "$calls" | tr -d ' ')" == 2 ]]
}
if setup_docker_mirrors; then echo 'Expected failed restart status' >&2; exit 1; fi
cmp "$DOCKER_DAEMON_CONFIG" "$tmp/before"
[[ "$(wc -l < "$calls" | tr -d ' ')" == 2 ]]

# Invalid dockerd configuration must be restored without restarting.
: > "$calls"
have_cmd(){
  case "$1" in docker|dockerd) return 0 ;; *) command -v "$1" >/dev/null 2>&1 ;; esac
}
dockerd(){ return 1; }
if setup_docker_mirrors; then echo 'Expected validation failure' >&2; exit 1; fi
cmp "$DOCKER_DAEMON_CONFIG" "$tmp/before"
[[ ! -s "$calls" ]]

# Disabled mirrors are a no-op, even with an explicit config override.
NAILONG_MIRROR=off setup_docker_mirrors
cmp "$DOCKER_DAEMON_CONFIG" "$tmp/before"
echo 'Mirror orchestration tests passed'
