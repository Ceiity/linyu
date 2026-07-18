#!/usr/bin/env bash
set -Eeuo pipefail
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$LIB_DIR/config.sh"
source "$LIB_DIR/logging.sh"
require_root(){ if [[ ${EUID:-$(id -u)} -ne 0 ]]; then fail "Please run as root."; exit 1; fi; }
ensure_dirs(){ mkdir -p "$INSTALL_PREFIX" "$PROJECT_DIR" "$DATA_DIR" "$COMPOSE_DIR" "$NAPCAT_BASE_DIR" "$BACKUP_DIR" "$LOG_DIR"; }
load_state(){ [[ -f "$STATE_FILE" ]] && set -a && source "$STATE_FILE" && set +a || true; }
save_state_var(){ local key="$1" val="$2" tmp="${STATE_FILE}.tmp"; touch "$STATE_FILE"; grep -vE "^${key}=" "$STATE_FILE" > "$tmp" || true; printf '%s=%q\n' "$key" "$val" >> "$tmp"; mv "$tmp" "$STATE_FILE"; }
have_cmd(){ command -v "$1" >/dev/null 2>&1; }
retry(){ local attempts="$1" delay="$2"; shift 2; local i; for ((i=1;i<=attempts;i++)); do if "$@"; then return 0; fi; warn "Attempt $i/$attempts failed; retrying in ${delay}s: $*"; sleep "$delay"; done; return 1; }
public_ip(){ curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null || echo "unknown"; }
private_ip(){ hostname -I 2>/dev/null | awk '{print $1}' || ip route get 1.1.1.1 2>/dev/null | awk '/src/{print $7; exit}' || echo "unknown"; }
os_pretty(){ if [[ -r /etc/os-release ]]; then . /etc/os-release; echo "${PRETTY_NAME:-$ID $VERSION_ID}"; else uname -a; fi; }
validate_os(){ if [[ -r /etc/os-release ]]; then . /etc/os-release; case "${ID:-}" in ubuntu|debian) success "OS: ${PRETTY_NAME:-$ID}";; *) warn "OS ${PRETTY_NAME:-unknown}; Debian/Ubuntu are the primary targets; continuing.";; esac; fi; }
validate_arch(){ local arch; arch="$(uname -m)"; case "$arch" in x86_64|amd64|aarch64|arm64) success "CPU architecture: $arch";; *) fail "Unsupported CPU architecture: $arch"; exit 1;; esac; }
network_check(){
  if retry 2 2 curl -fsS --max-time 8 https://github.com >/dev/null; then
    success "Network check passed"
  else
    warn "GitHub connectivity is unstable; continuing because apt/Docker may still work."
  fi
}
compose_cmd(){ if docker compose version >/dev/null 2>&1; then echo "docker compose"; elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; else return 1; fi; }
port_in_use(){ local p="$1"; if have_cmd ss; then ss -ltnH "sport = :$p" 2>/dev/null | grep -q .; elif have_cmd netstat; then netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]$p$"; else timeout 1 bash -c "</dev/tcp/127.0.0.1/$p" >/dev/null 2>&1; fi; }
find_free_port(){ local p="$1" limit="${2:-2000}" i; for ((i=0;i<limit;i++)); do if ! port_in_use "$((p+i))"; then echo "$((p+i))"; return 0; fi; done; return 1; }
random_token(){ if have_cmd openssl; then openssl rand -hex 18; else tr -dc 'A-Za-z0-9' </dev/urandom | head -c 36; echo; fi; }
