#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_DIR/lib/ops.sh"

setup_panel(){
  ensure_dirs
  load_state
  if [[ -z "${WEB_ADMIN_PORT:-}" ]]; then
    WEB_ADMIN_PORT="$(find_free_port 7070)"
    save_state_var WEB_ADMIN_PORT "$WEB_ADMIN_PORT"
  fi
  save_state_var WEB_ADMIN_HOST "${WEB_ADMIN_HOST:-0.0.0.0}"
  save_state_var PROJECT_DIR "$PROJECT_DIR"
  mkdir -p "$INSTALL_PREFIX/uploads" "$INSTALL_PREFIX/logs"
  if systemctl list-unit-files astrbot-deploy-web.service >/dev/null 2>&1; then
    systemctl disable --now astrbot-deploy-web.service >/dev/null 2>&1 || true
  fi
  local unit="/etc/systemd/system/astrbot-deploy-panel.service"
  cat > "$unit" <<EOF
[Unit]
Description=AstrBot-Deploy Enterprise Web Panel
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
Environment=PROJECT_DIR=${PROJECT_DIR}
Environment=INSTALL_PREFIX=${INSTALL_PREFIX}
Environment=STATE_FILE=${STATE_FILE}
Environment=PANEL_CONFIG=${INSTALL_PREFIX}/panel_config.json
ExecStart=/usr/bin/python3 ${PROJECT_DIR}/panel/backend/app.py --host ${WEB_ADMIN_HOST:-0.0.0.0} --port ${WEB_ADMIN_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  local watchdog_unit="/etc/systemd/system/astrbot-napcat-watchdog.service"
  cat > "$watchdog_unit" <<EOF
[Unit]
Description=AstrBot-Deploy NapCat Auto Restart Watchdog
After=docker.service astrbot-deploy-panel.service
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
Environment=PROJECT_DIR=${PROJECT_DIR}
Environment=INSTALL_PREFIX=${INSTALL_PREFIX}
Environment=STATE_FILE=${STATE_FILE}
ExecStart=/usr/bin/env bash ${PROJECT_DIR}/scripts/napcat-watchdog.sh loop
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now astrbot-deploy-panel.service >/dev/null
  systemctl restart astrbot-deploy-panel.service
  systemctl enable --now astrbot-napcat-watchdog.service >/dev/null 2>&1 || true
  local pub; pub="$(public_ip)"
  printf '\033[32m[OK]\033[0m Web 控制台：http://%s:%s/\n' "$pub" "$WEB_ADMIN_PORT"
  if [[ -f "$INSTALL_PREFIX/panel_config.json" ]]; then
    python3 - <<PY
import json
p="$INSTALL_PREFIX/panel_config.json"
d=json.load(open(p,encoding="utf-8"))
print("账号："+d.get("username","admin"))
print("首次密码："+d.get("initial_password","已修改，请使用你设置的密码"))
print("配置文件："+p)
PY
  fi
}

case "${1:-setup}" in
  setup|start) setup_panel ;;
  restart) systemctl restart astrbot-deploy-panel.service ;;
  stop) systemctl stop astrbot-deploy-panel.service ;;
  status) systemctl status astrbot-deploy-panel.service --no-pager || true ;;
  password) python3 - <<PY
import json
p="$INSTALL_PREFIX/panel_config.json"
d=json.load(open(p,encoding="utf-8"))
print(d.get("initial_password","密码已修改；如忘记请编辑 panel_config.json 或重新生成"))
PY
    ;;
  *) echo "Usage: $0 {setup|start|restart|stop|status|password}"; exit 1 ;;
esac
