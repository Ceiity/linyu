#!/usr/bin/env bash
set -Eeuo pipefail
# Mirror selection with speed tests.
#
# apt mirrors use plain http on purpose: packages are signature-checked and
# a fresh image may not have ca-certificates yet.
#
# Every download source used by the installer (apt, Docker Hub, PyPI, GitHub)
# is probed against a list of domestic mirrors and the fastest one that
# answers is used. The official source stays in the race, so servers outside
# mainland China keep using it when it is quickest.
#
#   NAILONG_MIRROR=auto   (default) probe and pick the fastest
#   NAILONG_MIRROR=off    never touch sources; use official endpoints
#   APT_MIRROR / PIP_INDEX_URL / GH_PROXY / DOCKER_MIRRORS  force a choice
#
# Third-party Docker Hub and GitHub proxies come and go; they are only kept
# when they answer the probe, and docker falls back to Docker Hub itself.

MIRROR_PROBE_TIMEOUT="${MIRROR_PROBE_TIMEOUT:-6}"

mirror_enabled(){ [[ "${NAILONG_MIRROR:-auto}" != "off" ]] && have_cmd curl; }

# mirror_probe URL [ok_codes] -> prints milliseconds, or nothing on failure.
mirror_probe(){
  local url="$1" codes="${2:-200}" out code t
  out="$(curl -sS -o /dev/null -L --connect-timeout 3 --max-time "$MIRROR_PROBE_TIMEOUT" -w '%{http_code} %{time_total}' "$url" 2>/dev/null)" || return 1
  code="${out%% *}"; t="${out##* }"
  [[ " $codes " == *" $code "* ]] || return 1
  awk -v t="$t" 'BEGIN{printf "%d\n", t*1000}'
}

# mirror_race "label" "probe-suffix" "ok-codes" candidate... -> prints "ms candidate" lines, fastest first.
mirror_race(){
  local label="$1" suffix="$2" codes="$3"; shift 3
  local c ms tmp seen=" "; tmp="$(mktemp)"
  for c in "$@"; do
    [[ "$seen" == *" $c "* ]] && continue; seen+="$c "
    ( ms="$(mirror_probe "${c}${suffix}" "$codes")" && echo "$ms $c" >> "$tmp" ) &
  done
  wait
  sort -n "$tmp"; rm -f "$tmp"
}

mirror_report(){
  local label="$1" results="$2"
  if [[ -z "$results" ]]; then warn "${label}: no source answered the speed test"; return 0; fi
  info "${label} speed test:"; while read -r ms c; do printf '    %6s ms  %s\n' "$ms" "$c"; done <<<"$results"
}

# ---------- apt ----------
APT_CANDIDATES=(
  http://mirrors.aliyun.com
  http://mirrors.tuna.tsinghua.edu.cn
  http://mirrors.ustc.edu.cn
  http://mirrors.cloud.tencent.com
  http://repo.huaweicloud.com
)

apt_source_files(){
  local f
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    if [[ -f "$f" ]] && grep -Eq '^[[:space:]]*(deb|URIs:)' "$f"; then echo "$f"; fi
  done
  return 0
}

setup_apt_mirror(){
  mirror_enabled || return 0
  [[ -r /etc/os-release ]] || return 0
  local id codename path arch current best results files f
  . /etc/os-release; id="${ID:-}"; codename="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"
  arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
  case "$id" in
    ubuntu) path="ubuntu"; [[ "$arch" == "amd64" || "$arch" == "i386" ]] || path="ubuntu-ports" ;;
    debian) path="debian" ;;
    *) return 0 ;;
  esac
  [[ -n "$codename" ]] || return 0
  files="$(apt_source_files || true)"; [[ -n "$files" ]] || return 0
  current="$(grep -hoE "https?://[^/ ]+/${path}/?" $files 2>/dev/null | grep -v security | head -n1 | sed -E "s#/${path}/?\$##" || true)"
  local official="http://deb.debian.org"; [[ "$id" == "ubuntu" ]] && official="http://archive.ubuntu.com"
  [[ "$path" == "ubuntu-ports" ]] && official="http://ports.ubuntu.com"
  if [[ -n "${APT_MIRROR:-}" ]]; then best="$APT_MIRROR"; else
    step "Testing apt mirrors"
    results="$(mirror_race apt "/${path}/dists/${codename}/Release" "200" ${current:+"$current"} "$official" "${APT_CANDIDATES[@]}")"
    mirror_report "apt" "$results"
    best="$(head -n1 <<<"$results" | awk '{print $2}')"
    [[ -n "$best" ]] || { warn "apt mirror test failed; keeping current sources"; return 0; }
    if [[ -n "$current" && "$best" != "$current" ]]; then
      local cur_ms best_ms; cur_ms="$(awk -v c="$current" '$2==c{print $1}' <<<"$results")"; best_ms="$(head -n1 <<<"$results" | awk '{print $1}')"
      # Keep the current mirror unless the winner is clearly faster.
      if [[ -n "$cur_ms" ]] && (( cur_ms < best_ms * 3 / 2 + 300 )); then best="$current"; fi
    fi
  fi
  if [[ "$best" == "$current" ]]; then success "apt: keeping ${current}"; return 0; fi
  for f in $files; do
    grep -Eq "https?://[^/ ]+/(${path}|debian-security)" "$f" || continue
    [[ -f "${f}.nailong.bak" ]] || cp -a "$f" "${f}.nailong.bak"
    if [[ "$id" == "debian" ]]; then
      sed -i -E "s#https?://[^/ ]+/(debian-security|debian)/?#${best}/\\1/#g" "$f"
    else
      sed -i -E "s#https?://[^/ ]+/${path}/?#${best}/${path}/#g" "$f"
    fi
  done
  success "apt: switched to ${best} (backup: *.nailong.bak)"
}

# ---------- PyPI ----------
PIP_CANDIDATES=(
  https://pypi.org/simple
  https://pypi.tuna.tsinghua.edu.cn/simple
  https://mirrors.aliyun.com/pypi/simple
  https://mirrors.cloud.tencent.com/pypi/simple
  https://repo.huaweicloud.com/repository/pypi/simple
)

setup_pip_mirror(){
  [[ -n "${PIP_INDEX_URL:-}" ]] && { export PIP_INDEX_URL; return 0; }
  mirror_enabled || return 0
  local results best
  results="$(mirror_race pip "/pip/" "200" "${PIP_CANDIDATES[@]}")"
  mirror_report "PyPI" "$results"
  best="$(head -n1 <<<"$results" | awk '{print $2}')"
  [[ -n "$best" ]] || return 0
  export PIP_INDEX_URL="$best"
  export PIP_TRUSTED_HOST="$(sed -E 's#https?://([^/]+).*#\1#' <<<"$best")"
  export PIP_DEFAULT_TIMEOUT=30
  success "PyPI: ${best}"
}

# ---------- GitHub ----------
GH_PROXY_CANDIDATES=(
  https://ghfast.top/
  https://gh-proxy.com/
  https://ghproxy.net/
)

# Picks the fastest way to reach GitHub; exports GH_PROXY ("" = direct).
setup_github_proxy(){
  [[ -n "${GH_PROXY+x}" ]] && return 0
  export GH_PROXY=""
  mirror_enabled || return 0
  local probe="https://raw.githubusercontent.com/Ceiity/linyu/main/README.md" results tmp c ms
  tmp="$(mktemp)"
  ( ms="$(mirror_probe "$probe")" && echo "$ms direct" >> "$tmp" ) &
  for c in "${GH_PROXY_CANDIDATES[@]}"; do ( ms="$(mirror_probe "${c}${probe}")" && echo "$ms $c" >> "$tmp" ) & done
  wait; results="$(sort -n "$tmp")"; rm -f "$tmp"
  mirror_report "GitHub" "$results"
  c="$(head -n1 <<<"$results" | awk '{print $2}')"
  if [[ -n "$c" && "$c" != "direct" ]]; then GH_PROXY="$c"; fi
  export GH_PROXY
}

# gh_url URL -> URL routed through the chosen GitHub proxy (if any).
gh_url(){
  local u="$1"
  if [[ -n "${GH_PROXY:-}" && "$u" =~ ^https://(github\.com|raw\.githubusercontent\.com|objects\.githubusercontent\.com)/ ]]; then
    echo "${GH_PROXY}${u}"
  else
    echo "$u"
  fi
}

# ---------- Docker Hub ----------
DOCKER_MIRROR_CANDIDATES=(
  https://docker.1ms.run
  https://docker.m.daocloud.io
  https://docker.xuanyuan.me
  https://dockerproxy.net
  https://hub.rat.dev
  https://docker.1panel.live
)

setup_docker_mirrors(){
  mirror_enabled || return 0
  have_cmd docker || return 0
  local results hub_ms list=() line
  if [[ -n "${DOCKER_MIRRORS:-}" ]]; then
    read -r -a list <<<"${DOCKER_MIRRORS//,/ }"
  else
    step "Testing Docker Hub and registry mirrors"
    hub_ms="$(mirror_probe "https://registry-1.docker.io/v2/" "200 401" || true)"
    if [[ -n "$hub_ms" ]] && (( hub_ms < 1500 )); then
      success "Docker Hub reachable directly (${hub_ms} ms); no registry mirror needed"
      return 0
    fi
    results="$(mirror_race docker "/v2/" "200 401" "${DOCKER_MIRROR_CANDIDATES[@]}")"
    mirror_report "Docker registry" "$results"
    while read -r _ line; do [[ -n "$line" ]] && list+=("$line"); done <<<"$results"
    list=("${list[@]:0:3}")
  fi
  (( ${#list[@]} )) || { warn "No Docker registry mirror answered; image pulls go to Docker Hub directly."; return 0; }
  mkdir -p /etc/docker
  python3 - "/etc/docker/daemon.json" "${list[@]}" <<'PY' || { warn "Could not update /etc/docker/daemon.json"; return 0; }
import json, os, sys
path, mirrors = sys.argv[1], sys.argv[2:]
cfg = {}
if os.path.exists(path):
    try:
        cfg = json.load(open(path, encoding="utf-8")) or {}
    except Exception:
        os.replace(path, path + ".broken")
        cfg = {}
if cfg.get("registry-mirrors") == mirrors:
    sys.exit(0)
if os.path.exists(path) and not os.path.exists(path + ".nailong.bak"):
    import shutil; shutil.copy2(path, path + ".nailong.bak")
cfg["registry-mirrors"] = mirrors
tmp = path + ".tmp"
json.dump(cfg, open(tmp, "w", encoding="utf-8"), indent=2)
os.replace(tmp, path)
PY
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl restart docker >/dev/null 2>&1 || service docker restart >/dev/null 2>&1 || true
  if docker version >/dev/null 2>&1; then success "Docker registry mirrors: ${list[*]}"; else warn "Docker did not come back after adding mirrors; check: journalctl -u docker"; fi
}

# Run all probes up front (they are independent and run in parallel internally).
setup_mirrors_early(){
  mirror_enabled || { info "Mirror selection disabled (NAILONG_MIRROR=off)"; return 0; }
  setup_apt_mirror || warn "apt mirror selection failed; continuing"
  setup_pip_mirror || true
  setup_github_proxy || true
}
