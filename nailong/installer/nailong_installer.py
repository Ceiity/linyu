#!/usr/bin/env python3
"""奶龙服务器安装器。

由奶龙 App 通过 SSH 上传（校验 SHA-256 后）并以 root 运行，只使用 Python 标准库。

子命令：
  detect                       输出环境检测报告与部署计划（JSON）
  deploy --config FILE         按计划部署，逐行输出 @@EVENT / @@RESULT
  pair-code                    生成一次性配对码（10 分钟有效）
  authorize-key ...            为 App 写入只能转发到 Agent 端口的受限 SSH 公钥
  revoke-key ...               删除 App 公钥
  cancel                       安全取消正在运行的部署
  speedtest --config FILE      测试镜像仓库与下载源

安全约束：不执行任何网络下载的脚本；Docker 软件源 GPG 指纹固定；
镜像按 digest 拉取；已有服务只读接管，不覆盖配置、不删除数据。
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import http.client
import ipaddress
import json
import os
import platform
import pwd
import re
import secrets
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "1.0.0"
BASE = Path(os.environ.get("NAILONG_BASE", "/opt/nailong"))
STATE_FILE = BASE / "state.json"
PID_FILE = BASE / "run" / "installer.pid"
RUN_DIR = BASE / "run"
DEPLOY_LOG = RUN_DIR / "deploy.log"
DEPLOY_CFG = RUN_DIR / "deploy-config.json"
POLL_MAX_BYTES = 256 * 1024
CACHE_DIR = BASE / "cache"
DOCKER_SOCK = os.environ.get("NAILONG_DOCKER_SOCK", "/var/run/docker.sock")
BUNDLE_DIR = Path(__file__).resolve().parent

# 固定版本 + 镜像摘要（多架构 index digest）。通过任何镜像源拉取时 Docker 都会按摘要校验内容。
IMAGES = {
    "astrbot": {"repo": "soulter/astrbot", "tag": "v4.29.3",
                "digest": "sha256:c93a6d19507ba45474c3dfb82aad9d36eb432a478112f13c7e6325b5ebffc5f2"},
    "napcat": {"repo": "mlikiowa/napcat-docker", "tag": "v4.18.41",
               "digest": "sha256:b101b8968cc31ae428ec0f8e117386e4ced7773b2d8226ed9f7ddfcec55f1b7e"},
    "python": {"repo": "library/python", "tag": "3.12-slim-bookworm",
               "digest": "sha256:62ed8e07e544e8555c5d93748d5275015136b7f5c52b5e8679b4de339c3779d3"},
}
# Docker 官方软件源签名密钥指纹（https://docs.docker.com/engine/install/ubuntu/）
DOCKER_GPG_FINGERPRINT = "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
OFFICIAL_DOCKER_APT = "https://download.docker.com"
OFFICIAL_REGISTRY = "registry-1.docker.io"
OFFICIAL_PYPI = "https://pypi.org/simple"

SUPPORTED_OS = {"ubuntu": ["20.04", "22.04", "24.04", "24.10", "25.04", "25.10", "26.04"],
                "debian": ["11", "12", "13"]}
SUPPORTED_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
MIN_FREE_DISK_GB = 4
MIN_MEMORY_MB = 900

NETWORK_NAME = "nailong_net"
HOST_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


def host_ca_binds() -> list[str]:
    """让容器使用宿主机的系统信任库（不关闭任何证书校验）。"""
    if Path(HOST_CA_BUNDLE).is_file():
        return ["%s:/etc/ssl/certs/ca-certificates.crt:ro" % HOST_CA_BUNDLE]
    return []
ASTRBOT_WS_PORT = 6199


class InstallError(Exception):
    """带用户可读提示的错误。"""

    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


class Cancelled(Exception):
    pass


_CANCELLED = False


def _on_term(signum, frame):  # noqa: ARG001
    global _CANCELLED
    _CANCELLED = True


def check_cancel() -> None:
    if _CANCELLED:
        raise Cancelled()


# ---------------------------------------------------------------- 输出与脱敏

_SECRETS: set[str] = set()


def add_secret(value: str) -> None:
    if value and len(value) >= 6:
        _SECRETS.add(value)


def redact(text: str) -> str:
    for s in _SECRETS:
        text = text.replace(s, "******")
    text = re.sub(r"(?i)(token|password|passwd|secret|credential)([\"']?\s*[:=]\s*[\"']?)([^\s\"',}]{4,})", r"\1\2******", text)
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}", "Bearer ******", text)
    return text


def emit(kind: str, **data) -> None:
    data["type"] = kind
    data["ts"] = int(time.time())
    line = json.dumps(data, ensure_ascii=False)
    sys.stdout.write("@@EVENT " + redact(line) + "\n")
    sys.stdout.flush()


def log(msg: str) -> None:
    emit("log", line=msg)


# ---------------------------------------------------------------- 工具函数

def run(args: list[str], timeout: int = 600, check: bool = True, env: dict | None = None,
        stream: bool = False, input_text: str | None = None) -> tuple[int, str]:
    """执行命令（参数列表，不经过 shell）。"""
    full_env = dict(os.environ)
    full_env.setdefault("DEBIAN_FRONTEND", "noninteractive")
    full_env["LC_ALL"] = "C"
    if env:
        full_env.update(env)
    try:
        if stream:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    env=full_env, stdin=subprocess.DEVNULL if input_text is None else subprocess.PIPE)
            if input_text is not None:
                proc.stdin.write(input_text)
                proc.stdin.close()
            out_lines = []
            start = time.time()
            for line in proc.stdout:
                line = line.rstrip()
                out_lines.append(line)
                log(line)
                if _CANCELLED:
                    proc.terminate()
                    proc.wait(10)
                    raise Cancelled()
                if time.time() - start > timeout:
                    proc.kill()
                    raise InstallError("TIMEOUT", "命令执行超时：%s" % args[0])
            code = proc.wait()
            out = "\n".join(out_lines[-200:])
        else:
            p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=full_env, input=input_text)
            code, out = p.returncode, (p.stdout + p.stderr)
    except FileNotFoundError:
        code, out = 127, "%s: not found" % args[0]
    except subprocess.TimeoutExpired:
        raise InstallError("TIMEOUT", "命令执行超时：%s" % args[0])
    if check and code != 0:
        raise InstallError("COMMAND_FAILED", "命令执行失败：%s" % " ".join(args[:3]), out[-2000:])
    return code, out


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, data, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    os.chmod(path, mode)


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(path.name + ".nailong-bak-" + stamp)
    shutil.copy2(path, dest)
    return dest


def load_state() -> dict:
    return read_json(STATE_FILE, {})


def save_state(state: dict) -> None:
    state["version"] = VERSION
    state["updated_at"] = int(time.time())
    write_json(STATE_FILE, state)


def rand_token(n: int = 24) -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024
    return "%.1f PB" % n


# ---------------------------------------------------------------- Docker Engine API

class _UnixConn(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


class DockerError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def docker_available() -> bool:
    try:
        docker_api("GET", "/_ping", timeout=5)
        return True
    except Exception:
        return False


def docker_api(method: str, path: str, body=None, timeout: float = 60, raw: bool = False,
               headers: dict | None = None):
    conn = _UnixConn(DOCKER_SOCK, timeout)
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = body
        else:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    payload = resp.read()
    conn.close()
    if resp.status >= 400:
        try:
            msg = json.loads(payload).get("message", "")
        except Exception:
            msg = payload.decode(errors="replace")
        raise DockerError(resp.status, msg)
    if raw:
        return payload
    if not payload:
        return None
    try:
        return json.loads(payload)
    except Exception:
        return payload.decode(errors="replace")


def docker_stream(method: str, path: str, body=None, timeout: float = 120):
    """逐行读取 Docker 流式 JSON（拉取镜像等）。超过 timeout 秒无数据视为卡住。"""
    conn = _UnixConn(DOCKER_SOCK, timeout)
    hdrs = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    if resp.status >= 400:
        payload = resp.read()
        conn.close()
        try:
            msg = json.loads(payload).get("message", "")
        except Exception:
            msg = payload.decode(errors="replace")
        raise DockerError(resp.status, msg)
    buf = b""
    try:
        while True:
            check_cancel()
            chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    try:
                        yield json.loads(line)
                    except Exception:
                        continue
    finally:
        conn.close()


def q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def list_containers() -> list[dict]:
    rows = docker_api("GET", "/containers/json?all=1") or []
    out = []
    for c in rows:
        name = (c.get("Names") or ["/?"])[0].lstrip("/")
        out.append({
            "id": c.get("Id", "")[:12],
            "name": name,
            "image": c.get("Image", ""),
            "state": c.get("State", ""),
            "status": c.get("Status", ""),
            "labels": c.get("Labels") or {},
            "ports": [{"private": p.get("PrivatePort"), "public": p.get("PublicPort"), "ip": p.get("IP", ""),
                       "type": p.get("Type")} for p in (c.get("Ports") or [])],
            "networks": list(((c.get("NetworkSettings") or {}).get("Networks") or {}).keys()),
            "mounts": [{"source": m.get("Source", ""), "destination": m.get("Destination", ""),
                        "type": m.get("Type", "")} for m in (c.get("Mounts") or [])],
        })
    return out


def container_inspect(name: str) -> dict | None:
    try:
        return docker_api("GET", "/containers/%s/json" % q(name))
    except DockerError as e:
        if e.status == 404:
            return None
        raise


def ensure_network(name: str) -> None:
    try:
        docker_api("GET", "/networks/%s" % q(name))
    except DockerError as e:
        if e.status != 404:
            raise
        docker_api("POST", "/networks/create", {"Name": name, "Driver": "bridge",
                                                 "Labels": {"com.nailong.managed": "true"}})


def image_exists(ref: str) -> bool:
    try:
        docker_api("GET", "/images/%s/json" % q(ref))
        return True
    except DockerError:
        return False


def image_repo_digests(ref: str) -> list[str]:
    try:
        info = docker_api("GET", "/images/%s/json" % q(ref))
        return info.get("RepoDigests") or []
    except DockerError:
        return []


def create_and_start(name: str, spec: dict) -> None:
    docker_api("POST", "/containers/create?name=%s" % q(name), spec)
    docker_api("POST", "/containers/%s/start" % q(name))


def wait_container_running(name: str, seconds: int = 60) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        check_cancel()
        info = container_inspect(name)
        if info and (info.get("State") or {}).get("Running"):
            return True
        if info and (info.get("State") or {}).get("Status") == "exited":
            return False
        time.sleep(2)
    return False


def container_logs(name: str, tail: int = 80) -> str:
    try:
        raw = docker_api("GET", "/containers/%s/logs?stdout=1&stderr=1&tail=%d" % (q(name), tail), raw=True)
    except Exception:
        return ""
    return demux_logs(raw)


def demux_logs(raw: bytes) -> str:
    out = []
    i = 0
    while i + 8 <= len(raw) and raw[i] in (0, 1, 2) and raw[i + 1:i + 4] == b"\x00\x00\x00":
        size = int.from_bytes(raw[i + 4:i + 8], "big")
        out.append(raw[i + 8:i + 8 + size])
        i += 8 + size
    if i == 0:
        return raw.decode(errors="replace")
    return b"".join(out).decode(errors="replace")


def container_ip(name: str) -> str:
    info = container_inspect(name) or {}
    for net in ((info.get("NetworkSettings") or {}).get("Networks") or {}).values():
        if net.get("IPAddress"):
            return net["IPAddress"]
    return ""


def published_port(info: dict, private: int) -> tuple[str, int] | None:
    ports = ((info.get("NetworkSettings") or {}).get("Ports") or {}).get("%d/tcp" % private) or []
    for p in ports:
        if p.get("HostPort"):
            host = p.get("HostIp") or "127.0.0.1"
            if host in ("0.0.0.0", "::", ""):
                host = "127.0.0.1"
            return host, int(p["HostPort"])
    return None


def bind_source(info: dict, destination: str) -> str:
    for m in info.get("Mounts") or []:
        if m.get("Destination") == destination:
            return m.get("Source", "")
    return ""


# ---------------------------------------------------------------- 端口

def listening_ports() -> set[int]:
    ports: set[int] = set()
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            for line in Path(f).read_text().splitlines()[1:]:
                parts = line.split()
                if len(parts) > 3 and parts[3] == "0A":
                    ports.add(int(parts[1].rsplit(":", 1)[1], 16))
        except Exception:
            pass
    if docker_available():
        try:
            for c in list_containers():
                for p in c["ports"]:
                    if p.get("public"):
                        ports.add(int(p["public"]))
        except Exception:
            pass
    return ports


def pick_port(start: int, reserved: set[int], span: int = 200) -> int:
    used = listening_ports() | reserved
    for p in range(start, start + span):
        if p in used:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
    raise InstallError("PORT_CONFLICT", "端口 %d-%d 都被占用，无法自动分配。" % (start, start + span))


def http_ready(url: str, timeout: float = 5) -> bool:
    """服务真正可用：能收到任意 HTTP 响应（docker-proxy 端口提前可连，不能只看 TCP）。"""
    try:
        http_plain(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def tcp_open(host: str, port: int, timeout: float = 3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------- 网络与下载源

_SSL = ssl.create_default_context()


def http_request(url: str, method: str = "GET", headers: dict | None = None, timeout: float = 8,
                 max_bytes: int = 1 << 20) -> tuple[int, dict, bytes, float]:
    """HTTPS 请求（强制证书校验）。返回 (status, headers, body, 首字节耗时秒)。"""
    req = urllib.request.Request(url, method=method, headers=headers or {})
    req.add_header("User-Agent", "Nailong-Installer/%s" % VERSION)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            ttfb = time.time() - t0
            body = r.read(max_bytes) if method != "HEAD" else b""
            return r.status, dict(r.headers), body, ttfb
    except urllib.error.HTTPError as e:
        ttfb = time.time() - t0
        try:
            body = e.read(max_bytes)
        except Exception:
            body = b""
        return e.code, dict(e.headers or {}), body, ttfb


def dns_ok(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        return True
    except OSError:
        return False


def registry_host(entry: str) -> str:
    entry = entry.strip().rstrip("/")
    if entry.startswith("https://"):
        entry = entry[8:]
    elif entry.startswith("http://"):
        raise InstallError("INSECURE_MIRROR", "镜像加速地址必须使用 HTTPS：%s" % entry)
    if not re.fullmatch(r"[A-Za-z0-9.\-]+(:\d+)?(/[A-Za-z0-9._\-/]+)?", entry):
        raise InstallError("BAD_MIRROR", "镜像加速地址格式不正确：%s" % entry)
    return entry


def registry_token(www_auth: str, repo: str) -> str | None:
    m = re.match(r'Bearer\s+(.*)', www_auth or "", re.I)
    if not m:
        return None
    params = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
    realm = params.get("realm")
    if not realm or not realm.startswith("https://"):
        return None
    query = {"scope": "repository:%s:pull" % repo}
    if params.get("service"):
        query["service"] = params["service"]
    status, _, body, _ = http_request(realm + "?" + urllib.parse.urlencode(query), timeout=8)
    if status != 200:
        return None
    try:
        data = json.loads(body)
        return data.get("token") or data.get("access_token")
    except Exception:
        return None


def probe_registry(registry: str, image: dict, arch: str) -> dict:
    """检测：DNS、TLS、/v2/ 可达、镜像摘要存在、架构匹配、延迟。"""
    host = registry.split("/")[0]
    prefix = registry[len(host):]
    result = {"registry": registry, "ok": False, "latency_ms": None, "error": ""}
    if not dns_ok(host.split(":")[0]):
        result["error"] = "DNS 解析失败"
        return result
    repo = image["repo"]
    path_repo = (prefix.strip("/") + "/" + repo) if prefix else repo
    url = "https://%s/v2/%s/manifests/%s" % (host, path_repo, image["digest"])
    accept = ("application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,"
              "application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json")
    try:
        t0 = time.time()
        status, hdrs, body, _ = http_request(url, headers={"Accept": accept}, timeout=8)
        if status == 401:
            token = registry_token(hdrs.get("WWW-Authenticate") or hdrs.get("Www-Authenticate", ""), repo)
            if not token:
                result["error"] = "需要认证"
                return result
            status, hdrs, body, _ = http_request(url, headers={"Accept": accept, "Authorization": "Bearer " + token},
                                                 timeout=8)
        result["latency_ms"] = int((time.time() - t0) * 1000)
        if status != 200:
            result["error"] = "镜像不存在或不可访问（HTTP %d）" % status
            return result
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        if digest != image["digest"]:
            result["error"] = "摘要不匹配，已拒绝该来源"
            return result
        manifest = json.loads(body)
        archs = [m.get("platform", {}).get("architecture") for m in manifest.get("manifests", [])]
        if archs and arch not in archs:
            result["error"] = "该镜像没有 %s 架构" % arch
            return result
        result["ok"] = True
    except ssl.SSLError as e:
        result["error"] = "TLS 证书无效：%s" % e
    except (urllib.error.URLError, OSError) as e:
        result["error"] = "无法连接：%s" % getattr(e, "reason", e)
    except Exception as e:  # noqa: BLE001
        result["error"] = str(e)[:200]
    return result


def rank_registries(registries: list[str], image_key: str, arch: str, use_cache: bool = True) -> list[dict]:
    cache_file = CACHE_DIR / "registry-speedtest.json"
    cache = read_json(cache_file, {}) if use_cache else {}
    key = image_key + "|" + ",".join(registries)
    hit = cache.get(key)
    if hit and time.time() - hit.get("ts", 0) < 6 * 3600:
        return hit["results"]
    results = [probe_registry(r, IMAGES[image_key], arch) for r in registries]
    results.sort(key=lambda r: (not r["ok"], r["latency_ms"] or 10 ** 9))
    cache[key] = {"ts": time.time(), "results": results}
    try:
        write_json(cache_file, cache, 0o644)
    except Exception:
        pass
    return results


def rank_by_latency(bases: list[str], probe_path: str, timeout: float = 6) -> list[str]:
    """并发探测各下载源，按响应速度从快到慢排序；不可达的排在最后（保留作兜底）。
    只做排序，不改变信任：之后仍然校验 GPG 指纹 / 哈希 / 摘要。"""
    import concurrent.futures

    def one(base: str) -> tuple[bool, float]:
        try:
            status, _, _, ttfb = http_request(base + probe_path, method="GET", timeout=timeout, max_bytes=4096)
            return status in (200, 301, 302), ttfb
        except Exception:
            return False, 1e9

    if len(bases) < 2:
        return list(bases)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(bases))) as ex:
        res = list(ex.map(one, bases))
    order = sorted(range(len(bases)), key=lambda i: (not res[i][0], res[i][1], i))
    return [bases[i] for i in order]


# ---------------------------------------------------------------- 环境检测

def os_info() -> dict:
    data = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k] = v.strip().strip('"')
    except Exception:
        pass
    os_id = data.get("ID", "unknown")
    ver = data.get("VERSION_ID", "")
    machine = platform.machine()
    arch = SUPPORTED_ARCH.get(machine, "")
    supported = os_id in SUPPORTED_OS and (ver in SUPPORTED_OS[os_id] or _ver_ge(ver, SUPPORTED_OS[os_id][0]))
    reason = ""
    if os_id not in SUPPORTED_OS:
        reason = "暂不支持 %s，请使用 Ubuntu 20.04+ 或 Debian 11+" % (data.get("PRETTY_NAME") or os_id)
    elif not supported:
        reason = "%s 版本过旧，请使用 Ubuntu 20.04+ 或 Debian 11+" % data.get("PRETTY_NAME")
    elif not arch:
        supported = False
        reason = "暂不支持 %s 架构（仅支持 x86_64 / arm64）" % machine
    return {"id": os_id, "version": ver, "codename": data.get("VERSION_CODENAME", ""),
            "pretty": data.get("PRETTY_NAME", os_id), "machine": machine, "arch": arch,
            "kernel": platform.release(), "supported": bool(supported and arch), "reason": reason,
            "systemd": Path("/run/systemd/system").exists()}


def _ver_ge(a: str, b: str) -> bool:
    try:
        return tuple(int(x) for x in a.split(".")) >= tuple(int(x) for x in b.split("."))
    except ValueError:
        return False


def resources() -> dict:
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0]) * 1024
    except Exception:
        pass
    target = BASE if BASE.exists() else Path("/opt") if Path("/opt").exists() else Path("/")
    st = os.statvfs(target)
    return {"cpu_cores": os.cpu_count() or 1, "mem_total": mem.get("MemTotal", 0),
            "mem_available": mem.get("MemAvailable", 0), "swap_total": mem.get("SwapTotal", 0),
            "disk_total": st.f_blocks * st.f_frsize, "disk_free": st.f_bavail * st.f_frsize,
            "disk_path": str(target)}


def tool_versions() -> dict:
    tools = {}
    for name, args in {"docker": ["docker", "--version"], "compose": ["docker", "compose", "version", "--short"],
                       "python3": ["python3", "--version"], "git": ["git", "--version"],
                       "curl": ["curl", "--version"], "wget": ["wget", "--version"], "tar": ["tar", "--version"],
                       "unzip": ["unzip", "-v"], "apt": ["apt-get", "--version"], "gpg": ["gpg", "--version"]}.items():
        if not which(args[0]):
            tools[name] = None
            continue
        code, out = run(args, timeout=15, check=False)
        tools[name] = out.splitlines()[0].strip()[:80] if code == 0 and out else None
    return tools


def firewall_status() -> dict:
    fw = {"ufw": None, "firewalld": None}
    if which("ufw"):
        _, out = run(["ufw", "status"], timeout=10, check=False)
        fw["ufw"] = "active" if "Status: active" in out else "inactive"
    if which("firewall-cmd"):
        _, out = run(["firewall-cmd", "--state"], timeout=10, check=False)
        fw["firewalld"] = out.strip() or "unknown"
    return fw


def network_status() -> dict:
    checks = {}
    for host in ("download.docker.com", "registry-1.docker.io", "github.com", "pypi.org"):
        item = {"dns": dns_ok(host), "https": False, "latency_ms": None}
        if item["dns"]:
            try:
                t0 = time.time()
                status, _, _, _ = http_request("https://%s/" % host, method="HEAD", timeout=6)
                item["https"] = status < 500
                item["latency_ms"] = int((time.time() - t0) * 1000)
            except Exception:
                pass
        checks[host] = item
    return checks


F2B_JAIL = Path("/etc/fail2ban/jail.d/nailong-sshd.local")
F2B_MAXRETRY = 5
F2B_FINDTIME = "10m"
F2B_BANTIME = "1h"


def sshd_ports() -> list[int]:
    """sshd 实际监听的端口（可能不是 22）。"""
    path = which("sshd") or "/usr/sbin/sshd"
    code, out = run([path, "-T"], timeout=10, check=False)
    ports = set()
    if code == 0:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].lower() == "port" and parts[1].isdigit():
                ports.add(int(parts[1]))
    return sorted(ports) or [22]


def fail2ban_jail_text(ports: list[int], systemd: bool) -> str:
    """奶龙的 sshd jail 覆盖文件。删除该文件即可恢复 Fail2Ban 默认行为。"""
    lines = [
        "# 由奶龙生成：SSH 暴力破解防护。删除本文件后执行 fail2ban-client reload 即可撤销。",
        "[sshd]",
        "enabled = true",
        "port = %s" % ",".join(str(p) for p in ports),
        "maxretry = %d" % F2B_MAXRETRY,
        "findtime = %s" % F2B_FINDTIME,
        "bantime = %s" % F2B_BANTIME,
    ]
    if systemd:
        # Ubuntu 的服务名是 ssh.service，新版 OpenSSH 的认证进程叫 sshd-session，所以按进程名匹配
        lines += ["backend = systemd", "journalmatch = _COMM=sshd + _COMM=sshd-session"]
    return "\n".join(lines) + "\n"


def fail2ban_state() -> dict:
    st = {"installed": bool(which("fail2ban-client")), "active": False, "sshd_jail": False,
          "managed": F2B_JAIL.exists(), "banned": 0}
    if not st["installed"]:
        return st
    code, _ = run(["fail2ban-client", "ping"], timeout=10, check=False)
    st["active"] = code == 0
    if st["active"]:
        code, out = run(["fail2ban-client", "status", "sshd"], timeout=10, check=False)
        st["sshd_jail"] = code == 0
        m = re.search(r"Currently banned:\s*(\d+)", out)
        st["banned"] = int(m.group(1)) if m else 0
    return st


def deploy_running() -> bool:
    """部署进程是否还活着（部署在服务器上独立运行，与手机的 SSH 连接无关）。"""
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def read_log_chunk(path: Path, offset: int, max_bytes: int = POLL_MAX_BYTES) -> tuple[str, int]:
    """从字节偏移读取新增日志，只返回完整的行；返回 (文本, 新偏移)。"""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return "", 0
    if offset > size:  # 日志被新一轮部署覆盖
        offset = 0
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(max_bytes)
    cut = data.rfind(b"\n")
    if cut < 0:
        return "", offset
    data = data[:cut + 1]
    return data.decode("utf-8", errors="replace"), offset + len(data)


def start_deploy_detached(cfg_path: Path) -> dict:
    """在服务器上以独立后台任务启动部署：手机切后台、断网、被系统回收都不会中断它。"""
    if deploy_running():
        return {"ok": True, "started": False, "running": True, "message": "部署已在服务器上运行，已接上进度"}
    cfg = read_json(cfg_path, None)
    if not isinstance(cfg, dict):
        raise InstallError("BAD_INPUT", "部署配置无效")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    write_json(DEPLOY_CFG, cfg, 0o600)
    if DEPLOY_LOG.exists():
        os.replace(DEPLOY_LOG, DEPLOY_LOG.with_suffix(".log.1"))
    DEPLOY_LOG.touch(mode=0o600)
    script = str(Path(__file__).resolve())
    cmd = [sys.executable, script, "deploy-run", "--config", str(DEPLOY_CFG)]
    mode = "process"
    if os_info()["systemd"] and which("systemd-run"):
        unit = "nailong-deploy"
        run(["systemctl", "reset-failed", unit], timeout=15, check=False)
        code, out = run(["systemd-run", "--unit", unit, "--collect", "--quiet",
                         "--property=StandardOutput=append:%s" % DEPLOY_LOG,
                         "--property=StandardError=append:%s" % DEPLOY_LOG] + cmd, timeout=30, check=False)
        if code == 0:
            mode = "systemd"
    if mode == "process":
        log_f = open(DEPLOY_LOG, "ab")
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log_f, stderr=log_f, start_new_session=True,
                         close_fds=True)
    for _ in range(40):  # 等部署进程写好 pid
        if deploy_running():
            break
        time.sleep(0.25)
    return {"ok": True, "started": True, "running": deploy_running(), "mode": mode}


def container_logs_fail2ban() -> str:
    _, out = run(["journalctl", "-u", "fail2ban", "-n", "30", "--no-pager"], timeout=15, check=False)
    return out


def sshd_forwarding() -> dict:
    """App 后续通过 SSH 隧道访问 Agent，需要 sshd 允许本地转发。"""
    if not which("sshd"):
        path = "/usr/sbin/sshd"
        if not Path(path).exists():
            return {"known": False}
    else:
        path = which("sshd")
    code, out = run([path, "-T"], timeout=10, check=False)
    if code != 0:
        return {"known": False}
    conf = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            conf[parts[0].lower()] = parts[1].strip()
    allow = conf.get("allowtcpforwarding", "yes").lower()
    disabled = conf.get("disableforwarding", "no").lower() == "yes"
    return {"known": True, "allow_tcp_forwarding": allow, "ok": allow in ("yes", "all", "local") and not disabled}


def classify_containers(containers: list[dict]) -> dict:
    astrbot, napcat, agent = [], [], []
    for c in containers:
        image = c["image"].lower()
        role = (c["labels"] or {}).get("com.nailong.role", "")
        if role == "agent" or c["name"] == "nailong-agent":
            agent.append(c)
        elif role == "astrbot" or "astrbot" in image or any(m["destination"] == "/AstrBot/data" for m in c["mounts"]):
            astrbot.append(c)
        elif role == "napcat" or "napcat" in image or any(m["destination"] == "/app/napcat/config" for m in c["mounts"]):
            napcat.append(c)
    return {"astrbot": astrbot, "napcat": napcat, "agent": agent}


def detect() -> dict:
    report = {"installer_version": VERSION, "time": int(time.time()), "hostname": socket.gethostname(),
              "is_root": os.geteuid() == 0}
    report["os"] = os_info()
    report["resources"] = resources()
    report["tools"] = tool_versions()
    report["firewall"] = firewall_status()
    report["network"] = network_status()
    report["sshd"] = sshd_forwarding()
    report["fail2ban"] = fail2ban_state()
    report["deploy"] = {"running": deploy_running()}
    report["docker"] = {"installed": bool(report["tools"].get("docker")), "running": docker_available(),
                        "compose": bool(report["tools"].get("compose"))}
    report["containers"] = []
    report["networks"] = []
    report["volumes"] = []
    found = {"astrbot": [], "napcat": [], "agent": []}
    if report["docker"]["running"]:
        try:
            info = docker_api("GET", "/info")
            report["docker"]["version"] = info.get("ServerVersion")
            report["docker"]["running_containers"] = info.get("ContainersRunning", 0)
            report["docker"]["registry_mirrors"] = (info.get("RegistryConfig") or {}).get("Mirrors") or []
        except Exception:
            pass
        report["containers"] = list_containers()
        report["networks"] = [n.get("Name") for n in docker_api("GET", "/networks") or []]
        report["volumes"] = [v.get("Name") for v in (docker_api("GET", "/volumes") or {}).get("Volumes") or []]
        found = classify_containers(report["containers"])
    report["existing"] = {k: [c["name"] for c in v] for k, v in found.items()}
    report["listening_ports"] = sorted(listening_ports())
    report["state"] = load_state()
    report["plan"] = make_plan(report)
    return report


def make_plan(report: dict) -> dict:
    """根据现状生成部署方案。已有服务只接管，不重装。"""
    blockers = []
    warnings = []
    osi = report["os"]
    res = report["resources"]
    if not report["is_root"]:
        blockers.append("需要 root 权限（或可用的 sudo）")
    if not osi["supported"]:
        blockers.append(osi["reason"])
    if res["disk_free"] < MIN_FREE_DISK_GB * 1024 ** 3 and not report["existing"]["astrbot"]:
        blockers.append("磁盘剩余空间不足 %d GB（当前 %s）" % (MIN_FREE_DISK_GB, human_size(res["disk_free"])))
    if res["mem_total"] and res["mem_total"] < MIN_MEMORY_MB * 1024 ** 2:
        warnings.append("内存小于 1 GB，NapCat 可能运行不稳定，建议开启 Swap")
    if report["sshd"].get("known") and not report["sshd"].get("ok"):
        blockers.append("SSH 服务禁止了端口转发（AllowTcpForwarding），奶龙需要通过 SSH 隧道安全管理服务器")
    if report["firewall"].get("ufw") == "active":
        warnings.append("检测到 UFW 防火墙已开启；奶龙不会开放任何公网端口，只通过 SSH 隧道连接")

    existing = report["existing"]
    steps = []

    def step(sid, title, action, detail=""):
        steps.append({"id": sid, "title": title, "action": action, "detail": detail})

    missing_tools = [t for t in ("curl", "tar") if not report["tools"].get(t)]
    if not report["tools"].get("gpg") and not report["docker"]["installed"]:
        missing_tools.append("gnupg")
    step("deps", "安装基础依赖", "install" if missing_tools else "skip",
         ("将安装：" + "、".join(missing_tools)) if missing_tools else "依赖已齐全")
    f2b = report.get("fail2ban") or {}
    if f2b.get("active") and f2b.get("sshd_jail") and not f2b.get("managed"):
        step("fail2ban", "Fail2Ban（SSH 防暴力破解）", "keep", "检测到 Fail2Ban 已保护 SSH，保留原有配置")
    elif f2b.get("installed"):
        step("fail2ban", "Fail2Ban（SSH 防暴力破解）", "install", "已安装，补充 SSH 防护规则（连续失败 %d 次封禁 %s）" % (F2B_MAXRETRY, "1 小时"))
    else:
        step("fail2ban", "安装 Fail2Ban（SSH 防暴力破解）", "install", "连续输错 %d 次密码封禁该 IP %s，使用系统官方软件源" % (F2B_MAXRETRY, "1 小时"))
    if report["docker"]["installed"]:
        step("docker", "Docker", "skip", "已安装 %s，跳过安装" % (report["tools"].get("docker") or ""))
        if not report["docker"]["running"]:
            step("docker_start", "启动 Docker", "install", "Docker 已安装但未运行")
    else:
        step("docker", "安装 Docker Engine 与 Compose 插件", "install", "使用 Docker 官方 APT 软件源（GPG 指纹校验）")
    if existing["astrbot"]:
        step("astrbot", "AstrBot", "keep", "检测到已有 AstrBot（%s），保留原有配置和数据" % existing["astrbot"][0])
    else:
        step("astrbot", "部署 AstrBot", "install", "%s:%s" % (IMAGES["astrbot"]["repo"], IMAGES["astrbot"]["tag"]))
    if existing["napcat"]:
        step("napcat", "NapCat", "keep", "检测到已有 NapCat（%s），保留原有配置" % "、".join(existing["napcat"]))
    else:
        step("napcat", "部署 NapCat", "install", "%s:%s" % (IMAGES["napcat"]["repo"], IMAGES["napcat"]["tag"]))
    if existing["astrbot"] and existing["napcat"]:
        step("onebot", "OneBot v11 连接", "keep", "复用现有连接配置，不重置 Token")
    else:
        step("onebot", "配置 OneBot v11 连接", "install", "自动生成随机 Token 并建立反向 WebSocket")
    step("agent", "部署奶龙管理 Agent", "upgrade" if existing["agent"] else "install",
         "仅监听 127.0.0.1，通过 SSH 隧道访问")
    step("verify", "验证服务", "install", "检查容器、端口与连接")
    mode = "fresh"
    if existing["astrbot"] and existing["napcat"]:
        mode = "takeover"
    elif existing["astrbot"] or existing["napcat"] or report["docker"]["installed"]:
        mode = "partial"
    return {"mode": mode, "steps": steps, "blockers": blockers, "warnings": warnings}


# ---------------------------------------------------------------- 部署步骤

class Deployer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.state = load_state()
        self.report: dict = {}
        self.arch = SUPPORTED_ARCH.get(platform.machine(), "amd64")
        src = cfg.get("sources") or {}
        self.docker_apt = [u.rstrip("/") for u in (src.get("docker_apt") or [OFFICIAL_DOCKER_APT])]
        self.registries = [registry_host(r) for r in (src.get("registries") or [OFFICIAL_REGISTRY])]
        if OFFICIAL_REGISTRY not in self.registries:
            self.registries.append(OFFICIAL_REGISTRY)
        self.pypi = [u.rstrip("/") for u in (src.get("pypi") or [OFFICIAL_PYPI])]
        for u in self.docker_apt + self.pypi:
            if not u.startswith("https://"):
                raise InstallError("INSECURE_MIRROR", "下载源必须使用 HTTPS：%s" % u)
        self.allow_docker_restart = bool(cfg.get("allow_docker_restart", False))
        self.tz = cfg.get("timezone") or "Asia/Shanghai"
        if not re.fullmatch(r"[A-Za-z_]+(/[A-Za-z_\-+0-9]+)*", self.tz):
            self.tz = "Asia/Shanghai"

    # -- 框架
    def step(self, sid: str, title: str, fn) -> dict:
        check_cancel()
        emit("step_start", id=sid, title=title)
        t0 = time.time()
        try:
            res = fn() or {}
        except (InstallError, Cancelled):
            raise
        except DockerError as e:
            raise InstallError("DOCKER_ERROR", "Docker 操作失败：%s" % e, "")
        status = res.get("status", "done")
        emit("step_done", id=sid, status=status, message=res.get("message", ""),
             seconds=round(time.time() - t0, 1))
        return res

    def progress(self, sid: str, percent: float | None, message: str = "", **extra) -> None:
        emit("step_progress", id=sid, percent=None if percent is None else round(percent, 1), message=message,
             **extra)

    def run(self) -> dict:
        self.report = detect()
        plan = self.report["plan"]
        if plan["blockers"]:
            raise InstallError("PRECHECK_FAILED", "；".join(plan["blockers"]))
        emit("plan", plan=plan)
        actions = {s["id"]: s["action"] for s in plan["steps"]}
        self.step("deps", "安装基础依赖", self.install_deps)
        if self.cfg.get("fail2ban", True):
            self.step("fail2ban", "配置 Fail2Ban", self.setup_fail2ban)
        else:
            emit("step_done", id="fail2ban", status="skipped", message="已按你的选择跳过")
        if actions.get("docker") == "install":
            self.step("docker", "安装 Docker", self.install_docker)
        elif not docker_available():
            self.step("docker", "启动 Docker", self.start_docker)
        else:
            emit("step_done", id="docker", status="skipped", message="Docker 已安装，跳过")
        self.step("images", "拉取镜像", self.pull_images)
        self.step("astrbot", "部署 AstrBot", self.deploy_astrbot)
        self.step("napcat", "部署 NapCat", self.deploy_napcat)
        self.step("onebot", "配置 OneBot v11", self.configure_onebot)
        self.step("agent", "安装奶龙 Agent", self.deploy_agent)
        self.step("verify", "验证服务", self.verify)
        save_state(self.state)
        return {"ok": True, "mode": plan["mode"], "agent_port": self.state["agent"]["port"],
                "astrbot": self.state.get("astrbot", {}), "napcat": self.state.get("napcat", []),
                "onebot": {k: v for k, v in (self.state.get("onebot") or {}).items() if k != "token"}}

    # -- 依赖
    def apt(self, args: list[str], timeout: int = 1200) -> None:
        for attempt in range(3):
            code, out = run(["apt-get", "-o", "DPkg::Lock::Timeout=120", "-y", "-q"] + args, timeout=timeout,
                            check=False, stream=True)
            if code == 0:
                return
            if "Could not get lock" in out or "Temporary failure" in out:
                time.sleep(5 * (attempt + 1))
                continue
            raise InstallError("APT_FAILED", "软件包安装失败，请检查服务器网络或软件源", out[-1500:])
        raise InstallError("APT_FAILED", "软件包管理器繁忙或网络异常，请稍后重试")

    def setup_fail2ban(self) -> dict:
        """Fail2Ban 是附加的安全加固：失败只给出警告，不中断整个部署。"""
        try:
            return self._fail2ban()
        except InstallError as e:
            log("Fail2Ban 配置失败：%s %s" % (e.message, e.detail[-600:]))
            return {"status": "warning", "message": "Fail2Ban 没有配置成功（%s），不影响其它部署，可稍后手动安装" % e.message}

    def _fail2ban(self) -> dict:
        st = fail2ban_state()
        if st["active"] and st["sshd_jail"] and not st["managed"]:
            self.state["fail2ban"] = {"managed": False}
            save_state(self.state)
            return {"status": "kept", "message": "检测到 Fail2Ban 已保护 SSH，保留原有配置"}
        systemd = bool(os_info()["systemd"] and which("systemctl"))
        if not st["installed"]:
            self.progress("fail2ban", 20, "安装 Fail2Ban")
            self.apt(["update"])
            self.apt(["install", "fail2ban", "iptables"] + (["python3-systemd"] if systemd else []))
        ports = sshd_ports()
        text = fail2ban_jail_text(ports, systemd)
        changed = not F2B_JAIL.exists() or F2B_JAIL.read_text() != text
        if changed:
            backup_file(F2B_JAIL)
            F2B_JAIL.parent.mkdir(parents=True, exist_ok=True)
            F2B_JAIL.write_text(text)
            os.chmod(F2B_JAIL, 0o644)
        code, out = run(["fail2ban-client", "-t"], timeout=60, check=False)
        if code != 0:
            if changed:
                F2B_JAIL.unlink()
            raise InstallError("FAIL2BAN_CONFIG", "Fail2Ban 配置测试未通过，已撤销奶龙的规则", out[-1500:])
        if systemd:
            run(["systemctl", "enable", "fail2ban"], timeout=60, check=False)
            if st["active"] and changed:
                run(["fail2ban-client", "reload"], timeout=60, check=False)
            else:
                run(["systemctl", "restart", "fail2ban"], timeout=90, check=False)
        else:
            run(["service", "fail2ban", "restart"], timeout=90, check=False)
        for _ in range(20):
            check_cancel()
            if fail2ban_state()["sshd_jail"]:
                self.state["fail2ban"] = {"managed": True, "ports": ports}
                save_state(self.state)
                return {"message": "Fail2Ban 已启用：保护 SSH 端口 %s，连续失败 %d 次封禁 %s" % (
                    ",".join(map(str, ports)), F2B_MAXRETRY, "1 小时")}
            time.sleep(2)
        raise InstallError("FAIL2BAN_START", "Fail2Ban 启动后没有加载 SSH 防护", container_logs_fail2ban())

    def install_deps(self) -> dict:
        need = []
        for cmd, pkg in (("curl", "curl"), ("tar", "tar"), ("gpg", "gnupg")):
            if not which(cmd):
                need.append(pkg)
        if not Path("/etc/ssl/certs/ca-certificates.crt").exists():
            need.append("ca-certificates")
        if not need:
            return {"status": "skipped", "message": "依赖已齐全"}
        self.apt(["update"])
        self.apt(["install", "--no-install-recommends"] + need)
        return {"message": "已安装：" + "、".join(need)}

    # -- Docker
    def install_docker(self) -> dict:
        osi = os_info()
        if osi["id"] not in ("ubuntu", "debian"):
            raise InstallError("UNSUPPORTED_OS", osi["reason"] or "不支持的系统")
        # 清理可能冲突的发行版旧包（官方文档要求），不影响数据
        conflicts = [p for p in ("docker.io", "docker-doc", "docker-compose", "podman-docker", "containerd", "runc")
                     if run(["dpkg", "-s", p], check=False)[0] == 0]
        if conflicts:
            self.apt(["remove"] + conflicts)
        keyring = Path("/etc/apt/keyrings/docker.asc")
        keyring.parent.mkdir(parents=True, exist_ok=True)
        last_err = ""
        chosen = None
        codename = osi["codename"] or run(["sh", "-c", ". /etc/os-release; echo $VERSION_CODENAME"],
                                          check=False)[1].strip()
        self.progress("docker", 3, "测速 Docker 软件源")
        for base in rank_by_latency(self.docker_apt, "/linux/%s/gpg" % osi["id"]):
            check_cancel()
            url = "%s/linux/%s/gpg" % (base, osi["id"])
            self.progress("docker", 5, "下载 Docker 软件源密钥：%s" % base)
            try:
                status, _, body, _ = http_request(url, timeout=20, max_bytes=64 * 1024)
                if status != 200:
                    raise InstallError("DOWNLOAD_FAILED", "HTTP %d" % status)
                fp = gpg_fingerprints(body)
                if DOCKER_GPG_FINGERPRINT not in fp:
                    raise InstallError("GPG_MISMATCH", "密钥指纹不匹配，已拒绝该下载源")
                keyring.write_bytes(body)
                os.chmod(keyring, 0o644)
                line = "deb [arch=%s signed-by=%s] %s/linux/%s %s stable\n" % (self.arch, keyring, base, osi["id"],
                                                                                codename)
                Path("/etc/apt/sources.list.d/docker.list").write_text(line)
                self.progress("docker", 15, "更新软件包索引")
                self.apt(["update"])
                chosen = base
                break
            except InstallError as e:
                last_err = "%s：%s" % (base, e.message)
                log("Docker 源不可用：" + last_err)
            except Exception as e:  # noqa: BLE001
                last_err = "%s：%s" % (base, e)
                log("Docker 源不可用：" + last_err)
        if not chosen:
            Path("/etc/apt/sources.list.d/docker.list").unlink(missing_ok=True)
            raise InstallError("DOCKER_SOURCE_FAILED", "无法访问 Docker 软件源，请在设置中添加可信的 Docker APT 镜像",
                               last_err)
        self.progress("docker", 30, "安装 Docker Engine、containerd、Compose 插件")
        self.apt(["install", "--no-install-recommends", "docker-ce", "docker-ce-cli", "containerd.io",
                  "docker-buildx-plugin", "docker-compose-plugin"])
        self.start_docker()
        code, out = run(["docker", "version", "--format", "{{.Server.Version}}"], check=False)
        if code != 0:
            raise InstallError("DOCKER_FAILED", "Docker 安装后无法运行", out)
        return {"message": "Docker %s 已安装并设置开机启动" % out.strip()}

    def start_docker(self) -> dict:
        if os_info()["systemd"] and which("systemctl"):
            run(["systemctl", "enable", "--now", "docker"], check=False, timeout=120)
        elif Path("/etc/init.d/docker").exists():
            run(["/etc/init.d/docker", "start"], check=False, timeout=120)
        for _ in range(30):
            if docker_available():
                return {"message": "Docker 已启动"}
            time.sleep(2)
        raise InstallError("DOCKER_FAILED", "Docker 无法启动，请检查系统日志")

    # -- 镜像
    def pull_images(self) -> dict:
        found = classify_containers(list_containers())
        need = []
        if not found["astrbot"]:
            need.append("astrbot")
        if not found["napcat"]:
            need.append("napcat")
        need.append("python")
        done = []
        for i, key in enumerate(need):
            self.pull_image(key, base_percent=100 * i / len(need), span=100 / len(need))
            done.append("%s:%s" % (IMAGES[key]["repo"].replace("library/", ""), IMAGES[key]["tag"]))
        return {"message": "已就绪：" + "、".join(done)}

    def local_ref(self, key: str) -> str:
        img = IMAGES[key]
        return "%s:%s" % (img["repo"].replace("library/", ""), img["tag"])

    def pull_image(self, key: str, base_percent: float, span: float) -> None:
        img = IMAGES[key]
        ref = self.local_ref(key)
        if any(d.endswith("@" + img["digest"]) for d in image_repo_digests(ref)):
            self.progress("images", base_percent + span, "%s 已存在（摘要已校验）" % ref)
            return
        ranked = rank_registries(self.registries, key, self.arch)
        order = [r["registry"] for r in ranked if r["ok"]] + [r["registry"] for r in ranked if not r["ok"]]
        for r in ranked:
            log("镜像源 %s：%s" % (r["registry"], "可用 %sms" % r["latency_ms"] if r["ok"] else r["error"]))
        errors = []
        for registry in order:
            for attempt in range(2):
                check_cancel()
                source = img["repo"] if registry == OFFICIAL_REGISTRY else "%s/%s" % (registry, img["repo"])
                label = "Docker Hub" if registry == OFFICIAL_REGISTRY else registry
                self.progress("images", base_percent, "正在从 %s 拉取 %s" % (label, ref), source=label)
                try:
                    self._pull_stream(source, img["digest"], base_percent, span, ref)
                    pulled = "%s@%s" % (source, img["digest"])
                    repo, tag = ref.rsplit(":", 1)
                    docker_api("POST", "/images/%s/tag?repo=%s&tag=%s" % (q(pulled), q(repo), q(tag)))
                    self.progress("images", base_percent + span, "%s 拉取完成（摘要已校验）" % ref)
                    return
                except Cancelled:
                    raise
                except Exception as e:  # noqa: BLE001
                    msg = str(e)[:300]
                    errors.append("%s：%s" % (label, msg))
                    log("拉取失败（%s），%s" % (label, msg))
                    self.progress("images", base_percent, "Docker 镜像下载失败，正在尝试备用下载源")
                    time.sleep(min(30, 3 * (2 ** attempt)))
        raise InstallError("IMAGE_PULL_FAILED", "Docker 镜像 %s 下载失败，请在「下载加速」中添加可信的镜像加速器" % ref,
                           "\n".join(errors[-6:]))

    def _pull_stream(self, source: str, digest: str, base_percent: float, span: float, ref: str) -> None:
        layers: dict[str, tuple[int, int]] = {}
        last_emit = 0.0
        t0 = time.time()
        path = "/images/create?fromImage=%s&tag=%s" % (q(source), q(digest))
        for ev in docker_stream("POST", path, timeout=180):
            if ev.get("error"):
                raise RuntimeError(ev["error"])
            lid = ev.get("id")
            det = ev.get("progressDetail") or {}
            if lid and det.get("total"):
                layers[lid] = (det.get("current", 0), det["total"])
            elif lid and ev.get("status") in ("Pull complete", "Already exists", "Download complete") and lid in layers:
                cur, tot = layers[lid]
                layers[lid] = (tot, tot)
            if time.time() - last_emit > 1 and layers:
                cur = sum(c for c, _ in layers.values())
                tot = sum(t for _, t in layers.values()) or 1
                speed = cur / max(time.time() - t0, 0.1)
                self.progress("images", base_percent + span * min(cur / tot, 1), "%s %s / %s" % (
                    ref, human_size(cur), human_size(tot)), speed=int(speed))
                last_emit = time.time()
        if not any(d.endswith("@" + digest) for d in image_repo_digests("%s@%s" % (source, digest))):
            raise RuntimeError("拉取结果摘要校验失败")

    # -- AstrBot
    def _name_for(self, preferred: str, role: str) -> str:
        info = container_inspect(preferred)
        if info is None:
            return preferred
        if (info.get("Config", {}).get("Labels") or {}).get("com.nailong.role") == role:
            return preferred
        return "nailong-" + preferred

    def reserved_ports(self) -> set[int]:
        s = set()
        for key in ("astrbot", "agent"):
            p = (self.state.get(key) or {}).get("port")
            if p:
                s.add(int(p))
        for n in self.state.get("napcat") or []:
            if n.get("webui_port"):
                s.add(int(n["webui_port"]))
        return s

    def deploy_astrbot(self) -> dict:
        found = classify_containers(list_containers())
        if found["astrbot"]:
            c = found["astrbot"][0]
            info = container_inspect(c["name"]) or {}
            if not (info.get("State") or {}).get("Running"):
                log("已有 AstrBot 未运行，尝试启动（不修改配置）")
                docker_api("POST", "/containers/%s/start" % q(c["name"]))
            data_dir = bind_source(info, "/AstrBot/data")
            pub = published_port(info, 6185)
            nets = list(((info.get("NetworkSettings") or {}).get("Networks") or {}).keys())
            self.state["astrbot"] = {"container": c["name"], "managed": c["labels"].get("com.nailong.managed") == "true",
                                     "data_dir": data_dir, "port": pub[1] if pub else None,
                                     "network": next((n for n in nets if n not in ("bridge", "host", "none")),
                                                     nets[0] if nets else "")}
            save_state(self.state)
            return {"status": "kept", "message": "检测到已有 AstrBot，已保留原有配置"}
        ensure_network(NETWORK_NAME)
        name = self._name_for("astrbot", "astrbot")
        data_dir = BASE / "astrbot" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        port = pick_port(6185, self.reserved_ports())
        spec = {
            "Image": self.local_ref("astrbot"),
            "Env": ["TZ=%s" % self.tz],
            "Labels": {"com.nailong.managed": "true", "com.nailong.role": "astrbot"},
            "ExposedPorts": {"6185/tcp": {}},
            "HostConfig": {
                "Binds": ["%s:/AstrBot/data" % data_dir, "/etc/localtime:/etc/localtime:ro"],
                "PortBindings": {"6185/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]},
                "RestartPolicy": {"Name": "always"},
                "SecurityOpt": ["no-new-privileges:true"],
                "NetworkMode": NETWORK_NAME,
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "20m", "max-file": "3"}},
            },
        }
        write_compose_reference(BASE / "astrbot" / "compose.yml", name, spec)
        create_and_start(name, spec)
        self.state["astrbot"] = {"container": name, "managed": True, "data_dir": str(data_dir), "port": port,
                                 "network": NETWORK_NAME}
        save_state(self.state)
        self.progress("astrbot", 50, "等待 AstrBot 启动")
        cfg = data_dir / "cmd_config.json"
        end = time.time() + 240
        while time.time() < end:
            check_cancel()
            if not wait_container_running(name, 5):
                raise InstallError("ASTRBOT_FAILED", "AstrBot 启动失败", container_logs(name))
            if isinstance(read_json(cfg, None), dict) and http_ready("http://127.0.0.1:%d/" % port):
                return {"message": "AstrBot 已启动（WebUI 仅本机 127.0.0.1:%d）" % port}
            time.sleep(3)
        raise InstallError("ASTRBOT_FAILED", "AstrBot 启动超时", container_logs(name))

    # -- NapCat
    def deploy_napcat(self) -> dict:
        found = classify_containers(list_containers())
        astr = self.state.get("astrbot") or {}
        if found["napcat"]:
            rows = []
            for c in found["napcat"]:
                info = container_inspect(c["name"]) or {}
                cfg_dir = bind_source(info, "/app/napcat/config")
                webui = read_json(Path(cfg_dir) / "webui.json", {}) if cfg_dir else {}
                pub = published_port(info, int(webui.get("port") or 6099))
                rows.append({"container": c["name"], "managed": c["labels"].get("com.nailong.managed") == "true",
                             "config_dir": cfg_dir, "webui_port": pub[1] if pub else None,
                             "webui_container_port": int(webui.get("port") or 6099)})
                if webui.get("token"):
                    add_secret(str(webui["token"]))
            self.state["napcat"] = rows
            save_state(self.state)
            return {"status": "kept", "message": "检测到已有 NapCat（%d 个），已保留原有配置" % len(rows)}
        name = self._name_for("napcat", "napcat")
        root = BASE / "napcat"
        cfg_dir = root / "config"
        qq_dir = root / "ntqq"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        qq_dir.mkdir(parents=True, exist_ok=True)
        webui_token = rand_token(24)
        onebot_token = (self.state.get("onebot") or {}).get("token") or rand_token(32)
        add_secret(webui_token)
        add_secret(onebot_token)
        astr_name = astr.get("container") or "astrbot"
        write_json(cfg_dir / "webui.json", {"host": "0.0.0.0", "port": 6099, "prefix": "", "token": webui_token,
                                            "loginRate": 3}, 0o600)
        write_json(cfg_dir / "onebot11.json", napcat_onebot_config("ws://%s:%d/ws" % (astr_name, ASTRBOT_WS_PORT),
                                                                   onebot_token), 0o600)
        port = pick_port(6099, self.reserved_ports())
        network = astr.get("network") or NETWORK_NAME
        ensure_network(network)
        spec = {
            "Image": self.local_ref("napcat"),
            "Env": ["NAPCAT_UID=1000", "NAPCAT_GID=1000", "TZ=%s" % self.tz],
            "Labels": {"com.nailong.managed": "true", "com.nailong.role": "napcat"},
            "ExposedPorts": {"6099/tcp": {}},
            "HostConfig": {
                "Binds": ["%s:/app/napcat/config" % cfg_dir, "%s:/app/.config/QQ" % qq_dir],
                "PortBindings": {"6099/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]},
                "RestartPolicy": {"Name": "always"},
                "NetworkMode": network,
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "20m", "max-file": "3"}},
            },
        }
        write_compose_reference(root / "compose.yml", name, spec)
        create_and_start(name, spec)
        self.state["napcat"] = [{"container": name, "managed": True, "config_dir": str(cfg_dir), "webui_port": port,
                                 "webui_container_port": 6099}]
        self.state["onebot"] = {"token": onebot_token, "url": "ws://%s:%d/ws" % (astr_name, ASTRBOT_WS_PORT),
                                "source": "nailong"}
        save_state(self.state)
        self.progress("napcat", 60, "等待 NapCat 启动")
        end = time.time() + 180
        while time.time() < end:
            check_cancel()
            if not wait_container_running(name, 5):
                raise InstallError("NAPCAT_FAILED", "NapCat 启动失败", container_logs(name))
            if http_ready("http://127.0.0.1:%d/" % port):
                return {"message": "NapCat 已启动，部署完成后在 App 内扫码登录 QQ"}
            time.sleep(3)
        raise InstallError("NAPCAT_FAILED", "NapCat 启动超时", container_logs(name))

    # -- OneBot
    def configure_onebot(self) -> dict:
        astr = self.state.get("astrbot") or {}
        data_dir = Path(astr.get("data_dir") or "")
        cfg_path = data_dir / "cmd_config.json"
        if not astr.get("data_dir") or not cfg_path.exists():
            return {"status": "skipped", "message": "未找到 AstrBot 配置文件，跳过（不影响现有服务）"}
        cfg = None
        for _ in range(30):  # AstrBot 启动时可能正在写配置
            check_cancel()
            cfg = read_json(cfg_path, None)
            if isinstance(cfg, dict):
                break
            time.sleep(2)
        if not isinstance(cfg, dict):
            raise InstallError("ASTRBOT_CONFIG", "AstrBot 配置文件无法解析，已停止以免损坏数据")
        platforms = cfg.get("platform") or []
        existing = [p for p in platforms if isinstance(p, dict) and p.get("type") == "aiocqhttp"]
        onebot = self.state.get("onebot") or {}
        if existing:
            p = next((x for x in existing if x.get("enable")), existing[0])
            if p.get("ws_reverse_token"):
                add_secret(str(p["ws_reverse_token"]))
            self.state["onebot"] = {**onebot, "astrbot_platform_id": p.get("id"),
                                    "port": int(p.get("ws_reverse_port") or ASTRBOT_WS_PORT)}
            # 只有奶龙自己部署的 NapCat 才对齐到已有连接参数；AstrBot 端绝不改动
            ours = [n for n in self.state.get("napcat") or [] if n.get("managed")]
            if ours and onebot.get("source") == "nailong" and p.get("ws_reverse_token") != onebot.get("token"):
                token = p.get("ws_reverse_token") or ""
                for n in ours:
                    f = Path(n["config_dir"]) / "onebot11.json"
                    conf = read_json(f, None)
                    if isinstance(conf, dict):
                        for client in (conf.get("network") or {}).get("websocketClients") or []:
                            client["token"] = token
                            client["url"] = "ws://%s:%d/ws" % (astr["container"], int(p.get("ws_reverse_port") or 6199))
                        write_json(f, conf, 0o600)
                        docker_api("POST", "/containers/%s/restart" % q(n["container"]))
                self.state["onebot"]["token"] = token
                save_state(self.state)
                return {"message": "复用 AstrBot 现有 OneBot 配置，未重置 Token"}
            save_state(self.state)
            return {"status": "kept", "message": "OneBot 已配置，保留现有连接"}
        if not astr.get("managed"):
            # 已有 AstrBot 但没有 OneBot 平台：新增一个平台（不修改其它配置），先备份
            log("为已有 AstrBot 新增 OneBot v11 平台（已备份原配置）")
        token = onebot.get("token") or rand_token(32)
        add_secret(token)
        # 先停止 AstrBot，避免它运行中保存配置覆盖我们的修改；改完再启动
        self.progress("onebot", 30, "暂停 AstrBot 以安全写入配置")
        docker_api("POST", "/containers/%s/stop?t=20" % q(astr["container"]), timeout=90)
        cfg = read_json(cfg_path, None)
        if not isinstance(cfg, dict):
            docker_api("POST", "/containers/%s/start" % q(astr["container"]))
            raise InstallError("ASTRBOT_CONFIG", "AstrBot 配置文件无法解析，已停止以免损坏数据")
        platforms = cfg.get("platform") or []
        bak = backup_file(cfg_path)
        platforms.append({"id": "nailong_onebot", "type": "aiocqhttp", "enable": True, "ws_reverse_host": "0.0.0.0",
                          "ws_reverse_port": ASTRBOT_WS_PORT, "ws_reverse_token": token})
        cfg["platform"] = platforms
        tmp = cfg_path.with_suffix(".json.nailong-tmp")
        st = cfg_path.stat()
        bom = cfg_path.read_bytes().startswith(b"\xef\xbb\xbf")  # 保留 AstrBot 原有的 BOM 格式
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8-sig" if bom else "utf-8")
        os.chown(tmp, st.st_uid, st.st_gid)
        os.chmod(tmp, st.st_mode & 0o777)
        os.replace(tmp, cfg_path)
        self.state["onebot"] = {**onebot, "token": token, "astrbot_platform_id": "nailong_onebot",
                                "port": ASTRBOT_WS_PORT, "backup": str(bak) if bak else ""}
        save_state(self.state)
        self.progress("onebot", 60, "启动 AstrBot 使连接配置生效")
        docker_api("POST", "/containers/%s/start" % q(astr["container"]), timeout=90)
        ip = ""
        end = time.time() + 120
        while time.time() < end:
            check_cancel()
            ip = container_ip(astr["container"])
            if ip and tcp_open(ip, ASTRBOT_WS_PORT):
                return {"message": "OneBot v11 反向 WebSocket 已就绪（随机 Token），QQ 登录后自动连接"}
            time.sleep(3)
        raise InstallError("ONEBOT_FAILED", "AstrBot 的 OneBot 端口未就绪", container_logs(astr["container"]))

    # -- Agent
    def deploy_agent(self) -> dict:
        agent_src = BUNDLE_DIR / "agent"
        if not (agent_src / "nailong_agent" / "main.py").exists():
            raise InstallError("BUNDLE_BROKEN", "安装包不完整（缺少 Agent）")
        root = BASE / "agent"
        app_dir = root / "app"
        deps_dir = root / "deps"
        data_dir = root / "data"
        backups = BASE / "backups"
        for d in (root, data_dir, backups):
            d.mkdir(parents=True, exist_ok=True)
        os.chmod(data_dir, 0o700)
        # 复制源码（覆盖旧版本代码，不动数据）
        if app_dir.exists():
            shutil.rmtree(app_dir)
        shutil.copytree(agent_src, app_dir)
        req = app_dir / "requirements.lock"
        req_hash = hashlib.sha256(req.read_bytes()).hexdigest()
        stamp = deps_dir / ".installed"
        if not (stamp.exists() and stamp.read_text().strip() == req_hash + "|" + self.arch):
            self.install_agent_deps(deps_dir, req_hash)
        old = self.state.get("agent") or {}
        port = old.get("port")
        if not port or (tcp_open("127.0.0.1", int(port)) and not container_inspect("nailong-agent")):
            port = pick_port(18180, self.reserved_ports() - {int(port or 0)})
        astr = self.state.get("astrbot") or {}
        napcats = self.state.get("napcat") or []
        mounts = ["/var/run/docker.sock:/var/run/docker.sock", "%s:/app:ro" % app_dir, "%s:/deps:ro" % deps_dir,
                  "%s:/data" % data_dir, "%s:/backups" % backups] + host_ca_binds()
        osi = os_info()
        agent_cfg = {"version": VERSION, "port": int(port), "astrbot": None, "napcat": [],
                     "backups_dir": "/backups", "sources": self.cfg.get("sources") or {},
                     "server": {"os": osi["pretty"], "arch": osi["arch"], "kernel": osi["kernel"],
                                "hostname": socket.gethostname()}}
        if astr.get("data_dir"):
            mounts.append("%s:/mnt/astrbot" % astr["data_dir"])
            agent_cfg["astrbot"] = {"container": astr["container"], "data_dir": "/mnt/astrbot",
                                    "host_data_dir": astr["data_dir"], "port": astr.get("port")}
        for i, n in enumerate(napcats):
            entry = {"container": n["container"], "webui_port": n.get("webui_port"),
                     "webui_container_port": n.get("webui_container_port", 6099)}
            if n.get("config_dir"):
                mounts.append("%s:/mnt/napcat/%d" % (n["config_dir"], i))
                entry["config_dir"] = "/mnt/napcat/%d" % i
                entry["host_config_dir"] = n["config_dir"]
            agent_cfg["napcat"].append(entry)
        write_json(data_dir / "config.json", agent_cfg, 0o600)
        if container_inspect("nailong-agent"):
            docker_api("DELETE", "/containers/nailong-agent?force=1")
        spec = {
            "Image": self.local_ref("python"),
            "Cmd": ["python", "-m", "uvicorn", "nailong_agent.main:app", "--host", "127.0.0.1", "--port", str(port),
                    "--app-dir", "/app", "--no-server-header", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"],
            "Env": ["PYTHONPATH=/deps:/app", "NAILONG_CONFIG=/data/config.json", "PYTHONDONTWRITEBYTECODE=1",
                    "TZ=%s" % self.tz],
            "WorkingDir": "/app",
            "Labels": {"com.nailong.managed": "true", "com.nailong.role": "agent"},
            "HostConfig": {
                "Binds": mounts,
                "NetworkMode": "host",
                "RestartPolicy": {"Name": "unless-stopped"},
                "SecurityOpt": ["no-new-privileges:true"],
                "ReadonlyRootfs": True,
                "Tmpfs": {"/tmp": "rw,size=64m"},
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "3"}},
            },
        }
        create_and_start("nailong-agent", spec)
        self.state["agent"] = {"port": int(port), "container": "nailong-agent", "version": VERSION}
        save_state(self.state)
        end = time.time() + 60
        while time.time() < end:
            check_cancel()
            try:
                status, _, body, _ = http_plain("http://127.0.0.1:%d/healthz" % port)
                if status == 200 and json.loads(body).get("ok"):
                    return {"message": "Agent 已启动（127.0.0.1:%d，仅本机）" % port}
            except Exception:
                pass
            if not wait_container_running("nailong-agent", 3):
                raise InstallError("AGENT_FAILED", "Agent 启动失败", container_logs("nailong-agent"))
            time.sleep(2)
        raise InstallError("AGENT_FAILED", "Agent 启动超时", container_logs("nailong-agent"))

    def install_agent_deps(self, deps_dir: Path, req_hash: str) -> None:
        tmp = deps_dir.with_name("deps.new")
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        errors = []
        # 先用 App 自带的离线包（同样做哈希校验，零网络）；缺失或失败再走（测速后的）镜像
        sources: list[str | None] = []
        if (BASE / "agent" / "app" / "wheels").is_dir():
            sources.append(None)
        sources += rank_by_latency(self.pypi, "/pip/", 6) if len(self.pypi) > 1 else list(self.pypi)
        for index in sources:
            check_cancel()
            if index is None:
                self.progress("agent", 20, "安装 Agent 依赖（App 内置离线包，哈希校验）")
                net = ["--no-index", "--find-links", "/req/wheels"]
            else:
                self.progress("agent", 20, "安装 Agent 依赖（%s，哈希校验）" % urllib.parse.urlsplit(index).netloc)
                net = ["--index-url", index, "--timeout", "30", "--retries", "3"]
            name = "nailong-pip-%s" % secrets.token_hex(4)
            spec = {
                "Image": self.local_ref("python"),
                "Cmd": ["pip", "install", "--no-cache-dir", "--disable-pip-version-check", "--require-hashes",
                        "--only-binary", ":all:", "--target", "/deps", "-r", "/req/requirements.lock"] + net,
                "Env": ["PIP_CERT=/etc/ssl/certs/ca-certificates.crt"] if host_ca_binds() else [],
                "HostConfig": {"Binds": ["%s:/deps" % tmp, "%s:/req:ro" % (BASE / "agent" / "app")] + host_ca_binds(),
                               "NetworkMode": "host", "AutoRemove": False},
            }
            try:
                docker_api("POST", "/containers/create?name=%s" % name, spec)
                docker_api("POST", "/containers/%s/start" % name)
                res = docker_api("POST", "/containers/%s/wait" % name, timeout=900)
                out = container_logs(name, 60)
                docker_api("DELETE", "/containers/%s?force=1" % name)
                if (res or {}).get("StatusCode") == 0:
                    (tmp / ".installed").write_text(req_hash + "|" + self.arch)
                    if deps_dir.exists():
                        shutil.rmtree(deps_dir)
                    os.replace(tmp, deps_dir)
                    return
                errors.append("%s：%s" % (index, out[-600:]))
                log("依赖安装失败，尝试下一个源")
            except DockerError as e:
                errors.append("%s：%s" % (index, e))
            for f in tmp.iterdir():
                shutil.rmtree(f) if f.is_dir() else f.unlink()
        raise InstallError("AGENT_DEPS_FAILED", "Agent 依赖下载失败，请在「下载加速」中添加可信的 PyPI 镜像",
                           "\n".join(errors[-3:]))

    # -- 验证
    def verify(self) -> dict:
        problems = []
        astr = self.state.get("astrbot") or {}
        if astr.get("container"):
            info = container_inspect(astr["container"]) or {}
            if not (info.get("State") or {}).get("Running"):
                problems.append("AstrBot 未运行")
        for n in self.state.get("napcat") or []:
            info = container_inspect(n["container"]) or {}
            if not (info.get("State") or {}).get("Running"):
                problems.append("%s 未运行" % n["container"])
        port = (self.state.get("agent") or {}).get("port")
        try:
            status, _, _, _ = http_plain("http://127.0.0.1:%d/healthz" % port)
            if status != 200:
                problems.append("Agent 健康检查失败")
        except Exception:
            problems.append("Agent 无法访问")
        # 管理端口只允许本机访问
        for c in list_containers():
            if c["labels"].get("com.nailong.managed") == "true":
                for p in c["ports"]:
                    if p.get("public") and p.get("ip") not in ("127.0.0.1", "::1"):
                        problems.append("%s 端口 %s 对公网开放" % (c["name"], p["public"]))
        if problems:
            raise InstallError("VERIFY_FAILED", "服务验证未通过：" + "；".join(problems))
        return {"message": "全部服务运行正常，未开放任何公网端口"}


def http_plain(url: str, timeout: float = 5) -> tuple[int, dict, bytes, float]:
    """仅用于本机 127.0.0.1 健康检查。"""
    host = urllib.parse.urlsplit(url).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("http_plain 只允许本机地址")
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read(1 << 20), time.time() - t0


def napcat_onebot_config(url: str, token: str) -> dict:
    """与 NapCat-Docker 官方 astrbot 模板一致，只填入 URL 与 Token。"""
    return {
        "network": {
            "httpServers": [], "httpSseServers": [], "httpClients": [], "websocketServers": [],
            "websocketClients": [{
                "enable": True, "name": "nailong-astrbot", "url": url, "reportSelfMessage": False,
                "messagePostFormat": "array", "token": token, "debug": False, "heartInterval": 30000,
                "reconnectInterval": 30000,
            }],
            "plugins": [],
        },
        "musicSignUrl": "", "enableLocalFile2Url": False, "parseMultMsg": False,
    }


def write_compose_reference(path: Path, name: str, spec: dict) -> None:
    """写一份等价的 compose.yml 便于用户手工维护（容器本身由 Docker API 创建）。"""
    hc = spec.get("HostConfig") or {}
    lines = ["# 由奶龙生成，等价于当前容器配置。", "services:", "  %s:" % name,
             "    image: %s" % spec["Image"], "    container_name: %s" % name,
             "    restart: %s" % (hc.get("RestartPolicy") or {}).get("Name", "always")]
    if spec.get("Env"):
        lines.append("    environment:")
        lines += ["      - %s" % e for e in spec["Env"]]
    ports = []
    for cport, binds in (hc.get("PortBindings") or {}).items():
        for b in binds:
            ports.append("%s:%s:%s" % (b.get("HostIp", "127.0.0.1"), b["HostPort"], cport.split("/")[0]))
    if ports:
        lines.append("    ports:")
        lines += ['      - "%s"' % p for p in ports]
    if hc.get("Binds"):
        lines.append("    volumes:")
        lines += ["      - %s" % b for b in hc["Binds"]]
    if hc.get("NetworkMode") not in (None, "host", "bridge"):
        lines += ["    networks:", "      - %s" % hc["NetworkMode"], "networks:", "  %s:" % hc["NetworkMode"],
                  "    external: true"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------- GPG 指纹（OpenPGP 公钥解析）

def _dearmor(data: bytes) -> bytes:
    text = data.decode("ascii", errors="ignore")
    if "BEGIN PGP PUBLIC KEY BLOCK" not in text:
        return data
    body = text.split("BEGIN PGP PUBLIC KEY BLOCK-----", 1)[1].split("-----END", 1)[0]
    lines = [ln.strip() for ln in body.strip().splitlines()]
    # 去掉头部字段与校验和行
    while lines and (":" in lines[0]):
        lines.pop(0)
    lines = [ln for ln in lines if ln and not ln.startswith("=")]
    return base64.b64decode("".join(lines))


def gpg_fingerprints(data: bytes) -> list[str]:
    """计算 OpenPGP v4 公钥/子公钥指纹（RFC 4880 §12.2），不依赖 gpg 命令。"""
    raw = _dearmor(data)
    fps = []
    i = 0
    while i < len(raw):
        tag_byte = raw[i]
        if not tag_byte & 0x80:
            break
        if tag_byte & 0x40:  # 新格式
            tag = tag_byte & 0x3F
            l0 = raw[i + 1]
            if l0 < 192:
                length, hl = l0, 2
            elif l0 < 224:
                length, hl = ((l0 - 192) << 8) + raw[i + 2] + 192, 3
            elif l0 == 255:
                length, hl = int.from_bytes(raw[i + 2:i + 6], "big"), 6
            else:
                break
        else:
            tag = (tag_byte >> 2) & 0x0F
            lt = tag_byte & 0x03
            if lt == 0:
                length, hl = raw[i + 1], 2
            elif lt == 1:
                length, hl = int.from_bytes(raw[i + 1:i + 3], "big"), 3
            elif lt == 2:
                length, hl = int.from_bytes(raw[i + 1:i + 5], "big"), 5
            else:
                break
        body = raw[i + hl:i + hl + length]
        if tag in (6, 14) and body and body[0] == 4:
            fp = hashlib.sha1(b"\x99" + len(body).to_bytes(2, "big") + body).hexdigest().upper()
            fps.append(fp)
        i += hl + length
    return fps


# ---------------------------------------------------------------- 配对与 SSH 公钥

PAIRING_FILE = BASE / "agent" / "data" / "pairing.json"


def pair_code() -> dict:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(alphabet) for _ in range(12))
    data = read_json(PAIRING_FILE, {"codes": []})
    now = time.time()
    codes = [c for c in data.get("codes", []) if c.get("expires", 0) > now and not c.get("used")]
    codes.append({"hash": hashlib.sha256(code.encode()).hexdigest(), "expires": now + 600, "used": False})
    data["codes"] = codes[-5:]
    write_json(PAIRING_FILE, data, 0o600)
    return {"code": code, "expires_in": 600}


_PUBKEY_RE = re.compile(r"^ssh-ed25519 [A-Za-z0-9+/]{68}={0,2}$")
_DEVICE_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{7,63}$")


def _authorized_keys(user: str) -> tuple[Path, pwd.struct_passwd]:
    if not re.fullmatch(r"[a-z_][a-z0-9_\-.]{0,31}\$?", user):
        raise InstallError("BAD_INPUT", "用户名不合法")
    pw = pwd.getpwnam(user)
    return Path(pw.pw_dir) / ".ssh" / "authorized_keys", pw


def authorize_key(user: str, pubkey: str, device_id: str, port: int) -> dict:
    pubkey = pubkey.strip()
    if not _PUBKEY_RE.match(pubkey):
        raise InstallError("BAD_INPUT", "公钥格式不正确（仅接受 ssh-ed25519）")
    if not _DEVICE_RE.match(device_id):
        raise InstallError("BAD_INPUT", "设备 ID 不合法")
    if not 1024 <= int(port) <= 65535:
        raise InstallError("BAD_INPUT", "端口不合法")
    path, pw = _authorized_keys(user)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    os.chown(path.parent, pw.pw_uid, pw.pw_gid)
    comment = "nailong:%s" % device_id
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [ln for ln in lines if not ln.rstrip().endswith(" " + comment)]
    # restrict 关闭一切能力，只重新开启到 Agent 端口的本地转发；
    # command= 强制命令使该密钥无法执行任何 shell 命令。
    lines.append('restrict,port-forwarding,permitopen="127.0.0.1:%d",command="echo nailong-tunnel-only" %s %s'
                 % (int(port), pubkey, comment))
    tmp = path.with_name("authorized_keys.nailong-tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.chown(tmp, pw.pw_uid, pw.pw_gid)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return {"ok": True, "user": user, "device_id": device_id}


def revoke_key(user: str, device_id: str) -> dict:
    if not _DEVICE_RE.match(device_id):
        raise InstallError("BAD_INPUT", "设备 ID 不合法")
    path, pw = _authorized_keys(user)
    if not path.exists():
        return {"ok": True, "removed": 0}
    comment = " nailong:%s" % device_id
    lines = path.read_text().splitlines()
    kept = [ln for ln in lines if not ln.rstrip().endswith(comment)]
    tmp = path.with_name("authorized_keys.nailong-tmp")
    tmp.write_text("\n".join(kept) + ("\n" if kept else ""))
    os.chown(tmp, pw.pw_uid, pw.pw_gid)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return {"ok": True, "removed": len(lines) - len(kept)}


# ---------------------------------------------------------------- 入口

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nailong-installer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect")
    d = sub.add_parser("deploy")
    d.add_argument("--config", required=True)
    ds = sub.add_parser("deploy-start")
    ds.add_argument("--config", required=True)
    dr = sub.add_parser("deploy-run")
    dr.add_argument("--config", required=True)
    dp = sub.add_parser("deploy-poll")
    dp.add_argument("--offset", type=int, default=0)
    sub.add_parser("pair-code")
    a = sub.add_parser("authorize-key")
    a.add_argument("--user", required=True)
    a.add_argument("--pubkey", required=True)
    a.add_argument("--device-id", required=True)
    a.add_argument("--port", type=int, required=True)
    r = sub.add_parser("revoke-key")
    r.add_argument("--user", required=True)
    r.add_argument("--device-id", required=True)
    sub.add_parser("cancel")
    s = sub.add_parser("speedtest")
    s.add_argument("--config", required=True)
    s.add_argument("--fresh", action="store_true")
    args = ap.parse_args(argv)

    def result(obj: dict, code: int = 0) -> int:
        sys.stdout.write("@@RESULT " + redact(json.dumps(obj, ensure_ascii=False)) + "\n")
        sys.stdout.flush()
        return code

    try:
        if args.cmd == "detect":
            return result({"ok": True, "report": detect()})
        if args.cmd == "pair-code":
            if not (BASE / "agent" / "data").exists():
                raise InstallError("NO_AGENT", "Agent 尚未部署")
            return result({"ok": True, **pair_code()})
        if args.cmd == "authorize-key":
            return result(authorize_key(args.user, args.pubkey, args.device_id, args.port))
        if args.cmd == "revoke-key":
            return result(revoke_key(args.user, args.device_id))
        if args.cmd == "cancel":
            try:
                pid = int(PID_FILE.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                return result({"ok": True, "pid": pid})
            except (FileNotFoundError, ProcessLookupError, ValueError):
                return result({"ok": True, "pid": None})
        if args.cmd == "speedtest":
            cfg = read_json(Path(args.config), {})
            regs = [registry_host(x) for x in (cfg.get("sources") or {}).get("registries") or []]
            if OFFICIAL_REGISTRY not in regs:
                regs.append(OFFICIAL_REGISTRY)
            arch = SUPPORTED_ARCH.get(platform.machine(), "amd64")
            return result({"ok": True, "registries": rank_registries(regs, "astrbot", arch, not args.fresh)})
        if args.cmd == "deploy-start":
            return result(start_deploy_detached(Path(args.config)))
        if args.cmd == "deploy-poll":
            text, offset = read_log_chunk(DEPLOY_LOG, max(0, args.offset))
            sys.stdout.write(text)
            sys.stdout.write("@@POLL " + json.dumps({"offset": offset, "running": deploy_running()}) + "\n")
            sys.stdout.flush()
            return 0
        if args.cmd in ("deploy", "deploy-run"):
            cfg = read_json(Path(args.config), None)
            if not isinstance(cfg, dict):
                raise InstallError("BAD_INPUT", "部署配置无效")
            PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            if PID_FILE.exists():
                try:
                    old = int(PID_FILE.read_text())
                    os.kill(old, 0)
                    raise InstallError("BUSY", "已有部署任务正在运行")
                except (ProcessLookupError, ValueError):
                    pass
            PID_FILE.write_text(str(os.getpid()))
            signal.signal(signal.SIGTERM, _on_term)
            # SSH 断开（手机切后台、断网）会发 SIGHUP：必须忽略，部署要继续跑；只有明确“取消”才停止
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            try:
                return result(Deployer(cfg).run())
            finally:
                try:
                    PID_FILE.unlink()
                except FileNotFoundError:
                    pass
        return result({"ok": False, "code": "BAD_INPUT", "message": "未知命令"}, 2)
    except Cancelled:
        emit("cancelled", message="部署已取消，可稍后继续")
        return result({"ok": False, "code": "CANCELLED", "message": "部署已取消，已完成的步骤会保留，可以继续部署"}, 3)
    except InstallError as e:
        emit("error", code=e.code, message=e.message, detail=redact(e.detail)[-3000:])
        return result({"ok": False, "code": e.code, "message": e.message, "detail": redact(e.detail)[-3000:]}, 1)
    except Exception as e:  # noqa: BLE001
        emit("error", code="INTERNAL", message="安装器内部错误", detail=str(e))
        return result({"ok": False, "code": "INTERNAL", "message": "安装器内部错误：%s" % e}, 1)


if __name__ == "__main__":
    sys.exit(main())
