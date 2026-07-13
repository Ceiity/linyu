#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$SCRIPT_DIR/scripts/install-core.sh" ]]; then
  BOOTSTRAP_REPO="${ASTRBOT_DEPLOY_REPO:-https://github.com/astrbot-deploy/AstrBot-Deploy.git}"
  PREFIX="${INSTALL_PREFIX:-/opt/astrbot}"
  command -v git >/dev/null 2>&1 || { apt-get update -y && apt-get install -y git curl ca-certificates; }
  mkdir -p "$PREFIX"
  if [[ -d "$PREFIX/AstrBot-Deploy/.git" ]]; then git -C "$PREFIX/AstrBot-Deploy" pull --ff-only; else git clone "$BOOTSTRAP_REPO" "$PREFIX/AstrBot-Deploy"; fi
  exec bash "$PREFIX/AstrBot-Deploy/scripts/install-core.sh"
fi
exec bash "$SCRIPT_DIR/scripts/install-core.sh"
