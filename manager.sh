#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$PROJECT_DIR/lib/ops.sh"
trap trap_error ERR
load_state
menu(){ cat <<'EOF'

====== AstrBot-Deploy Manager ======
1) Show deployment info
2) Update AstrBot
3) Update NapCat
4) Update all
5) Add NapCat
6) Delete NapCat
7) View logs
8) Container status
9) Docker status
10) System status
11) Ports
12) Network
13) Restart AstrBot
14) Restart NapCat
15) Restart all
16) Stop all
17) Start all
18) Backup
19) Restore
20) Health check
21) One-click upgrade
22) Uninstall
0) Exit
EOF
}
while true; do
  menu; read -r -p "Select: " c || c=0
  case "$c" in
    1) cat "$DEPLOY_INFO_FILE" 2>/dev/null || warn "Deployment info not found";;
    2) update_astrbot; write_deploy_info;;
    3) update_napcat; write_deploy_info;;
    4) update_all;;
    5) read -r -p "NapCat count to add: " n; add_napcat_instances "$n"; write_deploy_info;;
    6) list_napcat; read -r -p "Instance name to delete: " n; delete_napcat_instance "$n"; write_deploy_info;;
    7) read -r -p "Container name (empty=astrbot): " n; n="${n:-astrbot}"; docker logs -f --tail 200 "$n";;
    8) status_containers;;
    9) docker_status;;
    10) system_status;;
    11) ports_status;;
    12) network_status;;
    13) docker restart "$ASTRBOT_CONTAINER";;
    14) list_napcat; read -r -p "NapCat instance (empty=all): " n; if [[ -z "$n" ]]; then while IFS=$'\t' read -r name _; do docker restart "$name"; done < "$NAPCAT_INDEX_FILE"; else docker restart "$n"; fi;;
    15) restart_all;;
    16) stop_all;;
    17) start_all;;
    18) backup_all;;
    19) restore_backup;;
    20) check_health;;
    21) update_all;;
    22) uninstall_all; exit 0;;
    0) exit 0;;
    *) warn "Invalid choice";;
  esac
done
