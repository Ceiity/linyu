#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/mirror.sh"
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
install_dependencies(){ export DEBIAN_FRONTEND=noninteractive; setup_mirrors_early; step "Installing system dependencies"; wait_apt_locks; apt-get update -y; wait_apt_locks; apt-get install -y ca-certificates curl wget git gnupg lsb-release jq tar gzip coreutils iproute2 procps openssl python3; }
ensure_compose(){
  docker compose version >/dev/null 2>&1 && return 0
  local package
  wait_apt_locks
  # Docker CE and Ubuntu's docker.io use different Compose v2 package names.
  for package in docker-compose-plugin docker-compose-v2; do
    if apt-get install -y "$package" && docker compose version >/dev/null 2>&1; then
      success "Docker Compose v2 installed: $package"
      return 0
    fi
  done
  if have_cmd docker-compose; then
    warn "Compose v2 packages unavailable; keeping existing standalone Compose."
    return 0
  fi
  if apt-get install -y docker-compose && have_cmd docker-compose; then
    warn "Compose v2 packages unavailable; using standalone Compose fallback."
    return 0
  fi
  fail "Docker Compose is not available."
  return 1
}
install_docker(){
  if have_cmd docker && docker version >/dev/null 2>&1; then success "Docker already installed: $(docker --version)"; else
    step "Installing Docker"; apt-get install -y docker.io || true; if ! have_cmd docker; then if [[ -n "${GH_PROXY:-}" ]]; then curl -fsSL https://get.docker.com | sh -s -- --mirror Aliyun; else curl -fsSL https://get.docker.com | sh; fi; fi
  fi
  systemctl enable docker >/dev/null 2>&1 || true; systemctl start docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true
  docker version >/dev/null 2>&1 || { fail "Docker failed to start. Inspect: journalctl -u docker"; exit 1; }
  setup_docker_mirrors || warn "Docker registry mirror setup failed; continuing with Docker Hub"
  ensure_compose || exit 1
  compose_cmd >/dev/null || { fail "Docker Compose is not available."; exit 1; }
  success "Docker: $(docker --version)"; success "Compose: $($(compose_cmd) version 2>/dev/null | head -n1)"
}
ensure_network(){ step "Ensuring Docker network: $NETWORK_NAME"; if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then success "Network exists: $NETWORK_NAME"; else docker network create --driver bridge "$NETWORK_NAME" >/dev/null; success "Network created: $NETWORK_NAME"; fi; }
compose_up(){
  local file="$1" t="${DOCKER_COMPOSE_UP_TIMEOUT:-900}"
  timeout "$t" $(compose_cmd) -f "$file" up -d --remove-orphans
}
compose_pull(){
  local file="$1" t="${DOCKER_PULL_TIMEOUT:-600}"
  timeout "$t" $(compose_cmd) -f "$file" pull
}
container_running(){ local name="$1"; [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || echo false)" == "true" ]]; }
wait_container(){ local name="$1" timeout="${2:-180}" i; for ((i=1;i<=timeout;i++)); do if container_running "$name"; then return 0; fi; sleep 1; done; return 1; }
