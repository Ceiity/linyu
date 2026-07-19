#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
wait_apt_locks(){
  local i
  for i in $(seq 1 90); do
    if fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || fuser /var/lib/dpkg/lock >/dev/null 2>&1 || fuser /var/cache/apt/archives/lock >/dev/null 2>&1; then
      warn "Waiting for apt/dpkg lock ${i}/90"
      sleep 10
    else
      return 0
    fi
  done
  fail "apt/dpkg lock wait timeout"
  return 1
}
install_dependencies(){ step "Installing system dependencies"; export DEBIAN_FRONTEND=noninteractive; wait_apt_locks; apt-get update -y; wait_apt_locks; apt-get install -y ca-certificates curl wget git gnupg lsb-release jq tar gzip coreutils iproute2 procps openssl; }
install_docker(){
  if have_cmd docker && docker version >/dev/null 2>&1; then success "Docker already installed: $(docker --version)"; else
    step "Installing Docker"; apt-get install -y docker.io || true; apt-get install -y docker-compose-plugin docker-compose || true; if ! have_cmd docker; then curl -fsSL https://get.docker.com | sh; fi
  fi
  systemctl enable docker >/dev/null 2>&1 || true; systemctl start docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true
  docker version >/dev/null 2>&1 || { fail "Docker failed to start. Inspect: journalctl -u docker"; exit 1; }
  if ! docker compose version >/dev/null 2>&1 && ! have_cmd docker-compose; then apt-get install -y docker-compose-plugin || true; apt-get install -y docker-compose || true; fi
  compose_cmd >/dev/null || { fail "Docker Compose is not available."; exit 1; }
  success "Docker: $(docker --version)"; success "Compose: $($(compose_cmd) version 2>/dev/null | head -n1)"
}
ensure_network(){ step "Ensuring Docker network: $NETWORK_NAME"; if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then success "Network exists: $NETWORK_NAME"; else docker network create --driver bridge "$NETWORK_NAME" >/dev/null; success "Network created: $NETWORK_NAME"; fi; }
compose_up(){
  local file="$1" t="${DOCKER_COMPOSE_UP_TIMEOUT:-900}"
  timeout "$t" $(compose_cmd) -f "$file" up -d --remove-orphans
}
compose_pull(){
  local file="$1" t="${DOCKER_PULL_TIMEOUT:-120}"
  timeout "$t" $(compose_cmd) -f "$file" pull
}
container_running(){ local name="$1"; [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || echo false)" == "true" ]]; }
wait_container(){ local name="$1" timeout="${2:-180}" i; for ((i=1;i<=timeout;i++)); do if container_running "$name"; then return 0; fi; sleep 1; done; return 1; }
