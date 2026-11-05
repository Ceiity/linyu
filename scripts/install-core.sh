#!/usr/bin/env bash
set -Eeuo pipefail
THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$THIS_DIR/.." && pwd)"
source "$PROJECT_DIR/lib/ops.sh"
trap trap_error ERR
banner(){ printf '%s\n' "${C_MAGENTA}${C_BOLD}AstrBot-Deploy${C_RESET} - Docker one-click deployment for AstrBot + NapCat"; }
maybe_enable_ip_https(){
  [[ "${NAILONG_AUTO_IP_HTTPS:-1}" == "1" ]] || return 0
  step "自动开启公网 IP HTTPS"
  if bash "$PROJECT_DIR/scripts/https.sh" --ip; then
    load_state
    success "公网 IP HTTPS 已开启：${HTTPS_PANEL_URL:-https://$(public_ip)}"
  else
    warn "IP HTTPS 暂未开启。请确认云安全组已放行 TCP 80/443，然后执行：sudo bash $PROJECT_DIR/scripts/https.sh --ip"
  fi
}
install_panel_first(){
  bash "$PROJECT_DIR/scripts/panel.sh" setup
  maybe_enable_ip_https
  write_deploy_info || true
  local pub panel_user panel_pass panel_url
  pub="$(public_ip)"
  panel_url="${HTTPS_PANEL_URL:-http://${pub}:${WEB_ADMIN_PORT:-7070}}"
  panel_user="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1],encoding="utf-8")); print(d.get("username","nailong"))' "$INSTALL_PREFIX/panel_config.json" 2>/dev/null || echo nailong)"
  panel_pass="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1],encoding="utf-8")); print(d.get("initial_password","password changed"))' "$INSTALL_PREFIX/panel_config.json" 2>/dev/null || echo "see /opt/astrbot/panel_config.json")"
  printf '\n%s%sWeb 控制台已启动%s\n' "$C_BOLD" "$C_GREEN" "$C_RESET"
  printf '地址：%s/\n账号：%s\n密码：%s\n' "$panel_url" "$panel_user" "$panel_pass"
  printf '\n现在请打开网页，在「仪表盘」里点击「初始化部署」，填写 NapCat 数量后开始部署。\n'
}
install_full_stack(){
  load_state
  : "${ASTRBOT_WEB_PORT:=$(find_free_port 6185)}"; : "${ASTRBOT_WS_PORT:=$(find_free_port 6199)}"; save_state_var ASTRBOT_WEB_PORT "$ASTRBOT_WEB_PORT"; save_state_var ASTRBOT_WS_PORT "$ASTRBOT_WS_PORT"
  local napcat_count; if [[ -n "${NAPCAT_COUNT:-}" ]]; then napcat_count="$NAPCAT_COUNT"; else read -r -p $'\u8bf7\u8f93\u5165 NapCat \u6570\u91cf\uff1a' napcat_count; fi; [[ -n "$napcat_count" ]] || napcat_count=1
  deploy_astrbot
  apply_astrbot_default_config
  install_nailong_remote_plugin
  add_napcat_instances "$napcat_count"
  bash "$PROJECT_DIR/scripts/web-admin.sh" setup
  maybe_enable_ip_https
  step "Running health checks"; retry 3 5 check_health || warn "Some health checks failed; inspect logs."
  write_deploy_info
  print_success_summary
}
main(){
  banner; require_root; ensure_dirs; save_state_var PROJECT_DIR "$PROJECT_DIR"; save_state_var INSTALL_PREFIX "$INSTALL_PREFIX"; save_state_var NETWORK_NAME "$NETWORK_NAME"; save_state_var SCRIPT_VERSION "$SCRIPT_VERSION"
  step "Environment checks"; validate_os; validate_arch; network_check
  install_dependencies; install_docker; install_fail2ban || warn "Fail2Ban setup failed; continuing deployment."; ensure_network
  load_state
  : "${WEB_ADMIN_PORT:=$(find_free_port 7070)}"; save_state_var WEB_ADMIN_PORT "$WEB_ADMIN_PORT"
  if [[ "${ASTRBOT_DEPLOY_FULL:-0}" == "1" || "${ASTRBOT_DEPLOY_MODE:-panel}" == "full" ]]; then
    install_full_stack
  else
    install_panel_first
  fi
}
main "$@"
