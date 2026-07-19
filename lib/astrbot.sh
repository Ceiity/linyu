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
get_astrbot_password(){
  local pass="" logs
  logs="$(docker logs "$ASTRBOT_CONTAINER" 2>&1 || true)"
  pass="$(printf '%s\n' "$logs" | sed -nE 's/.*Initial password:[[:space:]]*([A-Za-z0-9._@#%+=:-]{6,}).*/\1/p' | tail -n1 || true)"
  if [[ -z "$pass" ]]; then
    pass="$(printf '%s\n' "$logs" | sed -nE 's/.*(初始密码|随机初始密码)[^A-Za-z0-9._@#%+=:-]*([A-Za-z0-9._@#%+=:-]{6,}).*/\2/p' | tail -n1 || true)"
  fi
  if [[ -z "$pass" ]]; then
    pass="$(grep -RIEho '"?(password|passwd|initial_password)"?[[:space:]]*[:=][[:space:]]*"?[A-Za-z0-9._@#%+=:-]{6,}' "$DATA_DIR" 2>/dev/null | sed -nE 's/.*[:=][[:space:]]*"?([^"[:space:]]+).*/\1/p' | tail -n1 || true)"
  fi
  [[ -n "$pass" ]] && echo "$pass" || echo "Not parsed automatically; inspect docker logs ${ASTRBOT_CONTAINER}"
}
get_astrbot_token(){ echo "${ASTRBOT_REVERSE_WS_TOKEN}"; }

astrbot_common_jq_filter(){
  cat <<'EOF'
.dashboard = (.dashboard // {})
| .dashboard.host = "0.0.0.0"
| .dashboard.port = 6185
| .platform_settings = (.platform_settings // {})
| .platform_settings.enable_id_white_list = false
| .platform_settings.id_whitelist = []
| .platform_settings.id_whitelist_log = false
| .platform_settings.wl_ignore_admin_on_group = true
| .platform_settings.wl_ignore_admin_on_friend = true
| .platform_settings.reply_prefix = ""
| .platform_settings.wake_prefix = ""
| .platform_settings.reply_with_mention = false
| .platform_settings.reply_with_quote = false
| .platform_settings.friend_message_needs_wake_prefix = false
| .platform_settings.empty_mention_waiting = false
| .platform_settings.empty_mention_waiting_need_reply = false
| .platform_settings.ignore_bot_self_message = false
| .platform_settings.ignore_at_all = false
| .provider_settings = (.provider_settings // {})
| .provider_settings.wake_prefix = ""
| .provider_settings.prompt_prefix = (.provider_settings.prompt_prefix // "{{prompt}}")
| .wake_prefix = [""]
| .content_safety = (.content_safety // {})
| .content_safety.internal_keywords = (.content_safety.internal_keywords // {})
| .content_safety.internal_keywords.enable = false
EOF
}

apply_astrbot_no_prefix_wake(){
  local targets=() dst tmp changed=0
  [[ -f "$DATA_DIR/cmd_config.json" ]] && targets+=("$DATA_DIR/cmd_config.json")
  if compgen -G "$DATA_DIR/config/abconf_*.json" >/dev/null; then
    while IFS= read -r -d '' dst; do targets+=("$dst"); done < <(find "$DATA_DIR/config" -maxdepth 1 -type f -name 'abconf_*.json' -print0 | sort -z)
  fi
  (( ${#targets[@]} > 0 )) || { warn "AstrBot config not found: $DATA_DIR/cmd_config.json"; return 0; }
  for dst in "${targets[@]}"; do
    tmp="$INSTALL_PREFIX/$(basename "$dst").no-prefix.json"
    jq "$(astrbot_common_jq_filter)" "$dst" > "$tmp"
    install -m 600 "$tmp" "$dst"
    rm -f "$tmp"
    changed=$((changed+1))
  done
  if container_running "$ASTRBOT_CONTAINER"; then
    docker restart "$ASTRBOT_CONTAINER" >/dev/null
    wait_container "$ASTRBOT_CONTAINER" 180 || { docker logs "$ASTRBOT_CONTAINER" --tail 120 || true; fail "AstrBot failed to restart after no-prefix config."; return 1; }
    wait_astrbot_web 180 || warn "AstrBot WebUI did not return HTTP success after no-prefix config; container is running."
  fi
  success "AstrBot no-prefix/no-mention wake config applied to ${changed} config file(s); wake_prefix=[empty string]"
}

sync_astrbot_platforms(){
  local dst="$DATA_DIR/cmd_config.json" tmp="$INSTALL_PREFIX/cmd_config.platforms.json" platforms_json="[]" count=0
  [[ -f "$dst" ]] || return 0
  if [[ -f "$NAPCAT_INDEX_FILE" ]]; then
    platforms_json="$(
      awk -F'\t' -v base="$ASTRBOT_INTERNAL_WS_PORT" -v token="$ASTRBOT_REVERSE_WS_TOKEN" '
        BEGIN{print "["; first=1}
        NF>=1 && $1!="" {
          name=$1; id=name; sub(/^napcat0*/, "", id); if (id == "") id = NR;
          port=base + id - 1;
          if (!first) print ",";
          first=0;
          printf "{\"id\":\"%s\",\"type\":\"aiocqhttp\",\"enable\":true,\"ws_reverse_host\":\"0.0.0.0\",\"ws_reverse_port\":%d,\"ws_reverse_token\":\"%s\"}", name, port, token
        }
        END{print "]"}' "$NAPCAT_INDEX_FILE"
    )"
    count="$(jq 'length' <<<"$platforms_json")"
  fi
  if (( count == 0 )); then
    platforms_json="[{\"id\":\"napcat01\",\"type\":\"aiocqhttp\",\"enable\":true,\"ws_reverse_host\":\"0.0.0.0\",\"ws_reverse_port\":${ASTRBOT_INTERNAL_WS_PORT},\"ws_reverse_token\":\"${ASTRBOT_REVERSE_WS_TOKEN}\"}]"
  fi
  jq --argjson platforms "$platforms_json" "$(astrbot_common_jq_filter) | .platform = \$platforms" "$dst" > "$tmp"
  install -m 600 "$tmp" "$dst"
  rm -f "$tmp"
  if container_running "$ASTRBOT_CONTAINER"; then
    docker restart "$ASTRBOT_CONTAINER" >/dev/null
    wait_container "$ASTRBOT_CONTAINER" 180 || { docker logs "$ASTRBOT_CONTAINER" --tail 120 || true; fail "AstrBot failed to restart after platform sync."; return 1; }
    wait_astrbot_web 180 || warn "AstrBot WebUI did not return HTTP success after platform sync; container is running."
  fi
  success "AstrBot reverse WebSocket platforms synced; token=${ASTRBOT_REVERSE_WS_TOKEN}"
}

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
  jq --arg token "$ASTRBOT_REVERSE_WS_TOKEN" "$(astrbot_common_jq_filter) | .platform = ((.platform // []) | if length == 0 then [{\"id\":\"napcat01\",\"type\":\"aiocqhttp\",\"enable\":true,\"ws_reverse_host\":\"0.0.0.0\",\"ws_reverse_port\":6199,\"ws_reverse_token\":\$token}] else map(if .type == \"aiocqhttp\" then .ws_reverse_token = \$token else . end) end)" "$src" > "$tmp"
  install -m 600 "$tmp" "$dst"
  rm -f "$tmp"
  if container_running "$ASTRBOT_CONTAINER"; then
    docker restart "$ASTRBOT_CONTAINER" >/dev/null
    wait_container "$ASTRBOT_CONTAINER" 180 || { docker logs "$ASTRBOT_CONTAINER" --tail 120 || true; fail "AstrBot failed to restart after applying config."; exit 1; }
    wait_astrbot_web 180 || warn "AstrBot WebUI did not return HTTP success after restart; container is running."
  fi
  success "AstrBot default config applied: $dst"
}
