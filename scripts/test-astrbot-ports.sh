#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export INSTALL_PREFIX="$tmp/install" LOG_DIR="$tmp/logs"
source "$ROOT/lib/astrbot.sh"
mkdir -p "$INSTALL_PREFIX"
export ASTRBOT_WEB_PORT=6185 ASTRBOT_WS_PORT=6199
file="$(generate_astrbot_compose)"
grep -q '^      - "8686:8686"$' "$file"
grep -Fq -- "${DATA_DIR}:/AstrBot/data" "$file"
generate_astrbot_compose >/dev/null
[[ "$(grep -c '"8686:8686"' "$file")" == 1 ]]

calls="$tmp/firewall.calls"
: > "$calls"
have_cmd(){ [[ "$1" == ufw || "$1" == firewall-cmd ]]; }
ufw(){ printf 'ufw %s\n' "$*" >> "$calls"; }
firewall-cmd(){ printf 'firewall-cmd %s\n' "$*" >> "$calls"; }
configure_astrbot_firewall
grep -qx 'ufw allow 8686/tcp' "$calls"
grep -qx 'firewall-cmd --permanent --add-port=8686/tcp' "$calls"
grep -qx 'firewall-cmd --add-port=8686/tcp' "$calls"
! grep -Eq '(enable|reload|delete|flush)' "$calls"

# Missing firewalls must not trigger installation or new rules.
: > "$calls"
have_cmd(){ return 1; }
configure_astrbot_firewall
[[ ! -s "$calls" ]]

# A stopped firewalld stays stopped.
have_cmd(){ [[ "$1" == firewall-cmd ]]; }
firewall-cmd(){ printf 'firewall-cmd %s\n' "$*" >> "$calls"; return 1; }
configure_astrbot_firewall
[[ "$(cat "$calls")" == 'firewall-cmd --state' ]]

# Errors propagate, rather than reporting a successful rule change.
have_cmd(){ [[ "$1" == ufw ]]; }
ufw(){ return 1; }
if configure_astrbot_firewall; then
  echo 'Expected firewall failure' >&2
  exit 1
fi

# Both deploy entry points call this shared function; test its orchestration
# with Docker mocked, so no real containers or host firewall are modified.
events="$tmp/deploy.events"
compose_pull(){ :; }
configure_astrbot_firewall(){ echo firewall >> "$events"; }
compose_up(){ grep -q '"8686:8686"' "$1"; echo up >> "$events"; }
wait_container(){ return 0; }
wait_astrbot_web(){ return 0; }
private_ip(){ echo 127.0.0.1; }
deploy_astrbot
[[ "$(cat "$events")" == $'firewall\nup' ]]
echo 'AstrBot TCP 8686 tests passed'
