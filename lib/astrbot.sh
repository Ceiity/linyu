#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker.sh"
generate_astrbot_compose(){
  local file="$COMPOSE_DIR/astrbot/docker-compose.yml"; mkdir -p "$(dirname "$file")" "$DATA_DIR"
  : "${ASTRBOT_WEB_PORT:=$(find_free_port 6185)}"; : "${ASTRBOT_WS_PORT:=$(find_free_port 6199)}"
  cat > "$file" <<EOF
services:
  astrbot:
    image: ${ASTRBOT_IMAGE}
    container_name: ${ASTRBOT_CONTAINER}
    restart: always
    security_opt:
      - no-new-privileges:true
    ports:
      - "${ASTRBOT_WEB_PORT}:6185"
      - "${ASTRBOT_WS_PORT}:6199"
    environment:
      - TZ=${DEFAULT_TIMEZONE}
    volumes:
      - ${DATA_DIR}:/AstrBot/data
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    networks:
      - ${NETWORK_NAME}
networks:
  ${NETWORK_NAME}:
    external: true
EOF
  save_state_var ASTRBOT_WEB_PORT "$ASTRBOT_WEB_PORT"; save_state_var ASTRBOT_WS_PORT "$ASTRBOT_WS_PORT"; save_state_var ASTRBOT_IMAGE "$ASTRBOT_IMAGE"; echo "$file"
}
deploy_astrbot(){ step "Deploying AstrBot with official image ${ASTRBOT_IMAGE}"; local file; file="$(generate_astrbot_compose)"; compose_pull "$file" || warn "Image pull failed; trying to start with local image/cache."; compose_up "$file"; wait_container "$ASTRBOT_CONTAINER" 180 || { docker logs "$ASTRBOT_CONTAINER" --tail 120 || true; fail "AstrBot container did not become running."; exit 1; }; wait_astrbot_web 180 || warn "AstrBot WebUI did not return HTTP success yet; container is running."; success "AstrBot started: http://$(private_ip):${ASTRBOT_WEB_PORT}"; }
wait_astrbot_web(){ local timeout="$1" i; for ((i=1;i<=timeout;i++)); do curl -fsS --max-time 2 "http://127.0.0.1:${ASTRBOT_WEB_PORT}/" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
get_astrbot_password(){ local pass="" zh1 zh2; zh1=$'\345\210\235\345\247\213\345\257\206\347\240\201'; zh2=$'\351\232\217\346\234\272\345\210\235\345\247\213\345\257\206\347\240\201'; pass="$(docker logs "$ASTRBOT_CONTAINER" 2>&1 | grep -Ei "$zh1|$zh2|password|passwd" | sed -nE 's/.*[^A-Za-z0-9._@#%+=:-]([A-Za-z0-9._@#%+=:-]{6,}).*/\1/p' | tail -n1 || true)"; if [[ -z "$pass" ]]; then pass="$(grep -RIEho '"?(password|passwd|initial_password)"?[[:space:]]*[:=][[:space:]]*"?[A-Za-z0-9._@#%+=:-]{6,}' "$DATA_DIR" 2>/dev/null | sed -nE 's/.*[:=][[:space:]]*"?([^"[:space:]]+).*/\1/p' | tail -n1 || true)"; fi; [[ -n "$pass" ]] && echo "$pass" || echo "Not parsed automatically; inspect docker logs ${ASTRBOT_CONTAINER}"; }
get_astrbot_token(){ echo "Official docs do not expose a stable first-run automatic token API; not generated"; }

apply_astrbot_default_config(){
  local src=""
  if [[ -n "${ASTRBOT_CONFIG_FILE:-}" && -f "${ASTRBOT_CONFIG_FILE}" ]]; then
    src="${ASTRBOT_CONFIG_FILE}"
  elif [[ -n "${ASTRBOT_CONFIG_URL:-}" ]]; then
    src="${INSTALL_PREFIX}/cmd_config.downloaded.json"
    curl -fsSL "${ASTRBOT_CONFIG_URL}" -o "$src"
  elif [[ -f "${PROJECT_DIR}/templates/astrbot/cmd_config.json" ]]; then
    src="${PROJECT_DIR}/templates/astrbot/cmd_config.json"
  fi
  [[ -n "$src" ]] || return 0
  step "Applying AstrBot default config"
  jq empty "$src" >/dev/null
  mkdir -p "$DATA_DIR"
  local dst="$DATA_DIR/cmd_config.json"
  if [[ -f "$dst" ]]; then
    cp -a "$dst" "$dst.bak.$(date '+%Y%m%d_%H%M%S')"
  fi
  local tmp="$INSTALL_PREFIX/cmd_config.effective.json"
  jq '.dashboard = (.dashboard // {}) | .dashboard.host = "0.0.0.0" | .dashboard.port = 6185' "$src" > "$tmp"
  install -m 600 "$tmp" "$dst"
  rm -f "$tmp"
  if container_running "$ASTRBOT_CONTAINER"; then
    docker restart "$ASTRBOT_CONTAINER" >/dev/null
    wait_container "$ASTRBOT_CONTAINER" 180 || { docker logs "$ASTRBOT_CONTAINER" --tail 120 || true; fail "AstrBot failed to restart after applying config."; exit 1; }
    wait_astrbot_web 180 || warn "AstrBot WebUI did not return HTTP success after restart; container is running."
  fi
  success "AstrBot default config applied: $dst"
}
