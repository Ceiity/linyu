#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/napcat.sh"
write_deploy_info(){
  load_state
  local pub priv pass token now count
  pub="$(public_ip)"; priv="$(private_ip)"; pass="$(get_astrbot_password)"; token="$(get_astrbot_token)"; now="$(date '+%F %T %Z')"; count="$(get_napcat_count)"
  cat > "$DEPLOY_INFO_FILE" <<EOF
AstrBot-Deploy deployment information
====================================
Public IP: ${pub}
Private IP: ${priv}
OS: $(os_pretty)
Docker version: $(docker --version 2>/dev/null || echo unknown)
Compose version: $($(compose_cmd) version 2>/dev/null | head -n1 || echo unknown)
AstrBot URL: http://${pub}:${ASTRBOT_WEB_PORT:-6185}
AstrBot private URL: http://${priv}:${ASTRBOT_WEB_PORT:-6185}
AstrBot username: ${ASTRBOT_USERNAME}
AstrBot initial random password: ${pass}
Token: ${token}
NapCat count: ${count}
Docker Network: ${NETWORK_NAME}
Deploy time: ${now}
Script version: ${SCRIPT_VERSION}

NapCat instances:
EOF
  if [[ -f "$NAPCAT_INDEX_FILE" ]]; then
    while IFS=$'\t' read -r name webui ws http ntoken; do
      [[ -n "${name:-}" ]] || continue
      cat >> "$DEPLOY_INFO_FILE" <<EOF
- ${name}
  WebUI: http://${pub}:${webui}/webui
  Private WebUI: http://${priv}:${webui}/webui
  WebUI Token: ${ntoken}
  Forward WS port: ${ws}
  HTTP port: ${http}
  Directory: ${NAPCAT_BASE_DIR}/${name}
EOF
    done < "$NAPCAT_INDEX_FILE"
  fi
  chmod 600 "$DEPLOY_INFO_FILE" || true
  success "Deployment info saved: $DEPLOY_INFO_FILE"
}
print_success_summary(){
  load_state; local pub pass token count; pub="$(public_ip)"; pass="$(get_astrbot_password)"; token="$(get_astrbot_token)"; count="$(get_napcat_count)"
  printf '\n%s%sDeployment succeeded%s\n' "$C_BOLD" "$C_GREEN" "$C_RESET"
  printf '%sAstrBot%s\nURL: http://%s:%s\nUsername: %s\nInitial random password: %s\nToken: %s\n' "$C_CYAN" "$C_RESET" "$pub" "${ASTRBOT_WEB_PORT:-6185}" "$ASTRBOT_USERNAME" "$pass" "$token"
  printf '\n%sNapCat%s\nCount: %s\n' "$C_CYAN" "$C_RESET" "$count"
  [[ -f "$NAPCAT_INDEX_FILE" ]] && awk -F'\t' -v ip="$pub" '{printf "%s WebUI: http://%s:%s/webui  token: %s\n",$1,ip,$2,$5}' "$NAPCAT_INDEX_FILE"
  printf '\nInfo file: %s\nManager: bash %s/manager.sh\n' "$DEPLOY_INFO_FILE" "$PROJECT_DIR"
}
