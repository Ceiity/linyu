#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_DIR/lib/ops.sh"

setup_web_admin(){
  ensure_dirs
  load_state
  if [[ -z "${WEB_ADMIN_PORT:-}" ]]; then
    WEB_ADMIN_PORT="$(find_free_port 7070)"
    save_state_var WEB_ADMIN_PORT "$WEB_ADMIN_PORT"
  fi
  if [[ -z "${WEB_ADMIN_TOKEN:-}" ]]; then
    WEB_ADMIN_TOKEN="$(random_token)"
    save_state_var WEB_ADMIN_TOKEN "$WEB_ADMIN_TOKEN"
  fi
  save_state_var WEB_ADMIN_HOST "${WEB_ADMIN_HOST:-0.0.0.0}"
  save_state_var PROJECT_DIR "$PROJECT_DIR"
  local unit="/etc/systemd/system/astrbot-deploy-web.service"
  cat > "$unit" <<EOF
[Unit]
Description=AstrBot-Deploy Web Admin
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=/usr/bin/python3 ${PROJECT_DIR}/webadmin/server.py --host ${WEB_ADMIN_HOST:-0.0.0.0} --port ${WEB_ADMIN_PORT} --state ${STATE_FILE}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now astrbot-deploy-web.service >/dev/null 2>&1 || {
    warn "systemd start failed; trying direct background start"
    nohup python3 "$PROJECT_DIR/webadmin/server.py" --host "${WEB_ADMIN_HOST:-0.0.0.0}" --port "$WEB_ADMIN_PORT" --state "$STATE_FILE" >> "$LOG_DIR/web-admin.log" 2>&1 &
  }
  success "Web admin: http://$(public_ip):${WEB_ADMIN_PORT}/  token=${WEB_ADMIN_TOKEN}"
}

case "${1:-setup}" in
  setup) setup_web_admin ;;
  restart) systemctl restart astrbot-deploy-web.service ;;
  status) systemctl status astrbot-deploy-web.service --no-pager || true ;;
  token) load_state; echo "${WEB_ADMIN_TOKEN:-}" ;;
  *) echo "Usage: $0 {setup|restart|status|token}"; exit 1 ;;
esac
