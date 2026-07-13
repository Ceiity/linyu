#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/colors.sh"
mkdir -p "${LOG_DIR:-/opt/astrbot/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR:-/opt/astrbot/logs}/astrbot-deploy.log}"
touch "$LOG_FILE" 2>/dev/null || true
_log(){ local level="$1" color="$2"; shift 2; local msg="$*"; printf '%s[%s]%s %s\n' "$color" "$level" "$C_RESET" "$msg"; printf '[%s] %s %s\n' "$level" "$(date '+%F %T')" "$msg" >> "$LOG_FILE" 2>/dev/null || true; }
info(){ _log INFO "$C_CYAN" "$@"; }
success(){ _log OK "$C_GREEN" "$@"; }
warn(){ _log WARN "$C_YELLOW" "$@"; }
fail(){ _log FAIL "$C_RED" "$@"; }
step(){ printf '\n%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$*"; printf '[STEP] %s %s\n' "$(date '+%F %T')" "$*" >> "$LOG_FILE" 2>/dev/null || true; }
trap_error(){ local code=$? line=${BASH_LINENO[0]:-0} cmd=${BASH_COMMAND:-}; fail "Command failed: $cmd (exit $code, line $line)"; fail "Log file: $LOG_FILE"; exit "$code"; }
