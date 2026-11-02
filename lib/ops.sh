#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/backup.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/security.sh"
# Every compose file, including the inactive protocol end of each slot (used by stop/down).
every_compose_file(){ find "$COMPOSE_DIR" "$NAPCAT_BASE_DIR" "${SNOWLUMA_BASE_DIR:-$INSTALL_PREFIX/snowluma}" -name docker-compose.yml -type f 2>/dev/null | sort; }
# Compose files that may be started: AstrBot, plus only the ACTIVE protocol end of each
# slot. Starting both NapCat and SnowLuma for one slot would make them fight over the account.
all_compose_files(){
  local f dir slot
  while read -r f; do
    [[ -n "$f" ]] || continue
    dir="$(dirname "$f")"
    case "$dir" in
      "$NAPCAT_BASE_DIR"/*) [[ "$(slot_protocol "$(basename "$dir")")" == "napcat" ]] || continue ;;
      "${SNOWLUMA_BASE_DIR:-$INSTALL_PREFIX/snowluma}"/*) slot="$(snowluma_dir_slot "$dir")"; [[ -n "$slot" && "$(slot_protocol "$slot")" == "snowluma" ]] || continue ;;
    esac
    printf '%s\n' "$f"
  done < <(every_compose_file)
}
start_all(){ while read -r f; do [[ -n "$f" ]] && compose_up "$f"; done < <(all_compose_files); }
stop_all(){ while read -r f; do [[ -n "$f" ]] && $(compose_cmd) -f "$f" stop; done < <(every_compose_file); }
restart_all(){ while read -r f; do [[ -n "$f" ]] && $(compose_cmd) -f "$f" restart; done < <(all_compose_files); }
update_compose(){ local f="$1"; [[ -f "$f" ]] || { fail "Compose file missing: $f"; return 1; }; compose_pull "$f"; compose_up "$f"; }
update_astrbot(){ update_compose "$COMPOSE_DIR/astrbot/docker-compose.yml"; }
update_napcat(){
  # Pull for every NapCat, but only recreate/start the ones that are the active protocol end.
  find "$NAPCAT_BASE_DIR" -name docker-compose.yml -type f -print0 | while IFS= read -r -d '' f; do
    if [[ "$(slot_protocol "$(basename "$(dirname "$f")")")" == "napcat" ]]; then update_compose "$f"; else compose_pull "$f" || true; info "$(basename "$(dirname "$f")") uses SnowLuma; NapCat image pulled but not started"; fi
  done
}
update_all(){ update_astrbot; update_napcat; write_deploy_info; }
status_containers(){ docker ps -a --filter "name=astrbot" --filter "name=napcat" --filter "name=snowluma" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'; }
docker_status(){ docker version; echo; $(compose_cmd) version; echo; docker system df; }
system_status(){ echo "OS: $(os_pretty)"; uptime; free -h; df -h "$INSTALL_PREFIX"; }
ports_status(){ ss -ltnp 2>/dev/null | grep -E ':(6185|6199|6099|3000|3001|[0-9]+)' || true; }
network_status(){ docker network inspect "$NETWORK_NAME"; }
check_health(){ local ok=0; container_running "$ASTRBOT_CONTAINER" && success "AstrBot container is running" || { fail "AstrBot is not running"; ok=1; }; curl -fsS --max-time 3 "http://127.0.0.1:${ASTRBOT_WEB_PORT:-6185}/" >/dev/null 2>&1 && success "AstrBot WebUI reachable" || warn "AstrBot WebUI not reachable yet"; if [[ -f "$NAPCAT_INDEX_FILE" ]]; then while IFS=$'\t' read -r name webui _rest; do [[ "$(slot_protocol "$name")" == "napcat" ]] || { info "$name uses SnowLuma; NapCat check skipped"; continue; }; container_running "$name" && success "$name container is running" || { fail "$name is not running"; ok=1; }; curl -fsS --max-time 3 "http://127.0.0.1:${webui}/webui" >/dev/null 2>&1 && success "$name WebUI reachable" || warn "$name WebUI not reachable yet"; done < "$NAPCAT_INDEX_FILE"; fi; docker network inspect "$NETWORK_NAME" >/dev/null && success "Network OK: $NETWORK_NAME" || { fail "Network missing"; ok=1; }; return "$ok"; }
uninstall_all(){ read -r -p $'\u5378\u8f7d\u6a21\u5f0f\uff1a1=\u4fdd\u7559\u6570\u636e 2=\u5b8c\u5168\u5220\u9664\u6570\u636e [1/2]\uff1a' mode || mode=1; stop_all || true; while read -r f; do [[ -n "$f" ]] && $(compose_cmd) -f "$f" down || true; done < <(every_compose_file); read -r -p $'\u662f\u5426\u5220\u9664\u955c\u50cf '"${ASTRBOT_IMAGE}"$' \u548c '"${NAPCAT_IMAGE}"$'\uff1f[y/N]\uff1a' imgs || imgs=n; [[ "$imgs" =~ ^[Yy]$ ]] && docker rmi "$ASTRBOT_IMAGE" "$NAPCAT_IMAGE" || true; docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true; if [[ "$mode" == "2" ]]; then rm -rf -- "$INSTALL_PREFIX"; success "Deleted $INSTALL_PREFIX"; else success "Uninstalled containers and network; data kept in $INSTALL_PREFIX"; fi; }
