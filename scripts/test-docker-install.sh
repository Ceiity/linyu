#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export INSTALL_PREFIX="$tmp/install" LOG_DIR="$tmp/logs"
source "$ROOT/lib/docker.sh"
calls="$tmp/packages"
native=0 legacy=0 available=""
wait_apt_locks(){ :; }
docker(){ [[ "$*" == 'compose version' && "$native" == 1 ]]; }
have_cmd(){ [[ "$1" == docker-compose && "$legacy" == 1 ]]; }
apt-get(){
  local pkg="${*: -1}"
  echo "$pkg" >> "$calls"
  [[ "$pkg" == "$available" ]] || return 1
  if [[ "$pkg" == docker-compose ]]; then legacy=1; else native=1; fi
}

# An already installed v2 must not perform package operations.
: > "$calls"; native=1
ensure_compose
[[ ! -s "$calls" ]]

# Docker CE: first package works, Ubuntu-specific fallback is not installed.
: > "$calls"; native=0; available=docker-compose-plugin
ensure_compose
[[ "$(cat "$calls")" == docker-compose-plugin ]]

# Ubuntu docker.io: docker-compose-plugin is absent, docker-compose-v2 works.
: > "$calls"; native=0; available=docker-compose-v2
ensure_compose
[[ "$native" == 1 ]]
[[ "$(cat "$calls")" == $'docker-compose-plugin\ndocker-compose-v2' ]]

# A preexisting v1 must not prevent an attempt to upgrade to native v2.
: > "$calls"; native=0; legacy=1; available=docker-compose-v2
ensure_compose
[[ "$native" == 1 ]]

# No v2 available: keep a working legacy installation.
: > "$calls"; native=0; legacy=1; available=""
ensure_compose
[[ "$(cat "$calls")" == $'docker-compose-plugin\ndocker-compose-v2' ]]

# Fresh system with only the legacy package available.
: > "$calls"; native=0; legacy=0; available=docker-compose
ensure_compose
[[ "$legacy" == 1 ]]

# No usable package must return failure.
: > "$calls"; native=0; legacy=0; available=""
if ensure_compose; then echo 'Expected unavailable Compose failure' >&2; exit 1; fi
echo 'Docker Compose installation tests passed'
