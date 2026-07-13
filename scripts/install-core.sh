#!/usr/bin/env bash
set -Eeuo pipefail
THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$THIS_DIR/.." && pwd)"
source "$PROJECT_DIR/lib/deploy_info.sh"
trap trap_error ERR
banner(){ printf '%s\n' "${C_MAGENTA}${C_BOLD}AstrBot-Deploy${C_RESET} - Docker one-click deployment for AstrBot + NapCat"; }
main(){
  banner; require_root; ensure_dirs; save_state_var PROJECT_DIR "$PROJECT_DIR"; save_state_var INSTALL_PREFIX "$INSTALL_PREFIX"; save_state_var NETWORK_NAME "$NETWORK_NAME"; save_state_var SCRIPT_VERSION "$SCRIPT_VERSION"
  step "Environment checks"; validate_os; validate_arch; network_check
  install_dependencies; install_docker; ensure_network
  load_state
  : "${ASTRBOT_WEB_PORT:=$(find_free_port 6185)}"; : "${ASTRBOT_WS_PORT:=$(find_free_port 6199)}"; save_state_var ASTRBOT_WEB_PORT "$ASTRBOT_WEB_PORT"; save_state_var ASTRBOT_WS_PORT "$ASTRBOT_WS_PORT"
  local napcat_count; if [[ -n "${NAPCAT_COUNT:-}" ]]; then napcat_count="$NAPCAT_COUNT"; else read -r -p "Enter NapCat instance count: " napcat_count; fi; [[ -n "$napcat_count" ]] || napcat_count=1
  deploy_astrbot
  add_napcat_instances "$napcat_count"
  step "Running health checks"; retry 3 5 check_health || warn "Some health checks failed; inspect logs."
  write_deploy_info
  print_success_summary
}
main "$@"
