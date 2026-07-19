#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_DIR/lib/ops.sh"
LOG_FILE="${INSTALL_PREFIX:-/opt/astrbot}/logs/napcat-watchdog.log"
COOLDOWN_SECONDS="${NAPCAT_WATCHDOG_COOLDOWN:-180}"
INTERVAL_SECONDS="${NAPCAT_WATCHDOG_INTERVAL:-30}"
mkdir -p "$(dirname "$LOG_FILE")"
log(){ printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG_FILE" >/dev/null; }
restart_bot(){
  local name="$1" reason="$2" stamp_file="${INSTALL_PREFIX}/logs/.watchdog-${name}.stamp" now last=0
  now="$(date +%s)"
  [[ -f "$stamp_file" ]] && last="$(cat "$stamp_file" 2>/dev/null || echo 0)"
  if (( now - last < COOLDOWN_SECONDS )); then
    log "${name} 触发 ${reason}，但仍在冷却期，暂不重复重启"
    return 0
  fi
  echo "$now" > "$stamp_file"
  log "检测到 ${name} ${reason}，开始自动重启"
  docker restart "$name" >>"$LOG_FILE" 2>&1 || log "${name} 重启失败"
}
check_once(){
  load_state || true
  local idx="${NAPCAT_INDEX_FILE:-${INSTALL_PREFIX}/napcat_index.tsv}" name line status logs
  [[ -f "$idx" ]] || return 0
  while IFS=$'\t' read -r name _; do
    [[ -n "${name:-}" ]] || continue
    status="$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo missing)"
    if [[ "$status" != "running" ]]; then
      restart_bot "$name" "容器状态为 ${status}"
      continue
    fi
    logs="$(docker logs --since 90s "$name" 2>&1 || true)"
    if grep -Eiq '被踢|踢下线|下线|掉线|登录过期|扫码.*过期|二维码.*过期|账号.*其他.*登录|login.*expired|qrcode.*expired|kick|kicked|offline|logout|session.*expired' <<<"$logs"; then
      restart_bot "$name" "疑似 QQ 被踢下线或登录过期"
    fi
  done < "$idx"
}
case "${1:-loop}" in
  once) check_once ;;
  loop) log "NapCat 自动守护已启动；间隔 ${INTERVAL_SECONDS}s，冷却 ${COOLDOWN_SECONDS}s"; while true; do check_once; sleep "$INTERVAL_SECONDS"; done ;;
  *) echo "Usage: $0 {loop|once}"; exit 1 ;;
esac
