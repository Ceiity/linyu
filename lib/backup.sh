#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy_info.sh"
backup_all(){ ensure_dirs; local ts archive; ts="$(date '+%Y%m%d_%H%M%S')"; archive="$BACKUP_DIR/astrbot_backup_${ts}.tar.gz"; step "Creating backup ${archive}"; tar -czf "$archive" -C "$INSTALL_PREFIX" data napcat .env napcat_index.tsv deploy_info.txt 2>/dev/null || tar -czf "$archive" -C "$INSTALL_PREFIX" data napcat .env napcat_index.tsv; success "Backup completed: $archive"; }
restore_backup(){ local archive="${1:-}"; [[ -n "$archive" ]] || { ls -1t "$BACKUP_DIR"/*.tar.gz 2>/dev/null | head -n 10; read -r -p "Backup file to restore: " archive; }; [[ -f "$archive" ]] || { fail "Backup file not found: $archive"; return 1; }; step "Stopping containers and restoring backup"; stop_all || true; tar -xzf "$archive" -C "$INSTALL_PREFIX"; success "Restore completed; starting containers"; start_all; }
