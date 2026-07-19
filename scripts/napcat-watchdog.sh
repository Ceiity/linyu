#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_DIR/lib/ops.sh"
load_state || true
PANEL_CONFIG="${PANEL_CONFIG:-${INSTALL_PREFIX}/panel_config.json}"
LOG_FILE="${INSTALL_PREFIX}/logs/napcat-watchdog.log"
STATUS_FILE="${INSTALL_PREFIX}/napcat_recovery_status.json"
STATE_DIR="${INSTALL_PREFIX}/logs/napcat-watchdog-state"
mkdir -p "$(dirname "$LOG_FILE")" "$STATE_DIR"

log(){ printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG_FILE" >/dev/null; }
cfg(){ local key="$1" def="$2"; jq -r --arg k "$key" --arg d "$def" 'if has($k) and .[$k] != null and .[$k] != "" then .[$k] else $d end' "$PANEL_CONFIG" 2>/dev/null || printf '%s\n' "$def"; }
now_ts(){ date +%s; }
sha256(){ printf '%s' "$1" | sha256sum | awk '{print $1}'; }

write_status(){
  local tmp="${STATUS_FILE}.tmp"
  if compgen -G "$STATE_DIR/*.status.json" >/dev/null; then
    jq -s --arg updated_at "$(date '+%F %T %Z')" '{updated_at:$updated_at,bots:(map({(.name):.})|add // {})}' "$STATE_DIR"/*.status.json > "$tmp"
  else
    jq -n --arg updated_at "$(date '+%F %T %Z')" '{updated_at:$updated_at,bots:{}}' > "$tmp"
  fi
  mv "$tmp" "$STATUS_FILE"
}

set_bot_status(){
  local name="$1" health="$2" reason="$3" action="$4" abnormal="$5" limited="$6"
  jq -n --arg name "$name" --arg health "$health" --arg reason "$reason" --arg action "$action" --arg updated_at "$(date '+%F %T %Z')" --argjson abnormal "${abnormal:-0}" --argjson limited "${limited:-false}" \
    '{name:$name,health:$health,reason:$reason,action:$action,abnormal_count:$abnormal,limited:$limited,updated_at:$updated_at}' > "$STATE_DIR/${name}.status.json"
}

credential(){
  local name="$1" port="$2" token="$3" force="${4:-false}" hash cache now expires cred res msg
  hash="$(sha256 "${token}.napcat")"; cache="$STATE_DIR/${name}.credential.json"; now="$(now_ts)"
  if [[ "$force" != "true" && -s "$cache" ]]; then
    expires="$(jq -r '.expires // 0' "$cache" 2>/dev/null || echo 0)"
    if [[ "$(jq -r '.hash // ""' "$cache" 2>/dev/null)" == "$hash" && "$expires" =~ ^[0-9]+$ && $expires -gt $((now+60)) ]]; then
      jq -r '.credential' "$cache"; return 0
    fi
  fi
  res="$(curl -fsS --max-time 8 -H 'Content-Type: application/json' -d "{\"hash\":\"${hash}\"}" "http://127.0.0.1:${port}/api/auth/login" 2>/dev/null || true)"
  [[ -n "$res" ]] || return 1
  if [[ "$(jq -r '.code // -1' <<<"$res" 2>/dev/null)" != "0" ]]; then
    msg="$(jq -r '.message // "auth failed"' <<<"$res" 2>/dev/null)"
    log "${name} WebUI auth failed: ${msg}"
    return 1
  fi
  cred="$(jq -r '.data.Credential // empty' <<<"$res" 2>/dev/null)"
  [[ -n "$cred" ]] || return 1
  jq -n --arg hash "$hash" --arg credential "$cred" --argjson expires "$((now+3300))" '{hash:$hash,credential:$credential,expires:$expires}' > "$cache"
  jq -r '.credential' "$cache"
}

napcat_api(){
  local name="$1" port="$2" token="$3" path="$4" cred res code
  cred="$(credential "$name" "$port" "$token" false || true)" || true
  [[ -n "$cred" ]] || return 1
  res="$(curl -sS --max-time 10 -H 'Content-Type: application/json' -H "Authorization: Bearer ${cred}" -d '{}' "http://127.0.0.1:${port}/api/${path#/}" 2>/dev/null || true)"
  code="$(jq -r '.code // -1' <<<"$res" 2>/dev/null || echo -1)"
  if [[ -z "$res" || ( "$code" == "-1" && "$res" == *Unauthorized* ) ]]; then
    rm -f "$STATE_DIR/${name}.credential.json"
    cred="$(credential "$name" "$port" "$token" true || true)"
    [[ -n "$cred" ]] || return 1
    res="$(curl -sS --max-time 10 -H 'Content-Type: application/json' -H "Authorization: Bearer ${cred}" -d '{}' "http://127.0.0.1:${port}/api/${path#/}" 2>/dev/null || true)"
  fi
  [[ -n "$res" ]] || return 1
  printf '%s\n' "$res"
}

recent_restart_count(){
  local file="$1" window="$2" now cutoff
  now="$(now_ts)"; cutoff=$((now-window))
  [[ -f "$file" ]] || { echo 0; return; }
  awk -v c="$cutoff" '$1>=c{print $1}' "$file" > "${file}.tmp" || true
  mv "${file}.tmp" "$file"
  wc -l < "$file" | tr -d ' '
}

recover_bot(){
  local name="$1" webui="$2" token="$3" reason="$4" max="$5" window="$6" wait_s="$7" times count
  times="$STATE_DIR/${name}.restarts"
  count="$(recent_restart_count "$times" "$window")"
  if (( count >= max )); then
    log "${name} ${reason}; recovery limit reached in ${window}s (${max}). Manual handling required."
    set_bot_status "$name" "limited" "QQ may be rate-limited; manual handling required" "auto recovery paused" "$count" true
    return 0
  fi
  date +%s >> "$times"
  log "${name} abnormal: ${reason}; starting auto recovery (${count}/${max})"
  set_bot_status "$name" "recovering" "$reason" "restarting NapCat and preparing QR code" "$count" false
  docker restart "$name" >>"$LOG_FILE" 2>&1 || { log "${name} restart failed"; return 1; }
  sleep "$wait_s"
  napcat_api "$name" "$webui" "$token" "/QQLogin/GetQQLoginQrcode" >/dev/null 2>&1 || true
  set_bot_status "$name" "waiting_qr" "recovered; waiting for QR scan" "new QR code requested" 0 false
}

check_one(){
  local name="$1" webui="$2" ws="$3" http="$4" token="$5" interval="$6" threshold="$7" max="$8" window="$9" wait_s="${10}"
  local reason="" status web_ok api_res is_login logs count_file count
  status="$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo missing)"
  if [[ "$status" != "running" ]]; then reason="container status: ${status}"; fi
  if [[ -z "$reason" ]]; then
    curl -fsS --max-time 4 "http://127.0.0.1:${webui}/webui" >/dev/null 2>&1 && web_ok=true || web_ok=false
    [[ "$web_ok" == true ]] || reason="WebUI not reachable"
  fi
  if [[ -z "$reason" ]]; then
    api_res="$(napcat_api "$name" "$webui" "$token" "/QQLogin/CheckLoginStatus" || true)"
    if [[ -z "$api_res" ]]; then
      reason="login status API not reachable"
    else
      is_login="$(jq -r '.data.isLogin // false' <<<"$api_res" 2>/dev/null || echo false)"
      [[ "$is_login" == "true" ]] || reason="QQ offline or kicked"
    fi
  fi
  logs="$(docker logs --since "$((interval+30))s" "$name" 2>&1 || true)"
  if grep -Eiq 'login.*expired|qrcode.*expired|kick|kicked|offline|logout|session.*expired|expired|QR.*expired' <<<"$logs"; then
    reason="possible QQ kick/offline or QR expired"
  fi
  count_file="$STATE_DIR/${name}.abnormal"
  if [[ -z "$reason" ]]; then
    echo 0 > "$count_file"
    set_bot_status "$name" "online" "normal" "none" 0 false
    return 0
  fi
  count=0; [[ -f "$count_file" ]] && count="$(cat "$count_file" 2>/dev/null || echo 0)"
  [[ "$count" =~ ^[0-9]+$ ]] || count=0
  count=$((count+1)); echo "$count" > "$count_file"
  if (( count < threshold )); then
    set_bot_status "$name" "suspect" "$reason" "waiting for next confirmation" "$count" false
    return 0
  fi
  echo 0 > "$count_file"
  recover_bot "$name" "$webui" "$token" "$reason" "$max" "$window" "$wait_s"
}

check_once(){
  load_state || true
  local idx="${NAPCAT_INDEX_FILE:-${INSTALL_PREFIX}/napcat_index.tsv}" interval threshold max window wait_s enabled name webui ws http token
  enabled="$(cfg napcat_watchdog_enabled true)"
  if [[ "$enabled" == "false" ]]; then
    log "NapCat auto recovery disabled"
    write_status
    return 0
  fi
  interval="$(cfg napcat_watchdog_interval 60)"; threshold="$(cfg napcat_watchdog_abnormal_threshold 2)"
  max="$(cfg napcat_recovery_max 3)"; window="$(cfg napcat_recovery_window 600)"; wait_s="$(cfg napcat_recovery_wait 25)"
  [[ "$interval" =~ ^[0-9]+$ ]] || interval=60
  [[ "$threshold" =~ ^[0-9]+$ ]] || threshold=2
  [[ "$max" =~ ^[0-9]+$ ]] || max=3
  [[ "$window" =~ ^[0-9]+$ ]] || window=600
  [[ "$wait_s" =~ ^[0-9]+$ ]] || wait_s=25
  [[ -f "$idx" ]] || { write_status; return 0; }
  while IFS=$'\t' read -r name webui ws http token; do
    [[ -n "${name:-}" && -n "${webui:-}" && -n "${token:-}" ]] || continue
    check_one "$name" "$webui" "$ws" "$http" "$token" "$interval" "$threshold" "$max" "$window" "$wait_s" || true
  done < "$idx"
  write_status
}

case "${1:-loop}" in
  once) check_once ;;
  loop)
    log "NapCat unified auto recovery watchdog started"
    while true; do
      interval="$(cfg napcat_watchdog_interval 60)"; [[ "$interval" =~ ^[0-9]+$ ]] || interval=60
      check_once
      sleep "$interval"
    done
    ;;
  *) echo "Usage: $0 {loop|once}"; exit 1 ;;
esac
