#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/backup.sh"
all_compose_files(){ find "$COMPOSE_DIR" "$NAPCAT_BASE_DIR" -name docker-compose.yml -type f 2>/dev/null | sort; }
start_all(){ while read -r f; do [[ -n "$f" ]] && compose_up "$f"; done < <(all_compose_files); }
stop_all(){ while read -r f; do [[ -n "$f" ]] && $(compose_cmd) -f "$f" stop; done < <(all_compose_files); }
restart_all(){ while read -r f; do [[ -n "$f" ]] && $(compose_cmd) -f "$f" restart; done < <(all_compose_files); }
update_compose(){ local f="$1"; [[ -f "$f" ]] || { fail "Compose file missing: $f"; return 1; }; compose_pull "$f"; compose_up "$f"; }
update_astrbot(){ update_compose "$COMPOSE_DIR/astrbot/docker-compose.yml"; }
update_napcat(){ find "$NAPCAT_BASE_DIR" -name docker-compose.yml -type f -print0 | while IFS= read -r -d '' f; do update_compose "$f"; done; }
update_all(){ update_astrbot; update_napcat; write_deploy_info; }
status_containers(){ docker ps -a --filter "name=astrbot" --filter "name=napcat" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'; }
docker_status(){ docker version; echo; $(compose_cmd) version; echo; docker system df; }
system_status(){ echo "OS: $(os_pretty)"; uptime; free -h; df -h "$INSTALL_PREFIX"; }
ports_status(){ ss -ltnp 2>/dev/null | grep -E ':(6185|6199|6099|3000|3001|[0-9]+)' || true; }
network_status(){ docker network inspect "$NETWORK_NAME"; }
check_health(){ local ok=0; container_running "$ASTRBOT_CONTAINER" && success "AstrBot container is running" || { fail "AstrBot is not running"; ok=1; }; curl -fsS --max-time 3 "http://127.0.0.1:${ASTRBOT_WEB_PORT:-6185}/" >/dev/null 2>&1 && success "AstrBot WebUI reachable" || warn "AstrBot WebUI not reachable yet"; if [[ -f "$NAPCAT_INDEX_FILE" ]]; then while IFS=$'\t' read -r name webui _rest; do container_running "$name" && success "$name container is running" || { fail "$name is not running"; ok=1; }; curl -fsS --max-time 3 "http://127.0.0.1:${webui}/webui" >/dev/null 2>&1 && success "$name WebUI reachable" || warn "$name WebUI not reachable yet"; done < "$NAPCAT_INDEX_FILE"; fi; docker network inspect "$NETWORK_NAME" >/dev/null && success "Network OK: $NETWORK_NAME" || { fail "Network missing"; ok=1; }; return "$ok"; }
uninstall_all(){ read -r -p $'\u5378\u8f7d\u6a21\u5f0f\uff1a1=\u4fdd\u7559\u6570\u636e 2=\u5b8c\u5168\u5220\u9664\u6570\u636e [1/2]\uff1a' mode || mode=1; stop_all || true; while read -r f; do [[ -n "$f" ]] && $(compose_cmd) -f "$f" down || true; done < <(all_compose_files); read -r -p $'\u662f\u5426\u5220\u9664\u955c\u50cf '"${ASTRBOT_IMAGE}"$' \u548c '"${NAPCAT_IMAGE}"$'\uff1f[y/N]\uff1a' imgs || imgs=n; [[ "$imgs" =~ ^[Yy]$ ]] && docker rmi "$ASTRBOT_IMAGE" "$NAPCAT_IMAGE" || true; docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true; if [[ "$mode" == "2" ]]; then rm -rf -- "$INSTALL_PREFIX"; success "Deleted $INSTALL_PREFIX"; else success "Uninstalled containers and network; data kept in $INSTALL_PREFIX"; fi; }
