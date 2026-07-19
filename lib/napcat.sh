#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/astrbot.sh"
napcat_name(){ local n="$1" width="${NAPCAT_PAD_WIDTH:-2}"; printf "napcat%0${width}d" "$n"; }
max_napcat_id(){ [[ -f "$NAPCAT_INDEX_FILE" ]] || { echo 0; return; }; awk -F'\t' 'BEGIN{m=0} $1 ~ /^napcat[0-9]+$/ {gsub(/^napcat0*/,"",$1); if($1+0>m)m=$1+0} END{print m}' "$NAPCAT_INDEX_FILE"; }
generate_napcat_config(){ local name="$1" dir="$NAPCAT_BASE_DIR/$name" token="$2" astrbot_ws_port="$3"; mkdir -p "$dir/config" "$dir/ntqq" "$dir/logs" "$dir/plugins"; cat > "$dir/config/webui.json" <<EOF
{"host":"0.0.0.0","port":6099,"token":"${token}","loginRate":3}
EOF
cat > "$dir/config/onebot11.json" <<EOF
{"network":{"httpServers":[],"httpClients":[],"websocketServers":[],"websocketClients":[{"name":"AstrBotReverseWs","enable":true,"url":"ws://astrbot:${astrbot_ws_port}/ws","messagePostFormat":"array","reportSelfMessage":false,"reconnectInterval":5000,"token":"${ASTRBOT_REVERSE_WS_TOKEN}","debug":false,"heartInterval":30000}]},"musicSignUrl":"","enableLocalFile2Url":false,"parseMultMsg":false}
EOF
}
generate_napcat_compose(){ local name="$1" webui_port="$2" ws_port="$3" http_port="$4" dir file; dir="$NAPCAT_BASE_DIR/$name"; file="$dir/docker-compose.yml"; cat > "$file" <<EOF
services:
  ${name}:
    image: ${NAPCAT_IMAGE}
    container_name: ${name}
    restart: always
    environment:
      - NAPCAT_UID=1000
      - NAPCAT_GID=1000
      - MODE=astrbot
      - TZ=${DEFAULT_TIMEZONE}
    ports:
      - "${webui_port}:6099"
      - "${ws_port}:3001"
      - "${http_port}:3000"
    volumes:
      - ${DATA_DIR}:/AstrBot/data
      - ${dir}/config:/app/napcat/config
      - ${dir}/plugins:/app/napcat/plugins
      - ${dir}/ntqq:/app/.config/QQ
      - ${dir}/logs:/app/napcat/logs
    networks:
      - ${NETWORK_NAME}
networks:
  ${NETWORK_NAME}:
    external: true
EOF
 echo "$file"; }
append_napcat_index(){ local name="$1" webui="$2" ws="$3" http="$4" token="$5"; touch "$NAPCAT_INDEX_FILE"; grep -vE "^${name}\t" "$NAPCAT_INDEX_FILE" > "${NAPCAT_INDEX_FILE}.tmp" || true; printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$webui" "$ws" "$http" "$token" >> "${NAPCAT_INDEX_FILE}.tmp"; mv "${NAPCAT_INDEX_FILE}.tmp" "$NAPCAT_INDEX_FILE"; }
sync_napcat_reverse_configs(){
  [[ -f "$NAPCAT_INDEX_FILE" ]] || return 0
  local name webui ws http webtoken id astrbot_ws_port dir cfg
  while IFS=$'\t' read -r name webui ws http webtoken; do
    [[ -n "${name:-}" ]] || continue
    id="${name#napcat}"; id="$((10#$id))"
    astrbot_ws_port="$((ASTRBOT_INTERNAL_WS_PORT + id - 1))"
    dir="$NAPCAT_BASE_DIR/$name"
    shopt -s nullglob
    for cfg in "$dir"/config/onebot11*.json; do
      jq --arg url "ws://astrbot:${astrbot_ws_port}/ws" --arg token "$ASTRBOT_REVERSE_WS_TOKEN" '
        .network = (.network // {})
        | .network.websocketClients = (.network.websocketClients // [])
        | if (.network.websocketClients | length) > 0 then
            .network.websocketClients |= map(.url=$url | .token=$token | .enable=true | .messagePostFormat=(.messagePostFormat // "array") | .reportSelfMessage=(.reportSelfMessage // false))
          else
            .network.websocketClients = [{"name":"rws","enable":true,"url":$url,"messagePostFormat":"array","reportSelfMessage":false,"reconnectInterval":30000,"token":$token,"debug":false,"heartInterval":30000}]
          end
      ' "$cfg" > "$cfg.tmp" && mv "$cfg.tmp" "$cfg"
    done
    shopt -u nullglob
  done < "$NAPCAT_INDEX_FILE"
  success "NapCat reverse WebSocket configs synced; token=${ASTRBOT_REVERSE_WS_TOKEN}"
}
add_napcat_instances(){
  local count="$1" start max width i id name token webui ws http file total astrbot_ws_port reserved_ports=""
  [[ "$count" =~ ^[0-9]+$ ]] && (( count > 0 )) || { fail "NapCat count must be a positive integer."; return 1; }
  next_free_unreserved(){
    local base="$1" limit="${2:-3000}" n p
    for ((n=0;n<limit;n++)); do
      p=$((base+n))
      [[ " ${reserved_ports} " == *" ${p} "* ]] && continue
      if ! port_in_use "$p"; then
        reserved_ports="${reserved_ports} ${p}"
        echo "$p"
        return 0
      fi
    done
    return 1
  }
  max="$(max_napcat_id)"; start=$((max+1)); total=$((max+count)); width=2; (( total >= 100 )) && width=${#total}; NAPCAT_PAD_WIDTH="$width"
  for ((i=0;i<count;i++)); do
    id=$((start+i)); name="$(napcat_name "$id")"; token="$(random_token)"
    webui="$(next_free_unreserved $((6099+i*10)))"
    ws="$(next_free_unreserved $((3001+i*10)))"
    http="$(next_free_unreserved $((3000+i*10)))"
    astrbot_ws_port="$((ASTRBOT_INTERNAL_WS_PORT + id - 1))"
    step "Creating ${name}"
    generate_napcat_config "$name" "$token" "$astrbot_ws_port"
    file="$(generate_napcat_compose "$name" "$webui" "$ws" "$http")"
    compose_pull "$file" || warn "${name} image pull failed; trying local cache."
    compose_up "$file"
    wait_container "$name" 180 || { docker logs "$name" --tail 100 || true; fail "${name} failed to start."; return 1; }
    append_napcat_index "$name" "$webui" "$ws" "$http" "$token"
    success "${name}: WebUI http://$(private_ip):${webui}/webui token=${token} reverse_ws=ws://astrbot:${astrbot_ws_port}/ws reverse_token=${ASTRBOT_REVERSE_WS_TOKEN}"
  done
  save_state_var NAPCAT_IMAGE "$NAPCAT_IMAGE"
  sync_napcat_reverse_configs
  sync_astrbot_platforms
}
delete_napcat_instance(){ local name="$1" dir file; dir="$NAPCAT_BASE_DIR/$name"; file="$dir/docker-compose.yml"; [[ -f "$file" ]] || { fail "Instance not found: ${name}"; return 1; }; $(compose_cmd) -f "$file" down || true; read -r -p $'\u662f\u5426\u5220\u9664\u6570\u636e\u76ee\u5f55 '"${dir}"$'\uff1f[y/N]\uff1a' ans || ans="n"; [[ "$ans" =~ ^[Yy]$ ]] && rm -rf -- "$dir"; grep -vE "^${name}\t" "$NAPCAT_INDEX_FILE" > "${NAPCAT_INDEX_FILE}.tmp" || true; mv "${NAPCAT_INDEX_FILE}.tmp" "$NAPCAT_INDEX_FILE"; sync_napcat_reverse_configs; sync_astrbot_platforms; success "Deleted ${name}"; }
list_napcat(){ [[ -f "$NAPCAT_INDEX_FILE" ]] && awk -F'\t' '{printf "%s  WebUI:%s  WS:%s  HTTP:%s\n",$1,$2,$3,$4}' "$NAPCAT_INDEX_FILE" || warn "No NapCat instances."; }
get_napcat_count(){ [[ -f "$NAPCAT_INDEX_FILE" ]] && wc -l < "$NAPCAT_INDEX_FILE" | tr -d ' ' || echo 0; }
