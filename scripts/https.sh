#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_DIR/lib/ops.sh"
trap trap_error ERR

DOMAIN="${HTTPS_DOMAIN:-${1:-}}"
EMAIL="${HTTPS_EMAIL:-${2:-}}"
MODE="${HTTPS_MODE:-panel}"

usage(){
  cat <<EOF
Usage:
  HTTPS_DOMAIN=panel.example.com HTTPS_EMAIL=admin@example.com bash scripts/https.sh
  bash scripts/https.sh panel.example.com admin@example.com

说明：
  - 域名必须提前解析到本服务器公网 IP。
  - 服务器安全组/防火墙必须开放 80 和 443。
  - 默认只给 Web 面板配置 HTTPS。
EOF
}

valid_domain(){
  [[ "$1" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]]
}

ensure_https_deps(){
  step "Installing HTTPS dependencies"
  export DEBIAN_FRONTEND=noninteractive
  wait_apt_locks
  apt-get update -y
  wait_apt_locks
  apt-get install -y nginx snapd ca-certificates curl openssl
  systemctl enable --now nginx >/dev/null 2>&1 || true
  if ! command -v certbot >/dev/null 2>&1; then
    snap install core >/dev/null 2>&1 || true
    snap refresh core >/dev/null 2>&1 || true
    snap install --classic certbot
    ln -sf /snap/bin/certbot /usr/local/bin/certbot
  fi
}

write_nginx_panel(){
  local domain="$1" file="/etc/nginx/sites-available/astrbot-deploy-panel.conf" upstream_host upstream_port
  load_state
  upstream_host="${WEB_ADMIN_UPSTREAM_HOST:-${PANEL_UPSTREAM_HOST:-127.0.0.1}}"
  upstream_port="${WEB_ADMIN_PORT:-7070}"
  cat > "$file" <<EOF
server {
    listen 80;
    server_name ${domain};

    client_max_body_size 512m;

    location / {
        proxy_pass http://${upstream_host}:${upstream_port};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_set_header X-Forwarded-Ssl on;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
EOF
  ln -sf "$file" /etc/nginx/sites-enabled/astrbot-deploy-panel.conf
  nginx -t
  systemctl reload nginx
}

issue_cert(){
  local domain="$1" email="$2"
  step "Issuing Let's Encrypt certificate for ${domain}"
  if [[ -n "$email" ]]; then
    certbot --nginx -d "$domain" --non-interactive --agree-tos -m "$email" --redirect
  else
    certbot --nginx -d "$domain" --non-interactive --agree-tos --register-unsafely-without-email --redirect
  fi
  certbot renew --dry-run
}

main(){
  require_root
  [[ -n "$DOMAIN" ]] || { usage; exit 1; }
  valid_domain "$DOMAIN" || { fail "域名格式不正确：$DOMAIN"; exit 1; }
  ensure_dirs
  ensure_https_deps
  write_nginx_panel "$DOMAIN"
  issue_cert "$DOMAIN" "$EMAIL"
  save_state_var HTTPS_DOMAIN "$DOMAIN"
  save_state_var HTTPS_PANEL_URL "https://${DOMAIN}"
  write_deploy_info || true
  success "HTTPS 已配置：https://${DOMAIN}"
}

main "$@"
