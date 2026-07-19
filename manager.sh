#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$PROJECT_DIR/lib/ops.sh"
trap trap_error ERR
load_state
menu(){
  printf '%b\n' ""
  printf '%b\n' "====== AstrBot-Deploy \u7ba1\u7406\u83dc\u5355 ======" \
    "1) \u67e5\u770b\u90e8\u7f72\u4fe1\u606f" \
    "2) \u66f4\u65b0 AstrBot" \
    "3) \u66f4\u65b0 NapCat" \
    "4) \u66f4\u65b0\u5168\u90e8" \
    "5) \u65b0\u589e NapCat" \
    "6) \u5220\u9664 NapCat" \
    "7) \u67e5\u770b\u65e5\u5fd7" \
    "8) \u67e5\u770b\u5bb9\u5668\u72b6\u6001" \
    "9) \u67e5\u770b Docker \u72b6\u6001" \
    "10) \u67e5\u770b\u7cfb\u7edf\u72b6\u6001" \
    "11) \u67e5\u770b\u7aef\u53e3" \
    "12) \u67e5\u770b Network" \
    "13) \u91cd\u542f AstrBot" \
    "14) \u91cd\u542f NapCat" \
    "15) \u91cd\u542f\u5168\u90e8" \
    "16) \u505c\u6b62\u5168\u90e8" \
    "17) \u542f\u52a8\u5168\u90e8" \
    "18) \u5907\u4efd" \
    "19) \u6062\u590d" \
    "20) \u5065\u5eb7\u68c0\u67e5" \
    "21) \u4e00\u952e\u5347\u7ea7" \
    "22) \u5378\u8f7d" \
    "23) Web \u63a7\u5236\u53f0" \
    "0) \u9000\u51fa"
}
while true; do
  menu; read -r -p $'\u8bf7\u9009\u62e9\uff1a' c || c=0
  case "$c" in
    1) cat "$DEPLOY_INFO_FILE" 2>/dev/null || warn $'\u5c1a\u672a\u751f\u6210\u90e8\u7f72\u4fe1\u606f';;
    2) update_astrbot; write_deploy_info;;
    3) update_napcat; write_deploy_info;;
    4) update_all;;
    5) read -r -p $'\u8bf7\u8f93\u5165\u65b0\u589e NapCat \u6570\u91cf\uff1a' n; add_napcat_instances "$n"; write_deploy_info;;
    6) list_napcat; read -r -p $'\u8bf7\u8f93\u5165\u8981\u5220\u9664\u7684\u5b9e\u4f8b\u540d\uff1a' n; delete_napcat_instance "$n"; write_deploy_info;;
    7) read -r -p $'\u5bb9\u5668\u540d\uff08\u7559\u7a7a\u9ed8\u8ba4 astrbot\uff09\uff1a' n; n="${n:-astrbot}"; docker logs -f --tail 200 "$n";;
    8) status_containers;;
    9) docker_status;;
    10) system_status;;
    11) ports_status;;
    12) network_status;;
    13) docker restart "$ASTRBOT_CONTAINER";;
    14) list_napcat; read -r -p $'NapCat \u5b9e\u4f8b\u540d\uff08\u7559\u7a7a\u8868\u793a\u5168\u90e8\uff09\uff1a' n; if [[ -z "$n" ]]; then while IFS=$'\t' read -r name _; do docker restart "$name"; done < "$NAPCAT_INDEX_FILE"; else docker restart "$n"; fi;;
    15) restart_all;;
    16) stop_all;;
    17) start_all;;
    18) backup_all;;
    19) restore_backup;;
    20) check_health;;
    21) update_all;;
    22) uninstall_all; exit 0;;
    23) bash "$PROJECT_DIR/scripts/web-admin.sh" setup; load_state; printf 'Web 控制台：http://%s:%s/  Token：%s\n' "$(public_ip)" "${WEB_ADMIN_PORT:-7070}" "${WEB_ADMIN_TOKEN:-}";;
    0) exit 0;;
    *) warn $'\u65e0\u6548\u9009\u9879';;
  esac
done
