#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_DIR/lib/ops.sh"
trap trap_error ERR

TARGET="${HTTPS_TARGET:-${HTTPS_DOMAIN:-}}"
EMAIL="${HTTPS_EMAIL:-}"
TARGET_KIND="${HTTPS_TARGET_KIND:-auto}"
ACME_ROOT="${HTTPS_ACME_ROOT:-/var/www/nailong-acme}"
NGINX_SITE="/etc/nginx/sites-available/astrbot-deploy-panel.conf"
CERTBOT_BIN=""

usage(){
  cat <<'EOF'
用法：
  # 无域名：自动识别本机公网 IPv4，一键申请 IP HTTPS
  sudo bash scripts/https.sh --ip

  # 有域名：保留传统域名 HTTPS
  sudo bash scripts/https.sh --domain panel.example.com --email admin@example.com

兼容旧用法：
  sudo bash scripts/https.sh panel.example.com admin@example.com

环境变量：
  HTTPS_IP=1 / HTTPS_TARGET_KIND=ip    强制使用公网 IP
  HTTPS_TARGET=1.2.3.4                 指定公网 IP
  HTTPS_EMAIL=admin@example.com        可选证书联系邮箱

要求：云厂商安全组必须放行 TCP 80 和 443；公网 IP 必须固定并指向本机。
EOF
}

parse_args(){
  while (( $# > 0 )); do
    case "$1" in
      --ip) TARGET_KIND="ip"; shift ;;
      --domain)
        [[ $# -ge 2 ]] || { fail "--domain 后缺少域名"; exit 2; }
        TARGET_KIND="domain"; TARGET="$2"; shift 2 ;;
      --email)
        [[ $# -ge 2 ]] || { fail "--email 后缺少邮箱"; exit 2; }
        EMAIL="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      --*) fail "未知参数：$1"; usage; exit 2 ;;
      *)
        if [[ -z "$TARGET" ]]; then TARGET="$1"; else EMAIL="${EMAIL:-$1}"; fi
        shift ;;
    esac
  done
  if [[ "${HTTPS_IP:-0}" == "1" ]]; then
    TARGET_KIND="ip"
  fi
  return 0
}

valid_domain(){
  [[ "$1" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]]
}

valid_public_ipv4(){
  python3 - "$1" <<'PY' >/dev/null 2>&1
import ipaddress, sys
ip = ipaddress.ip_address(sys.argv[1])
raise SystemExit(0 if ip.version == 4 and ip.is_global else 1)
PY
}

resolve_target(){
  if [[ "$TARGET_KIND" == "ip" && -z "$TARGET" ]]; then
    TARGET="$(public_ip)"
  fi
  if [[ "$TARGET_KIND" == "auto" ]]; then
    if [[ -z "$TARGET" ]]; then
      TARGET_KIND="ip"
      TARGET="$(public_ip)"
    elif valid_public_ipv4 "$TARGET"; then
      TARGET_KIND="ip"
    else
      TARGET_KIND="domain"
    fi
  fi
  if [[ "$TARGET_KIND" == "ip" ]]; then
    valid_public_ipv4 "$TARGET" || { fail "没有检测到可签发证书的公网 IPv4：${TARGET:-空}"; exit 1; }
  else
    valid_domain "$TARGET" || { fail "域名格式不正确：${TARGET:-空}"; exit 1; }
  fi
}

certbot_is_new_enough(){
  local bin="$1" version
  [[ -x "$bin" ]] || return 1
  version="$($bin --version 2>/dev/null | awk '{print $2}')"
  [[ -n "$version" && "$(printf '%s\n' 5.4 "$version" | sort -V | head -n1)" == "5.4" ]]
}

ensure_https_deps(){
  step "安装 Nginx 与 HTTPS 组件"
  export DEBIAN_FRONTEND=noninteractive
  wait_apt_locks
  apt-get update -y
  wait_apt_locks
  apt-get install -y nginx snapd ca-certificates curl openssl python3
  systemctl enable --now snapd.socket >/dev/null 2>&1 || true
  systemctl enable --now nginx >/dev/null 2>&1 || true

  if certbot_is_new_enough /snap/bin/certbot; then
    CERTBOT_BIN="/snap/bin/certbot"
  elif command -v certbot >/dev/null 2>&1 && certbot_is_new_enough "$(command -v certbot)"; then
    CERTBOT_BIN="$(command -v certbot)"
  else
    snap install core >/dev/null 2>&1 || true
    snap refresh core >/dev/null 2>&1 || true
    if snap list certbot >/dev/null 2>&1; then snap refresh certbot; else snap install --classic certbot; fi
    CERTBOT_BIN="/snap/bin/certbot"
    certbot_is_new_enough "$CERTBOT_BIN" || { fail "IP 证书需要 Certbot 5.4 或更高版本"; exit 1; }
  fi
  ln -sf "$CERTBOT_BIN" /usr/local/bin/certbot
  mkdir -p "$ACME_ROOT" /etc/nginx/sites-available /etc/nginx/sites-enabled
}

panel_upstream(){
  load_state
  printf '%s:%s' "${WEB_ADMIN_UPSTREAM_HOST:-${PANEL_UPSTREAM_HOST:-127.0.0.1}}" "${WEB_ADMIN_PORT:-7070}"
}

write_http_bootstrap(){
  local upstream
  upstream="$(panel_upstream)"
  cat > "$NGINX_SITE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${TARGET};
    client_max_body_size 512m;

    location ^~ /.well-known/acme-challenge/ {
        root ${ACME_ROOT};
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        proxy_pass http://${upstream};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
EOF
  ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/astrbot-deploy-panel.conf
  nginx -t
  systemctl reload nginx
}

issue_certificate(){
  local contact_args=() cert_path="/etc/letsencrypt/live/${TARGET}/fullchain.pem"
  if [[ -n "$EMAIL" ]]; then
    contact_args=(--email "$EMAIL")
  else
    contact_args=(--register-unsafely-without-email)
  fi
  if [[ -s "$cert_path" ]] && openssl x509 -checkend 86400 -noout -in "$cert_path" >/dev/null 2>&1; then
    info "现有证书仍然有效，跳过重复签发。"
    return 0
  fi

  step "为 ${TARGET} 申请 Let's Encrypt 证书"
  if [[ "$TARGET_KIND" == "ip" ]]; then
    "$CERTBOT_BIN" certonly --non-interactive --agree-tos "${contact_args[@]}" \
      --preferred-profile shortlived --webroot --webroot-path "$ACME_ROOT" \
      --ip-address "$TARGET" --cert-name "$TARGET"
  else
    "$CERTBOT_BIN" certonly --non-interactive --agree-tos "${contact_args[@]}" \
      --webroot --webroot-path "$ACME_ROOT" -d "$TARGET" --cert-name "$TARGET"
  fi
  [[ -s "$cert_path" ]] || { fail "证书已申请但文件不存在：$cert_path"; exit 1; }
}

management_web_ports(){
  load_state
  printf '%s\n' "${WEB_ADMIN_PORT:-7070}"
  [[ -n "${ASTRBOT_WEB_PORT:-}" ]] && printf '%s\n' "$ASTRBOT_WEB_PORT"
  if [[ -f "${NAPCAT_INDEX_FILE:-$INSTALL_PREFIX/napcat_index.tsv}" ]]; then
    awk -F'\t' 'NF >= 2 && $2 ~ /^[0-9]+$/ {print $2}' "${NAPCAT_INDEX_FILE:-$INSTALL_PREFIX/napcat_index.tsv}"
  fi
}

bind_compose_web_to_loopback(){
  local file="$1" container_port="$2" changed
  [[ -f "$file" ]] || return 0
  changed="$(python3 - "$file" "$container_port" <<'PY'
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
container_port = re.escape(sys.argv[2])
text = path.read_text(encoding="utf-8")
pattern = re.compile(r'(?m)^(\s*-\s*")(?P<host>[0-9]+):' + container_port + r'"\s*$')
new, count = pattern.subn(lambda m: f'{m.group(1)}127.0.0.1:{m.group("host")}:{sys.argv[2]}"', text)
if count:
    path.write_text(new, encoding="utf-8")
print(1 if count else 0)
PY
)"
  if [[ "$changed" == "1" ]]; then
    compose_up "$file"
  fi
}

harden_existing_web_bindings(){
  load_state
  command -v docker >/dev/null 2>&1 || return 0
  bind_compose_web_to_loopback "$COMPOSE_DIR/astrbot/docker-compose.yml" 6185
  if [[ -d "$NAPCAT_BASE_DIR" ]]; then
    while IFS= read -r file; do
      bind_compose_web_to_loopback "$file" 6099
    done < <(find "$NAPCAT_BASE_DIR" -mindepth 2 -maxdepth 2 -type f -name docker-compose.yml -print 2>/dev/null | sort)
  fi
}

append_port_gateway(){
  local port="$1" bind_ip="$2" cert_dir="/etc/letsencrypt/live/${TARGET}"
  [[ "$port" =~ ^[0-9]+$ ]] || return 0
  (( port > 0 && port < 65536 )) || return 0
  [[ "$port" != "80" && "$port" != "443" ]] || return 0
  cat >> "$NGINX_SITE" <<EOF

server {
    listen ${bind_ip}:${port} ssl http2;
    server_name ${TARGET};
    client_max_body_size 512m;

    ssl_certificate ${cert_dir}/fullchain.pem;
    ssl_certificate_key ${cert_dir}/privkey.pem;
    ssl_session_cache shared:NAILONG_TLS:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;
    ssl_protocols TLSv1.2 TLSv1.3;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;

    location / {
        proxy_pass http://127.0.0.1:${port};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
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
}

write_tls_gateway(){
  local upstream cert_dir="/etc/letsencrypt/live/${TARGET}" bind_ip port
  upstream="$(panel_upstream)"
  cat > "$NGINX_SITE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${TARGET};

    location ^~ /.well-known/acme-challenge/ {
        root ${ACME_ROOT};
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        return 308 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${TARGET};
    client_max_body_size 512m;

    ssl_certificate ${cert_dir}/fullchain.pem;
    ssl_certificate_key ${cert_dir}/privkey.pem;
    ssl_session_cache shared:NAILONG_TLS:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;
    ssl_protocols TLSv1.2 TLSv1.3;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "same-origin" always;

    location / {
        proxy_pass http://${upstream};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port 443;
        proxy_set_header X-Forwarded-Ssl on;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
EOF
  bind_ip="$(private_ip)"
  while IFS= read -r port; do
    append_port_gateway "$port" "$bind_ip"
  done < <(management_web_ports | awk '!seen[$0]++')
  nginx -t
  systemctl reload nginx
}

configure_renewal(){
  cat > /etc/systemd/system/nailong-certbot-renew.service <<EOF
[Unit]
Description=Renew Nailong Let's Encrypt certificates
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=${CERTBOT_BIN} renew --quiet --deploy-hook "systemctl reload nginx"
EOF
  cat > /etc/systemd/system/nailong-certbot-renew.timer <<'EOF'
[Unit]
Description=Check Nailong HTTPS certificate renewal twice daily

[Timer]
OnCalendar=*-*-* 03,15:17:00
RandomizedDelaySec=30m
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now nailong-certbot-renew.timer >/dev/null
}

configure_firewall(){
  local port
  if command -v ufw >/dev/null 2>&1 && ufw status | head -n1 | grep -qi active; then
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
    while IFS= read -r port; do
      [[ "$port" =~ ^[0-9]+$ ]] && ufw allow "${port}/tcp" >/dev/null
    done < <(management_web_ports | awk '!seen[$0]++')
  fi
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-service=http >/dev/null
    firewall-cmd --permanent --add-service=https >/dev/null
    while IFS= read -r port; do
      [[ "$port" =~ ^[0-9]+$ ]] && firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null
    done < <(management_web_ports | awk '!seen[$0]++')
    firewall-cmd --reload >/dev/null
  fi
}

lock_panel_to_loopback(){
  local upstream_host="${WEB_ADMIN_UPSTREAM_HOST:-${PANEL_UPSTREAM_HOST:-127.0.0.1}}"
  [[ "$upstream_host" == "127.0.0.1" ]] || return 0
  save_state_var WEB_ADMIN_HOST 127.0.0.1
  bash "$PROJECT_DIR/scripts/panel.sh" setup >/dev/null
}

main(){
  require_root
  parse_args "$@"
  ensure_dirs
  resolve_target
  ensure_https_deps
  write_http_bootstrap
  issue_certificate
  lock_panel_to_loopback
  harden_existing_web_bindings
  write_tls_gateway
  configure_renewal
  configure_firewall

  save_state_var HTTPS_DOMAIN "$TARGET"
  save_state_var HTTPS_IDENTIFIER "$TARGET"
  save_state_var HTTPS_TARGET_KIND "$TARGET_KIND"
  save_state_var HTTPS_PANEL_URL "https://${TARGET}"
  write_deploy_info || true
  success "HTTPS 已配置：https://${TARGET}"
  info "面板、AstrBot WebUI 与 NapCat WebUI 已统一使用同一张 HTTPS 证书；真实 HTTP 服务仅监听 127.0.0.1。"
}

main "$@"
