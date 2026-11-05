#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_root="$(mktemp -d)"
tmp="$(mktemp "$PROJECT_DIR/scripts/.test-https.XXXXXX")"
trap 'rm -f "$tmp"; rm -rf "$test_root"' EXIT
export INSTALL_PREFIX="$test_root/astrbot"
head -n -1 "$PROJECT_DIR/scripts/https.sh" > "$tmp"
# shellcheck disable=SC1090
source "$tmp"

TARGET=""
EMAIL=""
TARGET_KIND="auto"
HTTPS_IP=0
parse_args --ip
[[ "$TARGET_KIND" == "ip" ]]

TARGET=""
EMAIL=""
TARGET_KIND="auto"
HTTPS_IP=1
parse_args
[[ "$TARGET_KIND" == "ip" ]]

TARGET=""
EMAIL=""
TARGET_KIND="auto"
HTTPS_IP=0
parse_args --domain panel.example.com --email admin@example.com
[[ "$TARGET_KIND" == "domain" ]]
[[ "$TARGET" == "panel.example.com" ]]
[[ "$EMAIL" == "admin@example.com" ]]

echo "HTTPS argument parsing tests passed"
