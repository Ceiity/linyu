"""QQ protocol-end management: NapCat and SnowLuma behind one interface.

Model
-----
A *slot* is one bot account.  Slots keep their historical names
(``napcat01`` …) because AstrBot's platform IDs, reverse-WS ports and all
plugin / persona / knowledge data are keyed on them; switching protocol never
touches AstrBot data.

Each slot has exactly one *active* protocol end:

* ``napcat``   → container ``napcatNN`` (legacy, created by lib/napcat.sh)
* ``snowluma`` → container ``snowlumaNN`` (official ``motricseven7/snowluma``
  image, created on demand by :class:`SnowLumaAdapter`)

Both connect to AstrBot the same way – OneBot v11 *reverse WebSocket* to
``ws://<astrbot container>:<slot port>/ws`` with the deployment's reverse-WS
token – because AstrBot's ``aiocqhttp`` adapter is a reverse-WS server.  The
inactive protocol end is always stopped (and NapCat's restart policy is set to
``no``) so the two can never hold the same QQ account at the same time.

State lives in ``<INSTALL_PREFIX>/protocols.json``.
"""
from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shutil
import socket
import tarfile
import threading
import time
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from .host import Host

NAPCAT = "napcat"
SNOWLUMA = "snowluma"
PROTOCOLS = (NAPCAT, SNOWLUMA)
LABELS = {NAPCAT: "NapCat", SNOWLUMA: "SnowLuma"}

SNOWLUMA_DEFAULT_IMAGE = "motricseven7/snowluma:latest"
# Registry prefixes from SnowLuma's own docs (guide/china-network); tried only when Docker Hub fails.
SNOWLUMA_MIRROR_PREFIXES = ("docker.1ms.run/", "docker.xuanyuan.me/", "docker.m.daocloud.io/")
SNOWLUMA_LICENSE = {
    "license": "SnowLuma Source-Available Non-Commercial License 1.0 (2026-06-19)",
    "eula": "SnowLuma EULA 1.1 (2026-07-21)",
    "license_url": "https://github.com/SnowLuma/SnowLuma/blob/main/LICENSE",
    "eula_url": "https://github.com/SnowLuma/SnowLuma/blob/main/EULA.md",
    "privacy_url": "https://github.com/SnowLuma/SnowLuma/blob/main/PRIVACY.md",
    "docs_url": "https://snowluma.github.io/zh/docs/guide/deploy/docker",
    "points": [
        "SnowLuma 是第三方项目，与腾讯 / QQ 无隶属关系，仅限个人或其他非商业用途。",
        "官方镜像内含专有原生组件（snowluma-*.node/.so），本面板不复制、不修改、不重新打包，只拉取官方镜像 motricseven7/snowluma。",
        "EULA 第 5.4 条：把专有组件并入第三方安装包或 Docker 镜像、通过自动化脚本部署、或任何商业用途，需事先取得著作权人书面授权。由面板代为拉取并启动官方镜像属于“自动化脚本部署”，请确认你已取得授权或自行承担合规责任。",
        "使用非官方协议工具接入 QQ 可能违反《QQ 用户协议》并导致账号风险。",
        "SnowLuma WebUI 中的协议同意流程（/api/agreements）由你本人在 SnowLuma WebUI 内完成，面板不会代为同意。",
    ],
}
SNOWLUMA_INTERNAL = {"webui": 5099, "novnc": 6081, "vnc": 5900, "http": 3000, "ws": 3001}
SNOWLUMA_PORT_BASE = {"webui": 15099, "novnc": 16081, "vnc": 15900, "http": 13000}
SNOWLUMA_SCREEN = "1280x800x24"
SNOWLUMA_QQ_FLAGS = "--disable-gpu --disable-software-rasterizer --disable-gpu-compositing"

SLOT_RE = re.compile(r"^napcat(\d+)$")
WS_CLIENT_NAME = "nailong-astrbot"


class ProtocolError(ValueError):
    """Shown to the user as-is."""


class Unsupported(ProtocolError):
    """The protocol end genuinely does not support the operation."""

    code = "UNSUPPORTED"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def slot_number(slot: str) -> int:
    m = SLOT_RE.match(str(slot or ""))
    if not m:
        raise ProtocolError("机器人编号不合法：%s" % slot)
    return int(m.group(1))


def valid_slot(slot: str) -> str:
    slot_number(slot)
    return slot


def snowluma_container_for(slot: str) -> str:
    m = SLOT_RE.match(str(slot or ""))
    if not m:
        raise ProtocolError("机器人编号不合法：%s" % slot)
    return "snowluma" + m.group(1)


def display_name(slot: str) -> str:
    try:
        return "机器人%d" % slot_number(slot)
    except ProtocolError:
        return str(slot)


def mask(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * max(4, len(value) - 6) + value[-3:]


def write_json_atomic(path: Path, data, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.%d" % os.getpid())
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, mode)
    except OSError:
        pass
    os.replace(tmp, path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def http_json(url: str, payload: dict | None = None, headers: dict | None = None, timeout: float = 5.0, method: str = "POST") -> tuple[bool, dict | str]:
    data = json.dumps(payload or {}).encode("utf-8") if method == "POST" else None
    req = urlrequest.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            return False, json.loads(raw)
        except Exception:
            return False, "HTTP %s" % e.code
    except Exception as e:  # URLError, timeout, reset …
        return False, str(getattr(e, "reason", e))
    try:
        return True, json.loads(raw)
    except Exception:
        return False, raw[:300]


def tcp_reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def parse_proc_net_tcp(text: str) -> list[dict]:
    """Parse /proc/net/tcp{,6}. States: 01 ESTABLISHED, 0A LISTEN."""
    rows = []
    for line in str(text or "").splitlines():
        parts = line.split()
        if len(parts) < 4 or ":" not in parts[1] or parts[0] == "sl":
            continue
        try:
            lip, lport = parts[1].split(":")
            rip, rport = parts[2].split(":")
            rows.append({
                "local_ip": _hex_ip(lip), "local_port": int(lport, 16),
                "remote_ip": _hex_ip(rip), "remote_port": int(rport, 16),
                "state": {"01": "ESTABLISHED", "0A": "LISTEN"}.get(parts[3].upper(), parts[3].upper()),
            })
        except ValueError:
            continue
    return rows


def _hex_ip(h: str) -> str:
    if len(h) == 8:
        b = bytes.fromhex(h)[::-1]
        return socket.inet_ntop(socket.AF_INET, b)
    if len(h) == 32:
        raw = bytes.fromhex(h)
        b = b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4))
        ip = socket.inet_ntop(socket.AF_INET6, b)
        if ip.startswith("::ffff:"):
            return ip[7:]
        return ip
    return h


# ---------------------------------------------------------------------------
# persistent state
# ---------------------------------------------------------------------------

class ProtocolStore:
    def __init__(self, host: Host):
        self.host = host
        self.lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self.host.install_prefix / "protocols.json"

    def load(self) -> dict:
        with self.lock:
            data = read_json(self.path, {})
            if not isinstance(data, dict):
                data = {}
            data.setdefault("version", 1)
            if not isinstance(data.get("slots"), dict):
                data["slots"] = {}
            sl = data.get("snowluma")
            if not isinstance(sl, dict):
                sl = {}
            sl.setdefault("image", SNOWLUMA_DEFAULT_IMAGE)
            sl.setdefault("pinned_digest", "")
            sl.setdefault("consent", None)
            if not isinstance(sl.get("instances"), dict):
                sl["instances"] = {}
            data["snowluma"] = sl
            return data

    def save(self, data: dict) -> None:
        with self.lock:
            data["updated_at"] = now_text()
            write_json_atomic(self.path, data)

    def mutate(self, fn):
        with self.lock:
            data = self.load()
            result = fn(data)
            self.save(data)
            return result

    # slots ----------------------------------------------------------------
    def slot(self, slot: str) -> dict:
        row = self.load()["slots"].get(slot)
        return dict(row) if isinstance(row, dict) else {}

    def active(self, slot: str) -> str:
        value = self.slot(slot).get("active")
        return value if value in PROTOCOLS else NAPCAT

    def update_slot(self, slot: str, **patch) -> dict:
        def fn(data):
            row = data["slots"].setdefault(slot, {})
            row.update(patch)
            row["updated_at"] = now_text()
            return dict(row)
        return self.mutate(fn)

    def add_history(self, slot: str, entry: dict) -> None:
        def fn(data):
            row = data["slots"].setdefault(slot, {})
            hist = row.get("history") if isinstance(row.get("history"), list) else []
            hist.append({"time": now_text(), **entry})
            row["history"] = hist[-30:]
        self.mutate(fn)

    def remove_slot(self, slot: str) -> None:
        def fn(data):
            data["slots"].pop(slot, None)
        self.mutate(fn)

    # snowluma -------------------------------------------------------------
    def snowluma(self) -> dict:
        return self.load()["snowluma"]

    def snowluma_instance(self, slot: str) -> dict | None:
        row = self.snowluma()["instances"].get(slot)
        return dict(row) if isinstance(row, dict) else None

    def set_snowluma_instance(self, slot: str, info: dict | None) -> None:
        def fn(data):
            if info is None:
                data["snowluma"]["instances"].pop(slot, None)
            else:
                data["snowluma"]["instances"][slot] = info
        self.mutate(fn)

    def set_consent(self, user: str) -> dict:
        consent = {"user": user, "time": now_text(), "license": SNOWLUMA_LICENSE["license"], "eula": SNOWLUMA_LICENSE["eula"]}

        def fn(data):
            data["snowluma"]["consent"] = consent
        self.mutate(fn)
        return consent

    def set_snowluma_image(self, image: str, pinned_digest: str = "") -> None:
        image = str(image or "").strip() or SNOWLUMA_DEFAULT_IMAGE
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{2,200}", image):
            raise ProtocolError("镜像名称不合法")
        if pinned_digest and not re.fullmatch(r"sha256:[a-f0-9]{64}", pinned_digest):
            raise ProtocolError("镜像校验值必须是 sha256:<64 位十六进制>")

        def fn(data):
            data["snowluma"]["image"] = image
            data["snowluma"]["pinned_digest"] = pinned_digest
        self.mutate(fn)


# ---------------------------------------------------------------------------
# Docker / network helpers shared by both adapters
# ---------------------------------------------------------------------------

class DockerOps:
    def __init__(self, host: Host):
        self.host = host

    def inspect(self, name: str) -> dict:
        code, out = self.host.docker(["inspect", name], timeout=15)
        if code != 0:
            return {}
        try:
            data = json.loads(out)
            return data[0] if isinstance(data, list) and data else {}
        except Exception:
            return {}

    def state(self, name: str) -> dict:
        info = self.inspect(name)
        if not info:
            return {"name": name, "exists": False, "running": False, "status": "missing"}
        st = info.get("State") or {}
        cfg = info.get("Config") or {}
        labels = cfg.get("Labels") or {}
        policy = ((info.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name", "")
        return {
            "name": name, "exists": True, "running": bool(st.get("Running")), "status": st.get("Status", "unknown"),
            "started_at": st.get("StartedAt", ""), "restart_policy": policy, "image": cfg.get("Image", ""),
            "image_id": info.get("Image", ""), "version_label": labels.get("org.opencontainers.image.version", ""),
            "networks": sorted(((info.get("NetworkSettings") or {}).get("Networks") or {}).keys()),
            "ips": {k: (v or {}).get("IPAddress", "") for k, v in (((info.get("NetworkSettings") or {}).get("Networks") or {}).items())},
        }

    def set_restart(self, name: str, policy: str) -> tuple[int, str]:
        return self.host.docker(["update", "--restart=%s" % policy, name], timeout=30)

    def start(self, name: str) -> tuple[int, str]:
        return self.host.docker(["start", name], timeout=120)

    def stop(self, name: str, timeout: int = 30) -> tuple[int, str]:
        return self.host.docker(["stop", "-t", str(timeout), name], timeout=timeout + 60)

    def restart(self, name: str) -> tuple[int, str]:
        return self.host.docker(["restart", name], timeout=180)

    def wait_running(self, name: str, want: bool, seconds: int = 60) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if bool(self.state(name).get("running")) == want:
                return True
            time.sleep(1.5)
        return bool(self.state(name).get("running")) == want

    def exec(self, name: str, args: list[str], timeout: int = 20) -> tuple[int, str]:
        return self.host.docker(["exec", name] + args, timeout=timeout)

    def logs(self, name: str, lines: int = 300, since: str = "") -> str:
        args = ["logs", "--tail", str(max(1, min(int(lines or 300), 5000)))]
        if since:
            args += ["--since", since]
        code, out = self.host.docker(args + [name], timeout=30)
        return out if code == 0 else out

    def ensure_network(self, name: str) -> bool:
        net = self.host.network
        st = self.state(name)
        if not st.get("exists"):
            return False
        if net in (st.get("networks") or []):
            return True
        code, _ = self.host.docker(["network", "connect", net, name], timeout=30)
        return code == 0

    def tcp_table(self, name: str) -> list[dict]:
        code, out = self.exec(name, ["cat", "/proc/net/tcp", "/proc/net/tcp6"], timeout=10)
        if code != 0 and not out:
            return []
        return parse_proc_net_tcp(out)

    def published(self, name: str) -> dict[int, int]:
        """internal port → host port for published TCP ports."""
        info = self.inspect(name)
        ports = ((info.get("NetworkSettings") or {}).get("Ports") or {}) if info else {}
        out: dict[int, int] = {}
        for key, binds in ports.items():
            if not binds or not str(key).endswith("/tcp"):
                continue
            try:
                out[int(str(key).split("/")[0])] = int(binds[0].get("HostPort"))
            except (TypeError, ValueError, IndexError):
                continue
        return out


def endpoint_candidates(host: Host, container: str, internal_port: int, host_port: int | None) -> list[tuple[str, int]]:
    """Where the *panel* can reach a container port.

    systemd panel (default): 127.0.0.1:<published port>.  Panel in Docker on the
    shared network: <container name>:<internal port>.  Both are tried, cheapest
    first, so either deployment works without hard-coding.
    """
    cands: list[tuple[str, int]] = []
    if host.in_docker:
        cands.append((container, int(internal_port)))
    if host_port:
        cands.append(("127.0.0.1", int(host_port)))
    if not host.in_docker:
        cands.append((container, int(internal_port)))
    return cands


# ---------------------------------------------------------------------------
# AstrBot side
# ---------------------------------------------------------------------------

class AstrBotLink:
    def __init__(self, host: Host, docker: DockerOps):
        self.host = host
        self.docker = docker

    def ws_port(self, slot: str) -> int:
        alloc = read_json(self.host.path("PORT_STATE_FILE", self.host.install_prefix / "ports.json"), {})
        row = ((alloc or {}).get("allocations") or {}).get(slot) or {}
        try:
            if row.get("astrbot_ws"):
                return int(row["astrbot_ws"])
        except (TypeError, ValueError):
            pass
        base = 6199
        return base + slot_number(slot) - 1

    def ws_url(self, slot: str) -> str:
        # Docker service DNS name of AstrBot on the shared network – never 127.0.0.1,
        # which inside the protocol container would be the protocol container itself.
        return "ws://%s:%d/ws" % (self.host.astrbot_container, self.ws_port(slot))

    def config_path(self) -> Path:
        return self.host.data_dir / "cmd_config.json"

    def platform(self, slot: str) -> dict | None:
        cfg = read_json(self.config_path(), {})
        for item in (cfg.get("platform") or []) if isinstance(cfg, dict) else []:
            if isinstance(item, dict) and item.get("id") == slot:
                return item
        return None

    def platform_problem(self, slot: str) -> str:
        if not self.config_path().exists():
            return "AstrBot 配置文件不存在（AstrBot 可能尚未部署）"
        p = self.platform(slot)
        if not p:
            return "AstrBot 中没有 %s 的平台配置" % slot
        if p.get("type") != "aiocqhttp":
            return "AstrBot 平台类型不是 aiocqhttp"
        if not p.get("enable", True):
            return "AstrBot 中该平台被禁用"
        try:
            if int(p.get("ws_reverse_port") or 0) != self.ws_port(slot):
                return "AstrBot 平台端口 %s 与分配端口 %s 不一致" % (p.get("ws_reverse_port"), self.ws_port(slot))
        except (TypeError, ValueError):
            return "AstrBot 平台端口无效"
        token = self.host.reverse_token
        if token and str(p.get("ws_reverse_token") or "") != token:
            return "AstrBot 平台 Token 与部署 Token 不一致"
        return ""

    def ensure_platform(self, log=None) -> dict:
        """Run the legacy, idempotent sync (restarts AstrBot only when the config really changes)."""
        code, out = self.host.bash("sync_astrbot_platforms", timeout=400)
        if log:
            log("AstrBot 平台配置同步：%s" % ("完成" if code == 0 else "失败"))
        return {"ok": code == 0, "output": out[-2000:]}

    def link(self, slot: str, peer_container: str = "") -> dict:
        """Is AstrBot listening on the slot port and is the peer connected to it?"""
        port = self.ws_port(slot)
        astrbot = self.host.astrbot_container
        st = self.docker.state(astrbot)
        out = {"port": port, "astrbot_running": bool(st.get("running")), "listening": False, "connected": False, "peers": []}
        if not st.get("running"):
            return out
        rows = self.docker.tcp_table(astrbot)
        out["listening"] = any(r["local_port"] == port and r["state"] == "LISTEN" for r in rows)
        peers = sorted({r["remote_ip"] for r in rows if r["local_port"] == port and r["state"] == "ESTABLISHED"})
        out["peers"] = peers
        if peer_container:
            peer_ips = {ip for ip in (self.docker.state(peer_container).get("ips") or {}).values() if ip}
            out["peer_ips"] = sorted(peer_ips)
            out["connected"] = bool(peer_ips & set(peers))
        else:
            out["connected"] = bool(peers)
        return out


# ---------------------------------------------------------------------------
# Adapter interface
# ---------------------------------------------------------------------------

class ProtocolAdapter:
    """Common management interface.  Methods a protocol end cannot do raise
    :class:`Unsupported` – they never pretend to succeed."""

    kind = ""
    label = ""
    capabilities: dict = {}

    def __init__(self, host: Host, store: ProtocolStore, docker: DockerOps, astrbot: AstrBotLink):
        self.host = host
        self.store = store
        self.docker = docker
        self.astrbot = astrbot

    # identity
    def container(self, slot: str) -> str:
        raise NotImplementedError

    def installed(self, slot: str) -> bool:
        raise NotImplementedError

    # lifecycle
    def install(self, slot: str, log) -> dict:
        raise Unsupported("%s 不支持在此安装" % self.label)

    def update(self, slot: str, log) -> dict:
        raise Unsupported("%s 不支持在此更新" % self.label)

    def uninstall(self, slot: str, keep_data: bool, log) -> dict:
        raise Unsupported("%s 不支持在此卸载" % self.label)

    def repair(self, slot: str, log) -> dict:
        raise Unsupported("%s 不支持在此修复" % self.label)

    def start(self, slot: str) -> dict:
        self._require_installed(slot)
        code, out = self.docker.start(self.container(slot))
        return {"ok": code == 0, "output": out[-1000:]}

    def stop(self, slot: str) -> dict:
        self._require_installed(slot)
        code, out = self.docker.stop(self.container(slot))
        return {"ok": code == 0, "output": out[-1000:]}

    def restart(self, slot: str) -> dict:
        self._require_installed(slot)
        code, out = self.docker.restart(self.container(slot))
        return {"ok": code == 0, "output": out[-1000:]}

    def activate(self, slot: str) -> dict:
        return self.start(slot)

    def deactivate(self, slot: str) -> dict:
        return self.stop(slot)

    # status
    def get_status(self, slot: str) -> dict:
        name = self.container(slot)
        st = self.docker.state(name) if self.installed(slot) else {"name": name, "exists": False, "running": False, "status": "not_installed"}
        st["installed"] = self.installed(slot)
        st["protocol"] = self.kind
        return st

    def get_login_status(self, slot: str, quick: bool = False) -> dict:
        raise NotImplementedError

    def get_version(self, slot: str) -> str:
        st = self.docker.state(self.container(slot))
        if st.get("version_label"):
            return st["version_label"]
        image = str(st.get("image") or "")
        return image.rsplit(":", 1)[-1] if ":" in image else image

    def ready(self, slot: str) -> tuple[bool, str]:
        raise NotImplementedError

    # login
    def request_login(self, slot: str) -> dict:
        raise Unsupported("%s 不支持发起登录" % self.label)

    def get_qrcode(self, slot: str) -> dict:
        raise Unsupported("%s 没有二维码接口" % self.label)

    def refresh_qrcode(self, slot: str) -> dict:
        raise Unsupported("%s 不支持刷新二维码" % self.label)

    def cancel_login(self, slot: str) -> dict:
        raise Unsupported("%s 没有取消登录接口；面板会停止本次登录任务" % self.label)

    # logs / config
    def get_logs(self, slot: str, lines: int = 300, since: str = "") -> str:
        return self.host.redact(self.docker.logs(self.container(slot), lines, since))

    def get_config(self, slot: str) -> dict:
        raise NotImplementedError

    def apply_onebot(self, slot: str, ws_url: str, token: str) -> bool:
        raise NotImplementedError

    def onebot_token_ok(self, slot: str) -> tuple[bool, str]:
        raise NotImplementedError

    def config_dirs(self, slot: str) -> list[Path]:
        raise NotImplementedError

    def _require_installed(self, slot: str) -> None:
        if not self.installed(slot):
            raise ProtocolError("%s 尚未安装到 %s" % (self.label, display_name(slot)))


# ---------------------------------------------------------------------------
# NapCat
# ---------------------------------------------------------------------------

class NapCatAdapter(ProtocolAdapter):
    kind = NAPCAT
    label = "NapCat"
    capabilities = {
        "qr_api": True, "screen_login": False, "install": "legacy", "update": True, "uninstall": "legacy",
        "repair": True, "cancel_login": False,
        "onebot": ["ws_server", "ws_client", "http_server", "http_client"],
        "astrbot_link": "ws_client",
        "notes": "扫码、二维码刷新、登录阶段和错误由 NapCat WebUI 接口提供。新增 / 删除实例在「机器人」页面完成。",
    }

    def row(self, slot: str) -> dict | None:
        for row in self.host.napcat_rows() or []:
            if row.get("name") == slot:
                return row
        return None

    def container(self, slot: str) -> str:
        return slot

    def installed(self, slot: str) -> bool:
        return self.row(slot) is not None

    def config_dirs(self, slot: str) -> list[Path]:
        return [self.host.napcat_base / slot / "config"]

    def compose_file(self, slot: str) -> Path:
        return self.host.napcat_base / slot / "docker-compose.yml"

    def activate(self, slot: str) -> dict:
        self._require_installed(slot)
        self.docker.set_restart(slot, "always")
        code, out = self.docker.start(slot)
        return {"ok": code == 0, "output": out[-1000:]}

    def deactivate(self, slot: str) -> dict:
        self._require_installed(slot)
        # restart=always would bring a stopped NapCat back after a daemon / server
        # reboot and make it fight SnowLuma for the account.
        self.docker.set_restart(slot, "no")
        code, out = self.docker.stop(slot)
        return {"ok": code == 0, "output": out[-1000:]}

    _version_cache: dict = {}

    def get_version(self, slot: str) -> str:
        st = self.docker.state(slot)
        key = (slot, st.get("started_at", ""))
        if key in self._version_cache:
            return self._version_cache[key]
        version = ""
        if st.get("running"):
            code, out = self.host.docker(["logs", "--tail", "4000", slot], timeout=20)
            m = re.findall(r"NapCat\.Core Version:\s*([0-9][\w.+-]*)", out or "")
            if m:
                version = "v" + m[-1]
        if not version:
            version = super().get_version(slot)
            if version in ("latest", "base", ""):
                version = (st.get("image") or "").rsplit("/", 1)[-1]
        if st.get("running") and version.startswith("v"):
            self._version_cache[key] = version
        return version

    def webui(self, slot: str, path: str, timeout: int = 8) -> dict:
        row = self.row(slot)
        if not row:
            raise ProtocolError("NapCat 实例不存在：%s" % slot)
        if not self.host.napcat_webui_call:
            raise ProtocolError("NapCat WebUI 调用不可用")
        return self.host.napcat_webui_call(row, path, None, timeout)

    def ready(self, slot: str) -> tuple[bool, str]:
        if not self.docker.state(slot).get("running"):
            return False, "NapCat 容器未运行"
        try:
            res = self.webui(slot, "/QQLogin/CheckLoginStatus", timeout=4)
        except Exception as e:
            return False, "NapCat WebUI 未就绪：%s" % e
        ok = int(res.get("code", -1)) == 0
        return ok, "NapCat WebUI 正常" if ok else "NapCat WebUI 返回：%s" % (res.get("message") or "未知错误")

    def get_login_status(self, slot: str, quick: bool = False) -> dict:
        out = {"online": False, "uin": "", "nickname": "", "phase": "", "error": None, "source": "napcat_webui"}
        if not self.docker.state(slot).get("running"):
            out["phase"] = "stopped"
            return out
        try:
            res = self.webui(slot, "/QQLogin/CheckLoginStatus", timeout=3 if quick else 6)
        except Exception as e:
            out["phase"] = "unreachable"
            out["detail"] = str(e)
            return out
        data = res.get("data") or {} if int(res.get("code", -1)) == 0 else {}
        out["phase"] = str(data.get("loginPhase") or "")
        out["online"] = bool(data.get("isLogin"))
        out["offline"] = bool(data.get("isOffline"))
        if data.get("loginError"):
            from .login_codes import parse_napcat_login_error
            out["error"] = parse_napcat_login_error(str(data.get("loginError")), out["phase"])
        if out["online"]:
            try:
                info = self.webui(slot, "/QQLogin/GetQQLoginInfo", timeout=4)
                d = info.get("data") or {} if int(info.get("code", -1)) == 0 else {}
                out["uin"] = str(d.get("uin") or "")
                out["nickname"] = str(d.get("nick") or d.get("nickname") or "")
            except Exception:
                pass
        return out

    def _onebot_files(self, slot: str) -> list[Path]:
        cfg = self.host.napcat_base / slot / "config"
        return sorted(cfg.glob("onebot11*.json")) if cfg.exists() else []

    def apply_onebot(self, slot: str, ws_url: str, token: str) -> bool:
        changed = False
        files = self._onebot_files(slot)
        if not files:
            files = [self.host.napcat_base / slot / "config" / "onebot11.json"]
        for path in files:
            data = read_json(path, {})
            if not isinstance(data, dict):
                data = {}
            before = json.dumps(data, sort_keys=True)
            net = data.setdefault("network", {})
            if not isinstance(net, dict):
                net = data["network"] = {}
            clients = net.get("websocketClients")
            if not isinstance(clients, list) or not clients:
                clients = [{"name": "AstrBotReverseWs"}]
            fixed = []
            for item in clients:
                item = item if isinstance(item, dict) else {}
                item["name"] = item.get("name") or "AstrBotReverseWs"
                item["enable"] = True
                item["url"] = ws_url
                item["messagePostFormat"] = item.get("messagePostFormat") or "array"
                item["reportSelfMessage"] = bool(item.get("reportSelfMessage", False))
                item["reconnectInterval"] = int(item.get("reconnectInterval") or 5000)
                item["token"] = token
                item["debug"] = bool(item.get("debug", False))
                item["heartInterval"] = int(item.get("heartInterval") or 30000)
                fixed.append(item)
            net["websocketClients"] = fixed
            for key in ("httpServers", "httpClients", "websocketServers"):
                if not isinstance(net.get(key), list):
                    net[key] = []
            if json.dumps(data, sort_keys=True) != before:
                write_json_atomic(path, data, 0o644)
                changed = True
        return changed

    def onebot_token_ok(self, slot: str) -> tuple[bool, str]:
        token = self.host.reverse_token
        url = self.astrbot.ws_url(slot)
        files = self._onebot_files(slot)
        if not files:
            return False, "NapCat OneBot 配置文件不存在"
        for path in files:
            data = read_json(path, {})
            clients = ((data or {}).get("network") or {}).get("websocketClients") or []
            active = [c for c in clients if isinstance(c, dict) and c.get("enable", True)]
            if not active:
                return False, "%s 没有启用的反向 WebSocket" % path.name
            for c in active:
                if c.get("url") != url:
                    return False, "%s 反向 WS 地址是 %s，应为 %s" % (path.name, c.get("url"), url)
                if token and c.get("token") != token:
                    return False, "%s 的 Token 与 AstrBot 不一致" % path.name
        return True, "反向 WS 地址与 Token 正确"

    def get_config(self, slot: str) -> dict:
        out = {"files": [], "astrbot_ws_url": self.astrbot.ws_url(slot)}
        for path in self._onebot_files(slot):
            data = read_json(path, {})
            net = (data or {}).get("network") or {}
            out["files"].append({
                "file": path.name,
                "ws_clients": [{"url": c.get("url"), "enable": c.get("enable"), "token": mask(c.get("token", ""))} for c in net.get("websocketClients") or [] if isinstance(c, dict)],
                "ws_servers": [{"host": c.get("host"), "port": c.get("port"), "enable": c.get("enable")} for c in net.get("websocketServers") or [] if isinstance(c, dict)],
                "http_servers": [{"host": c.get("host"), "port": c.get("port"), "enable": c.get("enable")} for c in net.get("httpServers") or [] if isinstance(c, dict)],
                "http_clients": [{"url": c.get("url"), "enable": c.get("enable")} for c in net.get("httpClients") or [] if isinstance(c, dict)],
            })
        return out

    def update(self, slot: str, log) -> dict:
        self._require_installed(slot)
        compose = self.compose_file(slot)
        if not compose.exists():
            raise ProtocolError("找不到 %s" % compose)
        backup = backup_dirs(self.host, slot, NAPCAT, self.config_dirs(slot), "pre-update")
        log("已备份配置：%s" % backup)
        active = self.store.active(slot) == NAPCAT
        script = "timeout 900 $(compose_cmd) -f %s pull" % shlex_quote(str(compose))
        if active:
            script += " && timeout 900 $(compose_cmd) -f %s up -d" % shlex_quote(str(compose))
        code, out = self.host.bash(script, timeout=1900)
        log(out[-3000:])
        if code != 0:
            raise ProtocolError("NapCat 更新失败，配置备份在 %s" % backup)
        return {"ok": True, "backup": str(backup), "restarted": active}

    def repair(self, slot: str, log) -> dict:
        self._require_installed(slot)
        changed = self.apply_onebot(slot, self.astrbot.ws_url(slot), self.host.reverse_token)
        log("NapCat 反向 WS 配置%s" % ("已修正" if changed else "无需修改"))
        net = self.docker.ensure_network(slot)
        log("Docker 网络 %s：%s" % (self.host.network, "已连接" if net else "未连接（容器不存在？）"))
        return {"ok": True, "config_changed": changed, "network": net}


# ---------------------------------------------------------------------------
# SnowLuma
# ---------------------------------------------------------------------------

def shlex_quote(s: str) -> str:
    return "'" + str(s).replace("'", "'\"'\"'") + "'"


def backup_dirs(host: Host, slot: str, proto: str, dirs: list[Path], reason: str) -> Path:
    base = host.install_prefix / "backups" / "protocol" / slot
    base.mkdir(parents=True, exist_ok=True)
    target = base / ("%s-%s-%s.tar.gz" % (time.strftime("%Y%m%d_%H%M%S"), proto, reason))
    with tarfile.open(target, "w:gz") as tar:
        for d in dirs:
            if d.exists():
                tar.add(str(d), arcname="%s/%s" % (proto, d.name))
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    old = sorted(base.glob("*-%s-*.tar.gz" % proto))
    for f in old[:-8]:
        f.unlink(missing_ok=True)
    return target


def restore_backup(archive: Path, dirs: list[Path], proto: str) -> None:
    by_name = {d.name: d for d in dirs}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if len(parts) < 3 or parts[0] != proto or parts[1] not in by_name or not member.isfile():
                continue
            if any(p in ("..", "") for p in parts):
                continue
            dest = by_name[parts[1]].joinpath(*parts[2:])
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                continue
            tmp = dest.with_name(dest.name + ".restore")
            tmp.write_bytes(src.read())
            os.replace(tmp, dest)


class SnowLumaAdapter(ProtocolAdapter):
    kind = SNOWLUMA
    label = "SnowLuma"
    capabilities = {
        "qr_api": False, "screen_login": True, "install": True, "update": True, "uninstall": True,
        "repair": True, "cancel_login": False,
        "onebot": ["ws_server", "ws_client", "http_server", "http_client"],
        "astrbot_link": "ws_client",
        "notes": "SnowLuma 只支持在真实 QQ 窗口里扫码（官方无二维码 / 登录接口）。面板通过容器内 VNC 实时显示 QQ 登录窗口，"
                 "扫码与确认仍在手机 QQ 完成；二维码过期 / 拒绝只显示在该窗口里，SnowLuma 不回传错误码。",
    }

    # paths ------------------------------------------------------------------
    def container(self, slot: str) -> str:
        return snowluma_container_for(slot)

    def base_dir(self, slot: str) -> Path:
        return self.host.install_prefix / "snowluma" / self.container(slot)

    def data_dir(self, slot: str) -> Path:
        return self.base_dir(slot) / "data"

    def config_dir(self, slot: str) -> Path:
        return self.data_dir(slot) / "config"

    def config_dirs(self, slot: str) -> list[Path]:
        return [self.config_dir(slot)]

    def compose_file(self, slot: str) -> Path:
        return self.base_dir(slot) / "docker-compose.yml"

    def env_file(self, slot: str) -> Path:
        return self.base_dir(slot) / ".env"

    def instance(self, slot: str) -> dict | None:
        return self.store.snowluma_instance(slot)

    def installed(self, slot: str) -> bool:
        return bool(self.instance(slot)) and self.compose_file(slot).exists()

    # preflight --------------------------------------------------------------
    def preflight(self) -> list[dict]:
        checks = []

        def add(cid, title, ok, detail, level="error"):
            checks.append({"id": cid, "title": title, "ok": ok, "detail": detail, "level": "ok" if ok else level})

        arch = platform.machine().lower()
        add("arch", "CPU 架构", arch in {"x86_64", "amd64", "aarch64", "arm64"}, "%s（官方镜像提供 linux/amd64、linux/arm64）" % arch)
        osname = ""
        try:
            for line in Path("/etc/os-release").read_text().splitlines():
                if line.startswith("PRETTY_NAME="):
                    osname = line.split("=", 1)[1].strip('"')
        except Exception:
            osname = platform.platform()
        add("os", "操作系统", True, osname or "未知")
        code, out = self.host.docker(["version", "--format", "{{.Server.Version}}"], timeout=15)
        add("docker", "Docker", code == 0 and bool(out.strip()), out.strip()[:120] or "Docker 不可用")
        code, out = self.host.bash("$(compose_cmd) version 2>/dev/null | head -n1", timeout=20)
        add("compose", "Docker Compose", code == 0 and bool(out.strip()), out.strip()[:120] or "Docker Compose 不可用")
        mem_mb = 0
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    mem_mb = int(line.split()[1]) // 1024
        except Exception:
            pass
        add("memory", "可用内存", mem_mb >= 1024, "%d MB（每个 SnowLuma 含一个 QQ 客户端，约需 0.5–1 GB）" % mem_mb, "warn")
        try:
            st = shutil.disk_usage(str(self.host.install_prefix if self.host.install_prefix.exists() else "/"))
            free_gb = st.free / 1024 ** 3
        except Exception:
            free_gb = 0
        add("disk", "磁盘空间", free_gb >= 4, "可用 %.1f GB（镜像约 1.5–2 GB）" % free_gb, "warn")
        scope = ""
        try:
            scope = Path("/proc/sys/kernel/yama/ptrace_scope").read_text().strip()
        except Exception:
            scope = "n/a"
        add("ptrace", "ptrace 限制", scope != "3", "kernel.yama.ptrace_scope=%s（3 会直接拒绝注入）" % scope)
        net_ok, net_detail = False, ""
        for url in ("https://registry-1.docker.io/v2/", "https://docker.1ms.run/v2/"):
            ok, res = http_json(url, None, None, timeout=6, method="GET")
            if ok or (isinstance(res, (dict, str)) and ("401" in str(res) or "UNAUTHORIZED" in str(res).upper() or "errors" in str(res))):
                net_ok, net_detail = True, url.split("/")[2] + " 可达"
                break
            net_detail = str(res)[:120]
        add("network", "镜像仓库网络", net_ok, net_detail or "镜像仓库不可达", "warn")
        consent = self.store.snowluma().get("consent")
        add("consent", "许可确认", bool(consent), "已于 %s 由 %s 确认" % (consent.get("time"), consent.get("user")) if consent else "尚未阅读并确认 SnowLuma LICENSE / EULA")
        return checks

    # ports --------------------------------------------------------------------
    def _reserved_ports(self) -> set[int]:
        reserved: set[int] = set()
        ports_file = self.host.path("PORT_STATE_FILE", self.host.install_prefix / "ports.json")
        alloc = (read_json(ports_file, {}) or {}).get("allocations") or {}
        for row in alloc.values():
            if isinstance(row, dict):
                for v in row.values():
                    if isinstance(v, int):
                        reserved.add(v)
        for row in (self.store.snowluma().get("instances") or {}).values():
            for v in (row.get("ports") or {}).values():
                if isinstance(v, int):
                    reserved.add(v)
        for row in self.host.napcat_rows() or []:
            for key in ("webui_port", "ws_port", "http_port"):
                try:
                    reserved.add(int(row.get(key)))
                except (TypeError, ValueError):
                    pass
        code, out = self.host.docker(["ps", "-a", "--format", "{{.Ports}}"], timeout=20)
        for m in re.finditer(r":(\d+)->", out or ""):
            reserved.add(int(m.group(1)))
        return reserved

    @staticmethod
    def _port_free(port: int) -> bool:
        for fam, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET, "0.0.0.0")):
            s = socket.socket(fam, socket.SOCK_STREAM)
            try:
                s.bind((addr, port))
            except OSError:
                return False
            finally:
                s.close()
        return True

    def allocate_ports(self, slot: str) -> dict:
        n = slot_number(slot)
        reserved = self._reserved_ports()
        out = {}
        for key, base in SNOWLUMA_PORT_BASE.items():
            for off in range(0, 3000):
                p = base + n - 1 + off
                if p > 65000:
                    break
                if p in reserved or not self._port_free(p):
                    continue
                out[key] = p
                reserved.add(p)
                break
            if key not in out:
                raise ProtocolError("没有可用端口（%s）" % key)
        return out

    def _record_ports(self, container: str, ports: dict) -> None:
        path = self.host.path("PORT_STATE_FILE", self.host.install_prefix / "ports.json")
        data = read_json(path, {"version": 1, "allocations": {}})
        if not isinstance(data, dict):
            data = {"version": 1, "allocations": {}}
        data.setdefault("allocations", {})
        if ports:
            data["allocations"][container] = {**ports, "protocol": SNOWLUMA, "updated_at": now_text()}
        else:
            data["allocations"].pop(container, None)
        write_json_atomic(path, data, 0o644)

    # files ----------------------------------------------------------------
    def render_compose(self, slot: str, ports: dict, image: str) -> str:
        name = self.container(slot)
        d = self.base_dir(slot)
        tz = self.host.state.get("TZ") or "Asia/Shanghai"
        return """# Generated by 奶龙面板 (Nailong NG 2.0) from SnowLuma's official compose template:
# https://github.com/SnowLuma/SnowLuma.Docker.Framework/blob/main/docker-compose.yml
# Differences: per-account container / data dirs, loopback-only ports, shared bot network.
# SYS_PTRACE + seccomp=unconfined are REQUIRED by SnowLuma (hook injection into QQ);
# no-new-privileges must stay off because the image grants node cap_sys_ptrace via setcap.
services:
  {name}:
    image: ${{SNOWLUMA_IMAGE:-{image}}}
    container_name: {name}
    restart: unless-stopped
    shm_size: 1gb
    ulimits:
      nofile:
        soft: 65536
        hard: 1048576
    cap_add:
      - SYS_PTRACE
    security_opt:
      - seccomp=unconfined
    env_file:
      - .env
    environment:
      TZ: "{tz}"
      SNOWLUMA_ONEBOT_HOST: "0.0.0.0"
      SNOWLUMA_UID: "1000"
      SNOWLUMA_GID: "1000"
      SNOWLUMA_WEBUI_HOST: "0.0.0.0"
      SNOWLUMA_WEBUI_PORT: "5099"
      SNOWLUMA_LOG_LEVEL: "info"
      SNOWLUMA_SCREEN: "{screen}"
      SNOWLUMA_HOOK_AUTOLOAD: "1"
      SNOWLUMA_EXTRA_QQ_HOMES: ""
      SNOWLUMA_QQ_FLAGS: "{flags}"
    ports:
      - "127.0.0.1:{webui}:5099"
      - "127.0.0.1:{novnc}:6081"
      - "127.0.0.1:{vnc}:5900"
      - "127.0.0.1:{http}:3000"
    volumes:
      - {d}/data:/app/data
      - {d}/qq-config:/app/.config
      - {d}/qq-data:/app/.local/share
    networks:
      - {net}
networks:
  {net}:
    external: true
""".format(name=name, image=image, tz=tz, screen=SNOWLUMA_SCREEN, flags=SNOWLUMA_QQ_FLAGS, d=d, net=self.host.network, **ports)

    def write_files(self, slot: str, ports: dict, image: str) -> None:
        d = self.base_dir(slot)
        for sub in ("data/config", "qq-config", "qq-data"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        (d / "slot").write_text(slot + "\n", encoding="utf-8")
        env = self.env_file(slot)
        vnc = ""
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("VNC_PASSWD="):
                    vnc = line.split("=", 1)[1].strip()
        vnc = vnc or secrets.token_urlsafe(15)
        env.write_text("VNC_PASSWD=%s\nSNOWLUMA_IMAGE=%s\n" % (vnc, image), encoding="utf-8")
        os.chmod(env, 0o600)
        compose = self.compose_file(slot)
        compose.write_text(self.render_compose(slot, ports, image), encoding="utf-8")
        os.chmod(compose, 0o600)

    def _onebot_paths(self, slot: str) -> list[Path]:
        cfg = self.config_dir(slot)
        paths = [cfg / "onebot.json"]
        if cfg.exists():
            paths += sorted(p for p in cfg.glob("onebot_*.json") if re.fullmatch(r"onebot_\d+\.json", p.name))
        return paths

    def apply_onebot(self, slot: str, ws_url: str, token: str) -> bool:
        """Write the AstrBot reverse-WS client into the global onebot.json (inherited by
        every account) and into existing per-UIN files.  Server listeners keep their
        own access tokens; they are generated on first write."""
        changed = False
        for path in self._onebot_paths(slot):
            if path.name != "onebot.json" and not path.exists():
                continue
            data = read_json(path, {}) if path.exists() else {}
            if not isinstance(data, dict):
                data = {}
            before = json.dumps(data, sort_keys=True)
            nets = data.get("networks")
            if not isinstance(nets, dict):
                nets = data["networks"] = {}
            if path.name == "onebot.json":
                if not isinstance(nets.get("httpServers"), list):
                    nets["httpServers"] = [{"name": "http-default", "enabled": True, "host": "0.0.0.0", "port": 3000, "path": "/",
                                            "accessToken": secrets.token_urlsafe(32), "messageFormat": "array", "reportSelfMessage": False}]
                if not isinstance(nets.get("wsServers"), list):
                    nets["wsServers"] = [{"name": "ws-default", "enabled": True, "host": "0.0.0.0", "port": 3001, "path": "/", "role": "Universal",
                                          "accessToken": secrets.token_urlsafe(32), "messageFormat": "array", "reportSelfMessage": False}]
                if not isinstance(nets.get("httpClients"), list):
                    nets["httpClients"] = []
                data.setdefault("musicSignUrl", "")
            clients = nets.get("wsClients") if isinstance(nets.get("wsClients"), list) else []
            ours = [c for c in clients if isinstance(c, dict) and c.get("name") == WS_CLIENT_NAME]
            others = [c for c in clients if not (isinstance(c, dict) and c.get("name") == WS_CLIENT_NAME)]
            entry = ours[0] if ours else {"name": WS_CLIENT_NAME}
            entry.update({"enabled": True, "url": ws_url, "role": "Universal", "accessToken": token,
                          "reconnectIntervalMs": int(entry.get("reconnectIntervalMs") or 5000),
                          "messageFormat": entry.get("messageFormat") or "array",
                          "reportSelfMessage": bool(entry.get("reportSelfMessage", False))})
            # Another client pointing at the same AstrBot port would double every event.
            others = [c for c in others if not (isinstance(c, dict) and c.get("url") == ws_url)]
            nets["wsClients"] = [entry] + others
            if json.dumps(data, sort_keys=True) != before:
                write_json_atomic(path, data, 0o644)
                try:
                    os.chown(path, 1000, 1000)
                except (OSError, PermissionError):
                    pass
                changed = True
        return changed

    def onebot_token_ok(self, slot: str) -> tuple[bool, str]:
        token = self.host.reverse_token
        url = self.astrbot.ws_url(slot)
        found = False
        for path in self._onebot_paths(slot):
            if not path.exists():
                continue
            nets = (read_json(path, {}) or {}).get("networks") or {}
            for c in nets.get("wsClients") or []:
                if isinstance(c, dict) and c.get("name") == WS_CLIENT_NAME:
                    found = True
                    if not c.get("enabled", True):
                        return False, "%s 中 AstrBot 反向 WS 被禁用" % path.name
                    if c.get("url") != url:
                        return False, "%s 反向 WS 地址是 %s，应为 %s" % (path.name, c.get("url"), url)
                    if token and c.get("accessToken") != token:
                        return False, "%s 的 Token 与 AstrBot 不一致" % path.name
        if not found:
            return False, "SnowLuma 配置里没有 AstrBot 反向 WebSocket"
        return True, "反向 WS 地址与 Token 正确"

    def http_token(self, slot: str) -> str:
        tokens = []
        for path in reversed(self._onebot_paths(slot)):  # per-UIN overrides global
            if not path.exists():
                continue
            for s in ((read_json(path, {}) or {}).get("networks") or {}).get("httpServers") or []:
                if isinstance(s, dict) and s.get("enabled", True) and int(s.get("port") or 0) == 3000 and s.get("accessToken"):
                    tokens.append(str(s["accessToken"]))
        return tokens[0] if tokens else ""

    def vnc_password(self, slot: str) -> str:
        p = self.config_dir(slot) / "vnc-password"
        try:
            value = p.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
        env = self.env_file(slot)
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("VNC_PASSWD="):
                    return line.split("=", 1)[1].strip()
        return ""

    def ports(self, slot: str) -> dict:
        info = self.instance(slot) or {}
        return dict(info.get("ports") or {})

    def endpoints(self, slot: str, key: str) -> list[tuple[str, int]]:
        return endpoint_candidates(self.host, self.container(slot), SNOWLUMA_INTERNAL[key], self.ports(slot).get(key))

    def onebot_call(self, slot: str, action: str, payload: dict | None = None, timeout: float = 4.0) -> tuple[bool, dict | str]:
        token = self.http_token(slot)
        headers = {"Authorization": "Bearer " + token} if token else {}
        last: dict | str = "OneBot HTTP 不可达"
        for h, p in self.endpoints(slot, "http"):
            ok, res = http_json("http://%s:%d/%s" % (h, p, action.lstrip("/")), payload or {}, headers, timeout)
            if ok:
                return True, res
            last = res
        return False, last

    def supervisor(self, slot: str) -> dict:
        code, out = self.docker.exec(self.container(slot), ["supervisorctl", "status"], timeout=15)
        progs = {}
        for line in (out or "").splitlines():
            parts = line.split()
            if len(parts) >= 2 and re.fullmatch(r"[A-Za-z0-9_.:-]+", parts[0]):
                progs[parts[0]] = parts[1]
        return {"ok": code in (0, 3) and bool(progs), "programs": progs, "raw": (out or "")[-600:]}

    # lifecycle --------------------------------------------------------------
    def _compose(self, slot: str, args: str, timeout: int = 900) -> tuple[int, str]:
        f = self.compose_file(slot)
        return self.host.bash("cd %s && timeout %d $(compose_cmd) -f %s %s" % (shlex_quote(str(f.parent)), timeout, shlex_quote(str(f)), args), timeout=timeout + 60)

    def pull_image(self, image: str, log) -> str:
        code, out = self.host.docker(["pull", image], timeout=1800)
        if code == 0:
            log("已从 Docker Hub 拉取 %s" % image)
            return image
        log("Docker Hub 拉取失败：%s" % out.strip()[-300:])
        if "/" not in image.split(":")[0] or image.startswith(("docker.io/", "motricseven7/")):
            bare = image.removeprefix("docker.io/")
            for prefix in SNOWLUMA_MIRROR_PREFIXES:
                ref = prefix + bare
                log("尝试 SnowLuma 文档列出的镜像加速前缀：%s" % ref)
                code, out = self.host.docker(["pull", ref], timeout=1800)
                if code == 0:
                    self.host.docker(["tag", ref, image], timeout=60)
                    log("已通过 %s 拉取并标记为 %s" % (prefix, image))
                    return image
                log("失败：%s" % out.strip()[-200:])
        raise ProtocolError("拉取 SnowLuma 官方镜像失败，请检查网络或在服务器上配置镜像加速后重试")

    def image_digest(self, image: str) -> dict:
        code, out = self.host.docker(["image", "inspect", "--format", "{{json .RepoDigests}}|{{.Id}}|{{index .Config.Labels \"org.opencontainers.image.version\"}}", image], timeout=30)
        if code != 0:
            return {}
        try:
            repo_digests, image_id, version = out.strip().split("|", 2)
            digests = json.loads(repo_digests) or []
        except Exception:
            return {}
        digest = ""
        for d in digests:
            if "@" in d:
                digest = d.split("@", 1)[1]
                break
        return {"digest": digest, "repo_digests": digests, "id": image_id, "version": version if version != "<no value>" else ""}

    def verify_image(self, image: str, log) -> dict:
        info = self.image_digest(image)
        pinned = self.store.snowluma().get("pinned_digest") or ""
        if pinned:
            digests = [d.split("@", 1)[-1] for d in info.get("repo_digests") or []]
            if pinned not in digests:
                raise ProtocolError("镜像校验失败：期望 %s，实际 %s" % (pinned, info.get("digest") or "无"))
            log("镜像校验通过：%s" % pinned)
        else:
            log("镜像摘要：%s（未设置固定校验值，仅记录）" % (info.get("digest") or "未知"))
        return info

    def install(self, slot: str, log) -> dict:
        valid_slot(slot)
        sl = self.store.snowluma()
        if not sl.get("consent"):
            raise ProtocolError("请先阅读并确认 SnowLuma LICENSE / EULA")
        checks = self.preflight()
        for c in checks:
            log("[%s] %s：%s" % ("OK" if c["ok"] else c["level"].upper(), c["title"], c["detail"]))
        hard = [c for c in checks if not c["ok"] and c["level"] == "error"]
        if hard:
            raise ProtocolError("环境检测未通过：" + "；".join(c["title"] for c in hard))
        if self.installed(slot):
            log("该机器人已安装 SnowLuma，执行修复流程")
            return self.repair(slot, log)
        image = sl.get("image") or SNOWLUMA_DEFAULT_IMAGE
        lock = self.host.extra.get("mutation_lock")
        if lock is not None:
            lock.acquire()
        try:
            ports = self.allocate_ports(slot)
            log("分配端口（仅监听 127.0.0.1）：WebUI %(webui)s · noVNC %(novnc)s · VNC %(vnc)s · OneBot HTTP %(http)s" % ports)
            self._record_ports(self.container(slot), ports)
        finally:
            if lock is not None:
                lock.release()
        self.write_files(slot, ports, image)
        self.apply_onebot(slot, self.astrbot.ws_url(slot), self.host.reverse_token)
        log("已创建目录 %s 并写入 OneBot 配置（反向 WS → %s）" % (self.base_dir(slot), self.astrbot.ws_url(slot)))
        self.pull_image(image, log)
        info = self.verify_image(image, log)
        self.host.bash("ensure_network >/dev/null", timeout=60)
        code, out = self._compose(slot, "up --no-start")
        log(out[-1500:])
        if code != 0:
            raise ProtocolError("创建 SnowLuma 容器失败")
        self.store.set_snowluma_instance(slot, {
            "container": self.container(slot), "dir": str(self.base_dir(slot)), "ports": ports, "image": image,
            "digest": info.get("digest", ""), "image_id": info.get("id", ""), "version": info.get("version", ""),
            "installed_at": now_text(), "updated_at": now_text(),
        })
        log("SnowLuma 已安装但未启动：同一 QQ 账号同一时间只能由一个协议端接管，请在「协议端」页切换后再登录。")
        return {"ok": True, "container": self.container(slot), "ports": ports, "digest": info.get("digest", ""), "started": False}

    def update(self, slot: str, log) -> dict:
        self._require_installed(slot)
        info = self.instance(slot) or {}
        image = self.store.snowluma().get("image") or info.get("image") or SNOWLUMA_DEFAULT_IMAGE
        backup = backup_dirs(self.host, slot, SNOWLUMA, self.config_dirs(slot), "pre-update")
        log("已备份 SnowLuma 配置：%s" % backup)
        self.pull_image(image, log)
        digest = self.verify_image(image, log)
        self.write_files(slot, self.ports(slot), image)
        running = bool(self.docker.state(self.container(slot)).get("running"))
        active = self.store.active(slot) == SNOWLUMA
        code, out = self._compose(slot, "up -d" if (running and active) else "up --no-start")
        log(out[-1500:])
        if code != 0:
            raise ProtocolError("SnowLuma 容器重建失败，配置备份在 %s" % backup)
        info.update({"image": image, "digest": digest.get("digest", ""), "image_id": digest.get("id", ""), "version": digest.get("version", ""), "updated_at": now_text()})
        self.store.set_snowluma_instance(slot, info)
        return {"ok": True, "backup": str(backup), "restarted": running and active, "digest": digest.get("digest", "")}

    def repair(self, slot: str, log) -> dict:
        info = self.instance(slot)
        if not info:
            raise ProtocolError("该机器人尚未安装 SnowLuma")
        ports = self.ports(slot)
        if not ports:
            ports = self.allocate_ports(slot)
            self._record_ports(self.container(slot), ports)
        image = info.get("image") or self.store.snowluma().get("image") or SNOWLUMA_DEFAULT_IMAGE
        self.write_files(slot, ports, image)
        changed = self.apply_onebot(slot, self.astrbot.ws_url(slot), self.host.reverse_token)
        log("OneBot 配置%s" % ("已修正" if changed else "无需修改"))
        active = self.store.active(slot) == SNOWLUMA
        code, out = self._compose(slot, "up -d" if active else "up --no-start")
        log(out[-1500:])
        if active:
            self.docker.ensure_network(self.container(slot))
        info.update({"ports": ports, "updated_at": now_text()})
        self.store.set_snowluma_instance(slot, info)
        return {"ok": code == 0, "config_changed": changed, "running": active}

    def uninstall(self, slot: str, keep_data: bool, log) -> dict:
        if self.store.active(slot) == SNOWLUMA:
            raise ProtocolError("SnowLuma 是该机器人当前使用的协议端，请先切换回 NapCat 再卸载")
        if not self.instance(slot) and not self.base_dir(slot).exists():
            raise ProtocolError("该机器人没有安装 SnowLuma")
        if self.compose_file(slot).exists():
            code, out = self._compose(slot, "down", timeout=300)
            log(out[-1000:])
        else:
            self.host.docker(["rm", "-f", self.container(slot)], timeout=120)
        backup = None
        if self.config_dir(slot).exists():
            backup = backup_dirs(self.host, slot, SNOWLUMA, self.config_dirs(slot), "uninstall")
            log("配置已备份：%s" % backup)
        if not keep_data:
            target = self.base_dir(slot).resolve()
            root = (self.host.install_prefix / "snowluma").resolve()
            if root in target.parents:
                shutil.rmtree(target, ignore_errors=True)
                log("已删除数据目录 %s" % target)
        self.store.set_snowluma_instance(slot, None)
        self._record_ports(self.container(slot), {})
        return {"ok": True, "kept_data": keep_data, "backup": str(backup) if backup else ""}

    def activate(self, slot: str) -> dict:
        self._require_installed(slot)
        self.host.bash("ensure_network >/dev/null", timeout=60)
        code, out = self._compose(slot, "up -d", timeout=600)
        self.docker.ensure_network(self.container(slot))
        return {"ok": code == 0, "output": out[-1000:]}

    def start(self, slot: str) -> dict:
        if self.store.active(slot) != SNOWLUMA:
            raise ProtocolError("该机器人当前使用 NapCat；同一账号不能同时由两个协议端接管，请先切换到 SnowLuma")
        return self.activate(slot)

    def restart(self, slot: str) -> dict:
        if self.store.active(slot) != SNOWLUMA:
            raise ProtocolError("该机器人当前使用 NapCat，SnowLuma 保持停止")
        return super().restart(slot)

    def ready(self, slot: str) -> tuple[bool, str]:
        if not self.docker.state(self.container(slot)).get("running"):
            return False, "SnowLuma 容器未运行"
        sv = self.supervisor(slot)
        progs = sv.get("programs") or {}
        if progs.get("snowluma") != "RUNNING":
            return False, "SnowLuma 进程状态：%s" % (progs.get("snowluma") or "未知")
        if progs.get("qq") != "RUNNING":
            return False, "QQ 客户端进程状态：%s" % (progs.get("qq") or "未知")
        return True, "SnowLuma 与 QQ 客户端进程运行中"

    def get_login_status(self, slot: str, quick: bool = False) -> dict:
        out = {"online": False, "uin": "", "nickname": "", "phase": "", "error": None, "source": "onebot_http"}
        if not self.installed(slot):
            out["phase"] = "not_installed"
            return out
        if not self.docker.state(self.container(slot)).get("running"):
            out["phase"] = "stopped"
            return out
        ok, res = self.onebot_call(slot, "get_login_info", timeout=2.5 if quick else 4)
        if ok and isinstance(res, dict) and res.get("retcode") in (0, "0"):
            d = res.get("data") or {}
            if d.get("user_id"):
                out.update({"online": True, "uin": str(d.get("user_id")), "nickname": str(d.get("nickname") or ""), "phase": "online"})
                return out
        # Per SnowLuma docs the OneBot instance (and its HTTP listener) only exists
        # once an account is logged in, so "not reachable" here means "not logged in".
        out["phase"] = "waiting_login"
        out["detail"] = str(res)[:200] if not ok else ""
        return out

    def get_version(self, slot: str) -> str:
        info = self.instance(slot) or {}
        if info.get("version"):
            return info["version"]
        if self.docker.state(self.container(slot)).get("running"):
            code, out = self.docker.exec(self.container(slot), ["cat", "/app/runtime/package.json"], timeout=10)
            if code == 0:
                try:
                    v = json.loads(out).get("version")
                    if v:
                        return str(v)
                except Exception:
                    pass
        return super().get_version(slot) if self.installed(slot) else ""

    def get_config(self, slot: str) -> dict:
        out = {"files": [], "astrbot_ws_url": self.astrbot.ws_url(slot), "ports": self.ports(slot), "dir": str(self.base_dir(slot))}
        for path in self._onebot_paths(slot):
            if not path.exists():
                continue
            nets = (read_json(path, {}) or {}).get("networks") or {}
            out["files"].append({
                "file": path.name,
                "ws_clients": [{"name": c.get("name"), "url": c.get("url"), "enable": c.get("enabled", True), "token": mask(c.get("accessToken", ""))} for c in nets.get("wsClients") or [] if isinstance(c, dict)],
                "ws_servers": [{"host": c.get("host"), "port": c.get("port"), "enable": c.get("enabled", True), "token": mask(c.get("accessToken", ""))} for c in nets.get("wsServers") or [] if isinstance(c, dict)],
                "http_servers": [{"host": c.get("host"), "port": c.get("port"), "enable": c.get("enabled", True), "token": mask(c.get("accessToken", ""))} for c in nets.get("httpServers") or [] if isinstance(c, dict)],
                "http_clients": [{"url": c.get("url"), "enable": c.get("enabled", True)} for c in nets.get("httpClients") or [] if isinstance(c, dict)],
            })
        return out

    # screen login -------------------------------------------------------------
    def capture_screen(self, slot: str) -> dict:
        from . import rfb
        password = self.vnc_password(slot)
        last = None
        for h, p in self.endpoints(slot, "vnc"):
            try:
                return rfb.capture(h, p, password)
            except Exception as e:  # try next endpoint
                last = e
        raise ProtocolError("无法读取 SnowLuma 远程桌面画面：%s" % (last or "没有可用地址"))

    def click_screen(self, slot: str, x: int, y: int) -> None:
        from . import rfb
        password = self.vnc_password(slot)
        last = None
        for h, p in self.endpoints(slot, "vnc"):
            try:
                rfb.click(h, p, password, x, y)
                return
            except Exception as e:
                last = e
        raise ProtocolError("无法操作 SnowLuma 远程桌面：%s" % (last or "没有可用地址"))
