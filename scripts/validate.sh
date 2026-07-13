#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
files=(install.sh manager.sh update.sh backup.sh restore.sh uninstall.sh scripts/*.sh lib/*.sh)
for f in "${files[@]}"; do
  bash -n "$f"
  grep -q 'set -Eeuo pipefail' "$f"
done
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  mkdir -p "$tmp/compose/astrbot" "$tmp/napcat/napcat01/config" "$tmp/data"
  cat > "$tmp/compose/astrbot/docker-compose.yml" <<'YAML'
services:
  astrbot:
    image: soulter/astrbot:latest
    container_name: astrbot
    restart: always
    security_opt:
      - no-new-privileges:true
    ports:
      - "6185:6185"
      - "6199:6199"
    environment:
      - TZ=Asia/Shanghai
    volumes:
      - /opt/astrbot/data:/AstrBot/data
    networks:
      - astrbot_network
networks:
  astrbot_network:
    external: true
YAML
  docker compose -f "$tmp/compose/astrbot/docker-compose.yml" config >/dev/null
fi
echo "validation passed"
