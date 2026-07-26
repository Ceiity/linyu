#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker.sh"

install_fail2ban(){
  step "Installing and configuring Fail2Ban for SSH protection"
  export DEBIAN_FRONTEND=noninteractive
  wait_apt_locks
  apt-get update -y
  wait_apt_locks
  apt-get install -y fail2ban

  mkdir -p /etc/fail2ban/jail.d
  cat > /etc/fail2ban/jail.d/astrbot-deploy-sshd.local <<'EOF'
[sshd]
enabled = true
port = ssh
filter = sshd
backend = systemd
maxretry = 5
findtime = 10m
bantime = 24h
ignoreip = 127.0.0.1/8 ::1
EOF

  systemctl enable fail2ban >/dev/null 2>&1 || true
  systemctl restart fail2ban
  sleep 2
  if systemctl is-active --quiet fail2ban; then
    success "Fail2Ban is active; SSH jail enabled."
    fail2ban-client status sshd 2>/dev/null || true
  else
    fail "Fail2Ban failed to start. Inspect: journalctl -u fail2ban"
    return 1
  fi
}

fail2ban_status(){
  if ! command -v fail2ban-client >/dev/null 2>&1; then
    warn "Fail2Ban is not installed."
    return 1
  fi
  systemctl status fail2ban --no-pager || true
  echo
  fail2ban-client status || true
  echo
  fail2ban-client status sshd 2>/dev/null || true
}
