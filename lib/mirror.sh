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
MIRROR_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mirror_catalog_tool(){ echo "$MIRROR_LIB_DIR/../scripts/mirror-catalog.py"; }

# Refresh bounded online catalogs, then merge with local and built-in fallbacks.
mirror_candidates(){
  local kind="$1"; shift
  if have_cmd python3 && [[ -f "$(mirror_catalog_tool)" ]]; then
    python3 "$(mirror_catalog_tool)" candidates "$kind" \
      --cache-dir "${MIRROR_CACHE_DIR:-${INSTALL_PREFIX:-/opt/astrbot}/cache/mirrors}" \
      --timeout "${MIRROR_DISCOVERY_TIMEOUT:-4}" --ttl "${MIRROR_CACHE_TTL:-86400}" || true
  fi
  if (( $# )); then printf '%s\n' "$@"; fi
}

mirror_enabled(){ [[ "${NAILONG_MIRROR:-auto}" != "off" ]] && have_cmd curl; }

# mirror_probe URL [ok_codes] -> prints milliseconds, or nothing on failure.
mirror_probe(){
  local url="$1" codes="${2:-200}" out code t headers
  headers="$(mktemp)"
  if ! out="$(curl -sS -o /dev/null -D "$headers" -L --proto '=http,https' --proto-redir '=http,https' \
      --connect-timeout 3 --max-time "$MIRROR_PROBE_TIMEOUT" -w '%{http_code} %{time_total}' "$url" 2>/dev/null)"; then
    rm -f "$headers"; return 1
  fi
  code="${out%% *}"; t="${out##* }"
  if [[ " $codes " != *" $code "* ]]; then rm -f "$headers"; return 1; fi
  # A proxy homepage returning HTTP 200 is not a working registry.
  if [[ "$url" == */v2/ ]] && ! grep -Eiq '^Docker-Distribution-Api-Version:[[:space:]]*registry/2[.]0' "$headers"; then
    rm -f "$headers"; return 1
  fi
  rm -f "$headers"
  awk -v t="$t" 'BEGIN{printf "%d\n", t*1000}'
}

# Bounded parallel probes; the measured value is response latency, not MB/s.
mirror_race(){
  local label="$1" suffix="$2" codes="$3"; shift 3
  local c ms tmp seen=" " count=0 pid jobs=() max="${MIRROR_MAX_CANDIDATES:-32}" workers="${MIRROR_CONCURRENCY:-8}"
  [[ "$max" =~ ^[1-9][0-9]?$ ]] || max=32
  [[ "$workers" =~ ^[1-9][0-9]?$ ]] || workers=8
  (( max <= 64 )) || max=64
  (( workers <= 16 )) || workers=16
  tmp="$(mktemp -d)"
  for c in "$@"; do
    [[ -n "$c" && "$seen" != *" $c "* ]] || continue
    seen+="$c "; count=$((count+1))
    ( if ms="$(mirror_probe "${c}${suffix}" "$codes")"; then printf '%s %s\n' "$ms" "$c" > "$tmp/$count"; fi ) &
    jobs+=("$!")
    if (( ${#jobs[@]} >= workers )); then
      for pid in "${jobs[@]}"; do wait "$pid" || true; done
      jobs=()
    fi
    (( count < max )) || break
  done
  for pid in "${jobs[@]}"; do wait "$pid" || true; done
  find "$tmp" -type f -exec cat {} + | sort -nk1,1 -k2,2
  rm -rf -- "$tmp"
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
  local id codename path arch current best results files f candidates=()
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
    mapfile -t candidates < <(mirror_candidates apt "${APT_CANDIDATES[@]}")
    results="$(mirror_race apt "/${path}/dists/${codename}/Release" "200" ${current:+"$current"} "$official" "${candidates[@]}")"
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
  local results best candidates=()
  mapfile -t candidates < <(mirror_candidates pip "${PIP_CANDIDATES[@]}")
  results="$(mirror_race pip "/pip/" "200" "${candidates[@]}")"
  mirror_report "PyPI" "$results"
  best="$(head -n1 <<<"$results" | awk '{print $2}')"
  [[ -n "$best" ]] || return 0
  export PIP_INDEX_URL="$best"
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
  local probe="https://raw.githubusercontent.com/Ceiity/linyu/main/README.md" results c candidates=()
  mapfile -t candidates < <(mirror_candidates github "${GH_PROXY_CANDIDATES[@]}")
  # Official direct route participates alongside discovered proxy routes.
  local direct
  direct="$(mirror_probe "$probe" || true)"
  results="$(mirror_race github "$probe" "200" "${candidates[@]}")"
  [[ -z "$direct" ]] || results="$(printf '%s\n%s direct\n' "$results" "$direct" | sed '/^$/d' | sort -nk1,1 -k2,2)"
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
  https://dockerproxy.link
  https://docker.1panel.live
)

restart_docker_for_mirrors(){
  local i
  if ! systemctl restart docker; then service docker restart || return 1; fi
  for ((i=0;i<15;i++)); do
    docker version >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

setup_docker_mirrors(){
  mirror_enabled || return 0
  have_cmd docker || return 0
  local results hub_ms list=() line candidates=() result action backup
  local config="${DOCKER_DAEMON_CONFIG:-/etc/docker/daemon.json}" tool
  tool="$(mirror_catalog_tool)"
  if [[ -n "${DOCKER_MIRRORS:-}" ]]; then
    read -r -a list <<<"${DOCKER_MIRRORS//,/ }"
  else
    step "Discovering and testing Docker Hub registry mirrors"
    hub_ms="$(mirror_probe "https://registry-1.docker.io/v2/" "200 401" || true)"
    mapfile -t candidates < <(mirror_candidates docker "${DOCKER_MIRROR_CANDIDATES[@]}")
    results="$(mirror_race docker "/v2/" "200 401" "${candidates[@]}")"
    mirror_report "Docker registry" "$results"
    if [[ -n "$hub_ms" ]]; then
      line="$(head -n1 <<<"$results" | awk '{print $1}')"
      if [[ -z "$line" ]] || (( hub_ms <= line )); then
        success "Docker Hub is the fastest reachable route (${hub_ms} ms); keeping Docker config unchanged"
        return 0
      fi
    fi
    while read -r _ line; do [[ -n "$line" ]] && list+=("$line"); done <<<"$results"
    list=("${list[@]:0:3}")
  fi
  (( ${#list[@]} )) || { warn "No verified registry mirror answered; keeping Docker config unchanged (official fallback)."; return 0; }
  if ! result="$(python3 "$tool" configure-docker "$config" "${list[@]}")"; then
    warn "Could not update $config; original config unchanged"
    return 1
  fi
  IFS=$'\t' read -r action backup <<<"$result"
  if [[ "$action" == unchanged ]]; then
    success "Docker registry mirrors already configured; no daemon restart needed"
    return 0
  fi
  info "Docker config updated and read back; snapshot: ${backup} (- means config did not exist)"
  if have_cmd dockerd && ! dockerd --validate --config-file "$config"; then
    python3 "$tool" restore-docker "$config" "$backup" || return 1
    warn "Docker config validation failed; restored previous config without restarting Docker"
    return 1
  fi
  if restart_docker_for_mirrors; then
    success "Docker registry mirrors: ${list[*]}"
  else
    warn "Docker restart failed; restoring the exact pre-change config"
    python3 "$tool" restore-docker "$config" "$backup" || return 1
    restart_docker_for_mirrors || warn "Docker recovery failed; inspect: journalctl -u docker"
    return 1
  fi
}

# Run all probes up front (they are independent and run in parallel internally).
setup_mirrors_early(){
  mirror_enabled || { info "Mirror selection disabled (NAILONG_MIRROR=off)"; return 0; }
  setup_apt_mirror || warn "apt mirror selection failed; continuing"
  setup_pip_mirror || true
  setup_github_proxy || true
}
