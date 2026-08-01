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
wait_astrbot_web(){
  local timeout="${1:-60}" i code web_port="${ASTRBOT_WEB_PORT:-6185}"
  # AstrBot 新版根路径可能返回 405/403，这代表 Web 服务已经启动。
  # 不能使用 curl -f，否则“免 @ / 免前缀”应用后会误判未就绪并等待到超时。
  for ((i=1;i<=timeout;i++)); do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:${web_port}/" 2>/dev/null || true)"
    [[ "$code" =~ ^[0-9]{3}$ && "$code" != "000" ]] && return 0
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:${web_port}/dashboard" 2>/dev/null || true)"
    [[ "$code" =~ ^[0-9]{3}$ && "$code" != "000" ]] && return 0
    sleep 1
  done
  return 1
}
get_astrbot_password(){
  local pass="" logs
  if [[ -f "$DATA_DIR/cmd_config.json" ]] && jq -e '.dashboard.password_change_required == false' "$DATA_DIR/cmd_config.json" >/dev/null 2>&1; then
    echo "初始密码已被更改"
    return 0
  fi
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
| .platform_settings.rate_limit = (.platform_settings.rate_limit // {})
| .platform_settings.rate_limit.time = 0
| .platform_settings.rate_limit.count = 9999999999
| .platform_settings.rate_limit.strategy = "stall"
| .platform_settings.enable_id_white_list = false
| .platform_settings.id_whitelist = []
| .platform_settings.id_whitelist_log = false
| .platform_settings.wl_ignore_admin_on_group = true
| .platform_settings.wl_ignore_admin_on_friend = true
| .platform_settings.reply_prefix = ""
| .platform_settings.wake_prefix = ""
| .platform_settings.reply_with_mention = false
| .platform_settings.reply_with_quote = false
| .platform_settings.group_message_needs_wake_prefix = false
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

astrbot_effective_compare_filter(){
cat <<'EOF'
del(.platform_settings.group_message_needs_wake_prefix, .platform_settings.wake_prefix)
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
    if jq -S "$(astrbot_effective_compare_filter)" "$tmp" > "${tmp}.new.norm" 2>/dev/null && jq -S "$(astrbot_effective_compare_filter)" "$dst" > "${tmp}.old.norm" 2>/dev/null && cmp -s "${tmp}.new.norm" "${tmp}.old.norm"; then
      rm -f "$tmp" "${tmp}.new.norm" "${tmp}.old.norm"
      continue
    fi
    install -m 600 "$tmp" "$dst"
    rm -f "$tmp" "${tmp}.new.norm" "${tmp}.old.norm"
    changed=$((changed+1))
  done
  if (( changed == 0 )); then
    success "AstrBot no-prefix/no-mention wake config already applied; no restart needed."
    return 0
  fi
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
  if jq -S "$(astrbot_effective_compare_filter)" "$tmp" > "${tmp}.new.norm" 2>/dev/null && jq -S "$(astrbot_effective_compare_filter)" "$dst" > "${tmp}.old.norm" 2>/dev/null && cmp -s "${tmp}.new.norm" "${tmp}.old.norm"; then
    rm -f "$tmp" "${tmp}.new.norm" "${tmp}.old.norm"
    success "AstrBot reverse WebSocket platforms already synced; no restart needed."
    return 0
  fi
  install -m 600 "$tmp" "$dst"
  rm -f "$tmp" "${tmp}.new.norm" "${tmp}.old.norm"
  if container_running "$ASTRBOT_CONTAINER"; then
    docker restart "$ASTRBOT_CONTAINER" >/dev/null
    wait_container "$ASTRBOT_CONTAINER" 180 || { docker logs "$ASTRBOT_CONTAINER" --tail 120 || true; fail "AstrBot failed to restart after platform sync."; return 1; }
    wait_astrbot_web 180 || warn "AstrBot WebUI did not return HTTP success after platform sync; container is running."
  fi
  success "AstrBot reverse WebSocket platforms synced; token=${ASTRBOT_REVERSE_WS_TOKEN}"
}

repair_astrbot_napcat_connection(){
  local name webui rest failed=0 connected=0
  load_state
  step "Repairing AstrBot and NapCat connection"
  ensure_network
  if container_running "$ASTRBOT_CONTAINER"; then
    docker network connect "$NETWORK_NAME" "$ASTRBOT_CONTAINER" >/dev/null 2>&1 || true
  fi
  if [[ -f "$NAPCAT_INDEX_FILE" ]]; then
    while IFS=$'\t' read -r name webui rest; do
      [[ -n "${name:-}" ]] || continue
      docker network connect "$NETWORK_NAME" "$name" >/dev/null 2>&1 || true
      connected=$((connected+1))
    done < "$NAPCAT_INDEX_FILE"
  fi
  # Do not restart NapCat here: network config changes can be applied by NapCat/WebUI,
  # and preserving QQ login state is more important. Only AstrBot needs restart after platform/config changes.
  sync_napcat_reverse_configs
  sync_astrbot_platforms
  write_deploy_info
  (( failed == 0 )) || { warn "Connection repair completed with ${failed} NapCat issue(s)."; return 1; }
  success "Connection repair completed: synced token/reverse WebSocket and connected ${connected} NapCat container(s) to Docker network; NapCat was not restarted, QQ login state preserved."
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

install_linyu_remote_plugin(){
  local src="$PROJECT_DIR/plugins/astrbot_plugin_linyu_remote_admin"
  local dst="$DATA_DIR/plugins/astrbot_plugin_linyu_remote_admin"
  local cfg_dir="$DATA_DIR/config"
  local panel_cfg="$INSTALL_PREFIX/panel_config.json"
  local remote_token server_url plugin_cfg
  [[ -d "$src" ]] || { warn "Linyu remote plugin source not found: $src"; return 0; }
  mkdir -p "$dst" "$cfg_dir"
  cp -a "$src/." "$dst/"
  remote_token="$(
    PANEL_CONFIG_PATH="$panel_cfg" python3 - <<'PY'
import json, os, secrets
path = os.environ["PANEL_CONFIG_PATH"]
data = {}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        data = {}
token = str(data.get("remote_api_token") or "")
if not token:
    token = secrets.token_urlsafe(24)
    data["remote_api_enabled"] = True
    data["remote_api_token"] = token
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
print(token)
PY
  )"
  server_url="http://$(public_ip):${WEB_ADMIN_PORT:-7070}"
  plugin_cfg="$cfg_dir/astrbot_plugin_linyu_remote_admin_config.json"
  cat > "$plugin_cfg" <<JSON
{
  "enabled": true,
  "public_login_enabled": false,
  "server_url": "$server_url",
  "remote_token": "$remote_token",
  "owner_ids": ["${LINYU_REMOTE_OWNER_ID:-3179806299}"],
  "bot_self_ids": ["${LINYU_REMOTE_BOT_SELF_ID:-2141945863}"],
  "allowed_groups": [],
  "triggers": ["申请登录"],
  "cooldown_seconds": 300,
  "qr_retry_seconds": 60
}
JSON
  chmod 600 "$plugin_cfg" || true
  if container_running "$ASTRBOT_CONTAINER"; then
    docker restart "$ASTRBOT_CONTAINER" >/dev/null || true
    wait_container "$ASTRBOT_CONTAINER" 180 || warn "AstrBot did not restart cleanly after plugin install."
  fi
  success "Linyu QQ remote plugin installed: $dst"
}
