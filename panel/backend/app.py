#!/usr/bin/env python3
from __future__ import annotations

import base64
import cgi
import hashlib
import hmac
import json
import mimetypes
import ipaddress
import os
import secrets
import re
import shutil
import socket
import subprocess
import threading
import time
import traceback
import zipfile
from dataclasses import dataclass, field
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from urllib import request as urlrequest

APP_VERSION = "2.0.0"
PROJECT_DIR = Path(os.environ.get("PROJECT_DIR", "/opt/astrbot/AstrBot-Deploy"))
INSTALL_PREFIX = Path(os.environ.get("INSTALL_PREFIX", "/opt/astrbot"))
STATE_FILE = Path(os.environ.get("STATE_FILE", str(INSTALL_PREFIX / ".env")))
PANEL_CONFIG = Path(os.environ.get("PANEL_CONFIG", str(INSTALL_PREFIX / "panel_config.json")))
AUDIT_LOG = Path(os.environ.get("PANEL_AUDIT_LOG", str(INSTALL_PREFIX / "logs" / "panel-audit.log")))
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
TASK_LOCK = threading.RLock()
TASKS: dict[str, "Task"] = {}
IP_CACHE = {"public": "", "ts": 0.0}
LOGIN_FAILS: dict[str, list[float]] = {}
NAPCAT_CREDENTIAL_CACHE: dict[str, dict] = {}


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %Z")


def api(ok: bool, data=None, message: str = "", code: str = "") -> dict:
    return {"ok": ok, "data": data, "message": message, "code": code, "time": now(), "version": APP_VERSION}


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return default


def write_json(path: Path, data) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except Exception:
        pass


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000)
    return "pbkdf2_sha256$180000$%s$%s" % (salt, base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        alg, rounds, salt, digest = stored.split("$", 3)
        if alg != "pbkdf2_sha256":
            return False
        raw = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
        return hmac.compare_digest(base64.b64encode(raw).decode(), digest)
    except Exception:
        return False


def default_config() -> dict:
    password = os.environ.get("PANEL_DEFAULT_PASSWORD") or secrets.token_urlsafe(12)
    return {
        "username": "linyu",
        "password_hash": hash_password(password),
        "initial_password": password,
        "session_secret": secrets.token_hex(32),
        "install_prefix": str(INSTALL_PREFIX),
        "project_dir": str(PROJECT_DIR),
        "upload_dir": str(INSTALL_PREFIX / "uploads"),
        "astrbot_plugin_dir": str(INSTALL_PREFIX / "data" / "plugins"),
        "napcat_watchdog_enabled": True,
        "napcat_watchdog_interval": 60,
        "napcat_watchdog_abnormal_threshold": 2,
        "napcat_recovery_max": 3,
        "napcat_recovery_window": 600,
        "napcat_recovery_wait": 25,
        "max_upload_mb": 256,
        "network_name": "astrbot_network",
        "default_reverse_ws_token": "yuyu521521",
        "public_base_url": "",
        "allow_dangerous": False,
        "theme_color": "#2563eb",
        "created_at": now(),
    }


def load_config() -> dict:
    cfg = read_json(PANEL_CONFIG, None)
    if not cfg:
        cfg = default_config()
        write_json(PANEL_CONFIG, cfg)
    base = default_config()
    base.update(cfg)
    return base


def save_config_patch(patch: dict) -> dict:
    cfg = load_config()
    allowed = {"install_prefix", "network_name", "default_reverse_ws_token", "upload_dir", "astrbot_plugin_dir", "napcat_watchdog_enabled", "napcat_watchdog_interval", "napcat_watchdog_abnormal_threshold", "napcat_recovery_max", "napcat_recovery_window", "napcat_recovery_wait", "max_upload_mb", "public_base_url", "allow_dangerous", "theme_color", "username"}
    numeric_limits = {
        "max_upload_mb": (1, 2048),
        "napcat_watchdog_interval": (30, 3600),
        "napcat_watchdog_abnormal_threshold": (1, 10),
        "napcat_recovery_max": (0, 20),
        "napcat_recovery_window": (60, 86400),
        "napcat_recovery_wait": (5, 600),
    }
    for k, v in patch.items():
        if k in allowed:
            if k in numeric_limits:
                lo, hi = numeric_limits[k]
                try:
                    v = int(v)
                except Exception:
                    raise ValueError("%s \u5fc5\u987b\u662f\u6570\u5b57" % k)
                if v < lo or v > hi:
                    raise ValueError("%s \u5fc5\u987b\u5728 %s-%s \u4e4b\u95f4" % (k, lo, hi))
            cfg[k] = v
    if patch.get("password"):
        cfg["password_hash"] = hash_password(str(patch["password"]))
        cfg.pop("initial_password", None)
    write_json(PANEL_CONFIG, cfg)
    return cfg


def sanitize_config(cfg: dict) -> dict:
    out = dict(cfg)
    out.pop("password_hash", None)
    out.pop("session_secret", None)
    return out


def shell_state() -> dict[str, str]:
    data: dict[str, str] = {}
    if STATE_FILE.exists():
        for raw in STATE_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip("'\"")
    cfg = load_config()
    data.setdefault("INSTALL_PREFIX", cfg.get("install_prefix", str(INSTALL_PREFIX)))
    data.setdefault("PROJECT_DIR", cfg.get("project_dir", str(PROJECT_DIR)))
    data.setdefault("NETWORK_NAME", cfg.get("network_name", "astrbot_network"))
    data.setdefault("ASTRBOT_REVERSE_WS_TOKEN", cfg.get("default_reverse_ws_token", "yuyu521521"))
    return data


def run_process(args: list[str], timeout: int = 120, cwd: Path | None = None, input_text: str | None = None) -> tuple[int, str]:
    env = os.environ.copy()
    env.update({"LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"})
    try:
        p = subprocess.run(args, cwd=str(cwd or PROJECT_DIR), text=True, input=input_text, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env)
        return p.returncode, p.stdout[-60000:]
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or "") + "\nTIMEOUT"
    except FileNotFoundError as e:
        return 127, str(e)


def run_process_stream(args: list[str], timeout: int = 120, cwd: Path | None = None, on_line=None) -> tuple[int, str]:
    env = os.environ.copy()
    env.update({"LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"})
    output: list[str] = []
    try:
        if os.name == "nt":
            code, out = run_process(args, timeout=timeout, cwd=cwd)
            if on_line and out:
                for line in out.splitlines()[-80:]:
                    on_line(line)
            return code, out
        import selectors
        p = subprocess.Popen(args, cwd=str(cwd or PROJECT_DIR), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, start_new_session=True, bufsize=1)
        assert p.stdout is not None
        sel = selectors.DefaultSelector()
        sel.register(p.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                try:
                    os.killpg(p.pid, 15)
                except Exception:
                    p.kill()
                output.append("\nTIMEOUT")
                if on_line:
                    on_line("TIMEOUT")
                return 124, "".join(output)[-60000:]
            for key, _ in sel.select(timeout=0.5):
                line = key.fileobj.readline()
                if line:
                    output.append(line)
                    if on_line:
                        on_line(line.rstrip())
            if p.poll() is not None:
                rest = p.stdout.read()
                if rest:
                    output.append(rest)
                    if on_line:
                        for line in rest.splitlines()[-40:]:
                            on_line(line)
                return p.returncode, "".join(output)[-60000:]
    except FileNotFoundError as e:
        return 127, str(e)


def bash(script: str, timeout: int = 120) -> tuple[int, str]:
    prefix = "set -Eeuo pipefail; cd %s; source lib/ops.sh; load_state || true; " % sh_quote(str(PROJECT_DIR))
    return run_process(["bash", "-lc", prefix + script], timeout=timeout, cwd=PROJECT_DIR)


def bash_stream(script: str, timeout: int = 120, on_line=None) -> tuple[int, str]:
    prefix = "set -Eeuo pipefail; cd %s; source lib/ops.sh; load_state || true; " % sh_quote(str(PROJECT_DIR))
    return run_process_stream(["bash", "-lc", prefix + script], timeout=timeout, cwd=PROJECT_DIR, on_line=on_line)


def sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def docker(args: list[str], timeout: int = 60) -> tuple[int, str]:
    return run_process(["docker"] + args, timeout=timeout, cwd=PROJECT_DIR)


def public_ip() -> str:
    if IP_CACHE["public"] and time.time() - IP_CACHE["ts"] < 600:
        return IP_CACHE["public"]
    st = shell_state()
    if st.get("PUBLIC_IP") and st.get("PUBLIC_IP") != "unknown":
        IP_CACHE.update({"public": st["PUBLIC_IP"], "ts": time.time()})
        return st["PUBLIC_IP"]
    deploy = Path(st.get("DEPLOY_INFO_FILE", str(INSTALL_PREFIX / "deploy_info.txt")))
    parsed = parse_deploy_line(deploy, "Public IP")
    if parsed and parsed != "unknown":
        IP_CACHE.update({"public": parsed, "ts": time.time()})
        return parsed
    for url in ["https://api.ipify.org", "https://ifconfig.me/ip"]:
        code, out = run_process(["curl", "-fsSL", "--max-time", "3", url], timeout=5)
        if code == 0 and out.strip():
            IP_CACHE.update({"public": out.strip(), "ts": time.time()})
            return out.strip()
    return "127.0.0.1"


def private_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _first_header(value: str) -> str:
    return (value or "").split(",", 1)[0].strip()


def _clean_host(host: str) -> str:
    host = _first_header(host).strip().strip('"').strip()
    if not host or any(c in host for c in "\r\n/@") or len(host) > 255:
        return ""
    if host.startswith("[") and "]" in host:
        return host
    if not re.match(r"^[A-Za-z0-9.:-]+$", host):
        return ""
    return host


def _split_forwarded(value: str) -> dict[str, str]:
    out: dict[str, str] = {}
    first = _first_header(value)
    for part in first.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().lower()] = v.strip().strip('"')
    return out


def _host_without_port(host: str) -> str:
    host = _clean_host(host)
    if not host:
        return ""
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host


def origin_from_headers(headers=None, fallback_port: int | None = None) -> str:
    cfg = load_config()
    base = str(cfg.get("public_base_url") or "").strip().rstrip("/")
    if headers is None and base.startswith(("http://", "https://")):
        return base
    headers = headers or {}
    fwd = _split_forwarded(headers.get("Forwarded", "")) if hasattr(headers, "get") else {}
    proto = _first_header(fwd.get("proto") or headers.get("X-Forwarded-Proto", ""))
    host = _clean_host(fwd.get("host") or headers.get("X-Forwarded-Host", "") or headers.get("Host", ""))
    if not proto:
        cf_visitor = headers.get("CF-Visitor", "") if hasattr(headers, "get") else ""
        try:
            proto = json.loads(cf_visitor).get("scheme", "") if cf_visitor else ""
        except Exception:
            proto = ""
    if not proto and str(headers.get("X-Forwarded-Ssl", "")).lower() == "on":
        proto = "https"
    proto = proto.lower() if proto.lower() in {"http", "https"} else "http"
    xf_port = _first_header(headers.get("X-Forwarded-Port", "") if hasattr(headers, "get") else "")
    if host and ":" not in host.strip("[]") and xf_port.isdigit():
        if not ((proto == "http" and xf_port == "80") or (proto == "https" and xf_port == "443")):
            host = f"{host}:{xf_port}"
    if not host:
        if base.startswith(("http://", "https://")):
            return base
        ip = public_ip()
        host = ip if ip and ip != "unknown" else private_ip()
        if fallback_port:
            host = f"{host}:{fallback_port}"
    return f"{proto}://{host}".rstrip("/")


def public_origin() -> str:
    return origin_from_headers(None)


def url_for_port(origin: str, port: str | int, path: str = "") -> str:
    port = str(port)
    try:
        from urllib.parse import urlsplit, urlunsplit
        u = urlsplit(origin)
        host = _host_without_port(u.netloc) or u.hostname or public_ip()
        netloc = f"{host}:{port}"
        return urlunsplit((u.scheme or "http", netloc, "/" + path.lstrip("/"), "", ""))
    except Exception:
        return f"{origin.rstrip('/')}:{port}/{path.lstrip('/')}"


def audit(user: str, action: str, detail: dict | None = None, ok: bool = True) -> None:
    ensure_parent(AUDIT_LOG)
    row = {"time": now(), "user": user, "action": action, "ok": ok, "detail": detail or {}}
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


@dataclass
class Task:
    id: str
    title: str
    kind: str
    status: str = "queued"
    progress: int = 0
    logs: list[str] = field(default_factory=list)
    result: dict | None = None
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)

    def line(self, text: str, progress: int | None = None) -> None:
        with TASK_LOCK:
            self.logs.append("[%s] %s" % (now(), text.rstrip()))
            self.logs = self.logs[-500:]
            if progress is not None:
                self.progress = max(0, min(100, progress))
            self.updated_at = now()

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "kind": self.kind, "status": self.status, "progress": self.progress, "logs": self.logs, "result": self.result, "created_at": self.created_at, "updated_at": self.updated_at}


def create_task(title: str, kind: str, func, user: str, *args) -> Task:
    task = Task(id=secrets.token_hex(8), title=title, kind=kind)
    with TASK_LOCK:
        TASKS[task.id] = task

    def runner():
        ok = False
        task.status = "running"
        task.line("任务开始", 5)
        try:
            res = func(task, *args)
            task.result = res if isinstance(res, dict) else {"output": str(res)}
            ok = bool(task.result.get("ok", True))
            task.status = "success" if ok else "failed"
            if ok:
                task.progress = 100
        except Exception as e:
            task.status = "failed"
            task.result = {"ok": False, "message": str(e), "trace": traceback.format_exc()[-8000:]}
            task.line(str(e))
        task.updated_at = now()
        audit(user, kind, {"task": task.id, "status": task.status}, ok)

    threading.Thread(target=runner, daemon=True).start()
    return task


def safe_name(name: str) -> str:
    if not name or not all(c.isalnum() or c in "_.-" for c in name):
        raise ValueError("名称不合法")
    return name


def require_confirm(data: dict, word: str) -> None:
    if str(data.get("confirm", "")) != word:
        raise ValueError("需要二次确认")


def path_under(base: Path, rel: str) -> Path:
    base = base.resolve()
    target = (base / rel.lstrip("/")).resolve()
    if base != target and base not in target.parents:
        raise ValueError("\u8def\u5f84\u4e0d\u5408\u6cd5")
    return target


def ensure_server_file_allowed(path: Path) -> Path:
    target = path.expanduser().resolve()
    cfg = load_config()
    if bool(cfg.get("allow_dangerous")):
        return target
    allowed_roots = [INSTALL_PREFIX.resolve(), PROJECT_DIR.resolve()]
    for root in allowed_roots:
        if target == root or root in target.parents:
            return target
    raise PermissionError("\u5df2\u542f\u7528\u5b89\u5168\u6a21\u5f0f\uff1a\u53ea\u80fd\u6d4f\u89c8 /opt/astrbot \u548c\u9879\u76ee\u76ee\u5f55\u3002\u5982\u9700\u5168\u76d8\u8bbf\u95ee\uff0c\u8bf7\u5728\u7cfb\u7edf\u8bbe\u7f6e\u4e2d\u5f00\u542f\u201c\u5141\u8bb8\u5371\u9669\u64cd\u4f5c\u201d\u3002")


def container_status(name: str) -> dict:
    code, out = docker(["inspect", "-f", "{{json .State}}", name], timeout=10)
    if code != 0:
        return {"name": name, "exists": False, "status": "missing", "running": False}
    try:
        state = json.loads(out)
    except Exception:
        state = {}
    return {"name": name, "exists": True, "status": state.get("Status", "unknown"), "running": state.get("Running", False), "health": state.get("Health", {}).get("Status", "")}


def container_status_many(names: list[str]) -> dict[str, dict]:
    names = [safe_name(n) for n in names if n]
    if not names:
        return {}
    code, out = docker(["inspect", "-f", "{{.Name}}\t{{json .State}}"] + names, timeout=20)
    result: dict[str, dict] = {}
    for line in out.splitlines():
        if "\t" not in line:
            continue
        raw_name, raw_state = line.split("\t", 1)
        name = raw_name.strip().lstrip("/")
        try:
            state = json.loads(raw_state)
        except Exception:
            state = {}
        result[name] = {"name": name, "exists": True, "status": state.get("Status", "unknown"), "running": state.get("Running", False), "health": state.get("Health", {}).get("Status", "")}
    for name in names:
        result.setdefault(name, {"name": name, "exists": False, "status": "missing", "running": False})
    return result


def current_astrbot_password() -> str:
    st = shell_state()
    name = st.get("ASTRBOT_CONTAINER", "astrbot")
    code, out = docker(["logs", "--tail", "1200", name], timeout=20)
    if code == 0 and out:
        matches = re.findall(r"Initial password:\s*([A-Za-z0-9._@#%+=:-]{6,})", out)
        if matches:
            return matches[-1]
        matches = re.findall(r"(?:初始密码|随机初始密码)[^A-Za-z0-9._@#%+=:-]*([A-Za-z0-9._@#%+=:-]{6,})", out)
        if matches:
            return matches[-1]
    deploy = Path(st.get("DEPLOY_INFO_FILE", str(INSTALL_PREFIX / "deploy_info.txt")))
    return parse_deploy_line(deploy, "AstrBot initial random password")


def recovery_status() -> dict:
    paths = [INSTALL_PREFIX / "napcat_recovery_status.json", INSTALL_PREFIX / "logs" / "napcat-watchdog-status.json"]
    for path in paths:
        data = read_json(path, {})
        if isinstance(data, dict):
            bots = data.get("bots", data)
            if isinstance(bots, dict):
                return bots
    return {}


def watchdog_status() -> dict:
    cfg = load_config()
    status_file = INSTALL_PREFIX / "napcat_recovery_status.json"
    data = read_json(status_file, {})
    code, active = run_process(["bash", "-lc", "systemctl is-active astrbot-napcat-watchdog.service 2>/dev/null || true"], timeout=10)
    return {
        "enabled": bool(cfg.get("napcat_watchdog_enabled", True)),
        "service": active.strip(),
        "config": {
            "interval": int(cfg.get("napcat_watchdog_interval", 60) or 60),
            "abnormal_threshold": int(cfg.get("napcat_watchdog_abnormal_threshold", 2) or 2),
            "max_recovery": int(cfg.get("napcat_recovery_max", 3) or 3),
            "recovery_window": int(cfg.get("napcat_recovery_window", 600) or 600),
            "recovery_wait": int(cfg.get("napcat_recovery_wait", 25) or 25),
        },
        "status": data,
        "status_file": str(status_file),
    }


def parse_napcat_index(origin: str | None = None) -> list[dict]:
    st = shell_state()
    origin = origin or public_origin()
    recovery = recovery_status()
    idx = Path(st.get("NAPCAT_INDEX_FILE", str(INSTALL_PREFIX / "napcat_index.tsv")))
    entries: list[list[str]] = []
    if not idx.exists():
        return []
    for line in idx.read_text(encoding="utf-8", errors="replace").splitlines():
        p = line.split("\t")
        if len(p) >= 5 and p[0]:
            entries.append(p)
    statuses = container_status_many([p[0] for p in entries])
    rows = []
    base_dir = Path(st.get("NAPCAT_BASE_DIR", str(INSTALL_PREFIX / "napcat")))
    for p in entries:
        status = statuses.get(p[0]) or {"status":"missing","running":False}
        url = url_for_port(origin, p[1], "webui")
        rows.append({"name": p[0], "webui_port": p[1], "ws_port": p[2], "http_port": p[3], "token": p[4], "url": url, "login_url": url + "?token=" + quote(p[4]), "status": status.get("status"), "running": status.get("running"), "recovery": recovery.get(p[0], {}), "directory": str(base_dir / p[0])})
    return rows


def napcat_row(name: str) -> dict:
    safe = safe_name(name)
    for row in parse_napcat_index():
        if row.get("name") == safe:
            return row
    raise ValueError("机器人不存在：%s" % safe)


def http_json_post(url: str, payload: dict | None = None, headers: dict | None = None, timeout: int = 10) -> dict:
    data = json.dumps(payload or {}).encode("utf-8")
    req = urlrequest.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **(headers or {})})
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def napcat_webui_credential(row: dict, force_refresh: bool = False) -> str:
    name = str(row.get("name") or row.get("webui_port") or "napcat")
    token = str(row.get("token") or "")
    token_hash = hashlib.sha256((token + ".napcat").encode("utf-8")).hexdigest()
    cache = NAPCAT_CREDENTIAL_CACHE.get(name)
    now_ts = time.time()
    if not force_refresh and cache and cache.get("hash") == token_hash and cache.get("expires", 0) > now_ts + 60:
        return str(cache["credential"])
    port = str(row["webui_port"])
    res = http_json_post("http://127.0.0.1:%s/api/auth/login" % port, {"hash": token_hash})
    if int(res.get("code", -1)) != 0:
        msg = str(res.get("message", "unknown"))
        if "rate" in msg.lower():
            raise RuntimeError("NapCat WebUI \u767b\u5f55\u592a\u9891\u7e41\uff0c\u5df2\u89e6\u53d1\u9650\u6d41\u3002\u5f53\u524d\u5b9e\u4f8b\u9700\u8981\u7a0d\u7b49 1-3 \u5206\u949f\uff0c\u6216\u91cd\u542f\u8be5\u673a\u5668\u4eba\u540e\u518d\u70b9\u626b\u7801\u767b\u5f55\u3002")
        raise RuntimeError("NapCat WebUI \u9274\u6743\u5931\u8d25\uff1a%s" % msg)
    cred = (res.get("data") or {}).get("Credential")
    if not cred:
        raise RuntimeError("NapCat WebUI \u6ca1\u6709\u8fd4\u56de Credential")
    NAPCAT_CREDENTIAL_CACHE[name] = {"credential": cred, "hash": token_hash, "expires": now_ts + 3300}
    return cred


def napcat_webui_call(row: dict, path: str, payload: dict | None = None) -> dict:
    port = str(row["webui_port"])
    last = None
    for force in (False, True):
        cred = napcat_webui_credential(row, force_refresh=force)
        last = http_json_post("http://127.0.0.1:%s/api/%s" % (port, path.lstrip("/")), payload or {}, {"Authorization": "Bearer " + cred})
        if int(last.get("code", -1)) != -1 or "Unauthorized" not in str(last.get("message", "")):
            return last
        NAPCAT_CREDENTIAL_CACHE.pop(str(row.get("name") or row.get("webui_port") or "napcat"), None)
    return last or {"code": -1, "message": "NapCat WebUI \u8c03\u7528\u5931\u8d25"}


def qr_svg_for_text(text_value: str) -> str:
    try:
        import qrcode
        import qrcode.image.svg
    except Exception as e:
        raise RuntimeError("\u670d\u52a1\u5668\u7f3a\u5c11\u4e8c\u7ef4\u7801\u5e93\uff1a\u8bf7\u5b89\u88c5 python3-qrcode \u6216 pip install qrcode\u3002\u539f\u59cb\u4e8c\u7ef4\u7801\u5185\u5bb9\uff1a%s" % text_value) from e
    img = qrcode.make(text_value, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    return img.to_string(encoding="unicode")


def system_metrics() -> dict:
    meminfo = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                meminfo[parts[0].rstrip(":")] = int(parts[1])
    except Exception:
        pass
    total = meminfo.get("MemTotal", 0)
    free = meminfo.get("MemAvailable", 0)
    disk_path = str(INSTALL_PREFIX if INSTALL_PREFIX.exists() else Path("/"))
    du = shutil.disk_usage(disk_path)
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
    return {"load": load, "memory": {"total": total * 1024, "available": free * 1024, "used_percent": round((1 - free / total) * 100, 1) if total else 0}, "disk": {"total": du.total, "used": du.used, "free": du.free, "used_percent": round(du.used / du.total * 100, 1)}}


def parse_deploy_line(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    prefix = key + ":"
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def dashboard_data(origin: str | None = None) -> dict:
    st = shell_state()
    deploy = Path(st.get("DEPLOY_INFO_FILE", str(INSTALL_PREFIX / "deploy_info.txt")))
    astr = container_status(st.get("ASTRBOT_CONTAINER", "astrbot"))
    code, docker_ps = docker(["ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"], timeout=20)
    _, ports = run_process(["bash", "-lc", "ss -ltnp 2>/dev/null | head -n 80 || true"], timeout=20)
    recent = AUDIT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-20:] if AUDIT_LOG.exists() else []
    return {"deployed": bool(astr.get("exists")), "public_ip": public_ip(), "private_ip": private_ip(), "deploy_info": deploy.read_text(encoding="utf-8", errors="replace") if deploy.exists() else "尚未部署", "astrbot": astr, "napcats": parse_napcat_index(origin), "docker": {"ok": code == 0, "containers": docker_ps}, "system": system_metrics(), "ports": ports, "recent": recent, "network": st.get("NETWORK_NAME", "astrbot_network")}


def astrbot_data(origin: str | None = None) -> dict:
    st = shell_state()
    origin = origin or public_origin()
    deploy = Path(st.get("DEPLOY_INFO_FILE", str(INSTALL_PREFIX / "deploy_info.txt")))
    return {"status": container_status(st.get("ASTRBOT_CONTAINER", "astrbot")), "url": url_for_port(origin, st.get("ASTRBOT_WEB_PORT", "6185")), "username": st.get("ASTRBOT_USERNAME", "astrbot"), "password": current_astrbot_password(), "token": st.get("ASTRBOT_REVERSE_WS_TOKEN", "yuyu521521"), "config_path": str(INSTALL_PREFIX / "data" / "cmd_config.json"), "deploy_info": deploy.read_text(encoding="utf-8", errors="replace") if deploy.exists() else "尚未部署"}


def get_logs(target: str, lines: int) -> str:
    target = safe_name(target) if target not in {"deploy", "panel"} else target
    if target == "deploy":
        return tail_file(INSTALL_PREFIX / "logs" / "astrbot-deploy.log", lines)
    if target == "panel":
        return tail_file(AUDIT_LOG, lines)
    _, out = docker(["logs", "--tail", str(lines), target], timeout=30)
    return out


def tail_file(path: Path, lines: int) -> str:
    if not path.exists():
        return "\u65e5\u5fd7\u6587\u4ef6\u4e0d\u5b58\u5728"
    lines = max(1, min(int(lines or 300), 5000))
    buf: deque[str] = deque(maxlen=lines)
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            buf.append(line.rstrip("\n"))
    return "\n".join(buf)


def backups_data() -> list[dict]:
    base = INSTALL_PREFIX / "backups"
    base.mkdir(parents=True, exist_ok=True)
    return [{"name": p.name, "size": p.stat().st_size, "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))} for p in sorted(base.glob("*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True)]


def https_status() -> dict:
    st = shell_state()
    domain = st.get("HTTPS_DOMAIN", "")
    url = st.get("HTTPS_PANEL_URL", "https://" + domain if domain else "")
    cert_path = Path("/etc/letsencrypt/live") / domain / "fullchain.pem" if domain else Path("")
    code, nginx = run_process(["bash", "-lc", "systemctl is-active nginx 2>/dev/null || true"], timeout=10)
    code2, certbot = run_process(["bash", "-lc", "command -v certbot >/dev/null 2>&1 && certbot --version || true"], timeout=10)
    return {
        "enabled": bool(domain and cert_path.exists()),
        "domain": domain,
        "url": url,
        "certificate": str(cert_path) if domain else "",
        "nginx": nginx.strip(),
        "certbot": certbot.strip(),
    }


def safe_extract_zip(zip_path: Path, dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    max_files = 300
    max_total = 120 * 1024 * 1024
    max_one = 50 * 1024 * 1024
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        if not members:
            raise ValueError("\u63d2\u4ef6\u538b\u7f29\u5305\u4e3a\u7a7a")
        if len(members) > max_files:
            raise ValueError("\u63d2\u4ef6\u6587\u4ef6\u6570\u8fc7\u591a\uff0c\u8bf7\u63a7\u5236\u5728 300 \u4e2a\u4ee5\u5185")
        total_size = sum(max(0, m.file_size) for m in members)
        if total_size > max_total:
            raise ValueError("\u63d2\u4ef6\u89e3\u538b\u540e\u8fc7\u5927\uff0c\u8bf7\u63a7\u5236\u5728 120MB \u4ee5\u5185")
        root_names = {Path(m.filename.replace("\\", "/")).parts[0] for m in members if Path(m.filename.replace("\\", "/")).parts and not Path(m.filename.replace("\\", "/")).parts[0].startswith("__MACOSX")}
        backup_suffix = ".bak." + time.strftime("%Y%m%d_%H%M%S")
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if info.file_size > max_one:
                raise ValueError("\u63d2\u4ef6\u5355\u4e2a\u6587\u4ef6\u8fc7\u5927\uff1a" + name)
            if not name or name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("\u63d2\u4ef6\u538b\u7f29\u5305\u5305\u542b\u4e0d\u5b89\u5168\u8def\u5f84\uff1a" + name)
        for root in sorted(root_names):
            target = (dest / root).resolve()
            if target.exists():
                shutil.move(str(target), str(target) + backup_suffix)
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.startswith("__MACOSX/"):
                continue
            target = (dest / name).resolve()
            if dest.resolve() != target and dest.resolve() not in target.parents:
                raise ValueError("\u63d2\u4ef6\u89e3\u538b\u8def\u5f84\u8d8a\u754c")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(str(target))
    return extracted

def plugins_data() -> dict:
    cfg = load_config()
    base = Path(cfg.get("astrbot_plugin_dir") or (INSTALL_PREFIX / "data" / "plugins"))
    base.mkdir(parents=True, exist_ok=True)
    plugins = []
    for item in sorted(base.iterdir(), key=lambda x: x.name.lower()):
        try:
            st = item.stat()
            plugins.append({"name": item.name, "path": str(item), "is_dir": item.is_dir(), "size": st.st_size, "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))})
        except FileNotFoundError:
            continue
    return {"base": str(base), "plugins": plugins}


def task_install_plugin(task: Task, src: str, restart: bool) -> dict:
    cfg = load_config()
    source = path_under(Path(cfg["upload_dir"]), src)
    if source.suffix.lower() != ".zip":
        raise ValueError("只支持安装 .zip 插件包")
    plugin_dir = Path(cfg.get("astrbot_plugin_dir") or (INSTALL_PREFIX / "data" / "plugins"))
    task.line("正在解压插件到：%s" % plugin_dir, 25)
    extracted = safe_extract_zip(source, plugin_dir)
    task.line("已解压 %d 个文件" % len(extracted), 70)
    out = ""
    if restart:
        task.line("正在重启 AstrBot 让插件生效", 85)
        _, out = docker(["restart", "astrbot"], timeout=120)
        task.line(out, 95)
    return {"ok": True, "plugin_dir": str(plugin_dir), "files": len(extracted), "output": out}


def list_files(base: Path) -> list[dict]:
    base.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        st = p.stat()
        out.append({"name": p.name, "path": p.name, "is_dir": p.is_dir(), "size": st.st_size, "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)), "type": mimetypes.guess_type(str(p))[0] or "application/octet-stream"})
    return out


def task_shell(task: Task, title: str, script: str, timeout: int) -> dict:
    task.line(title, 15)
    def on_line(line: str):
        if not line:
            return
        progress = None
        low = line.lower()
        if "creating napcat" in low:
            progress = 25
        elif "pull" in low or "download" in low:
            progress = max(task.progress, 35)
        elif "started" in low or "running" in low or "webui" in low:
            progress = max(task.progress, 70)
        elif "deployment info saved" in low or "synced" in low:
            progress = max(task.progress, 90)
        task.line(line, progress)
    code, out = bash_stream(script, timeout=timeout, on_line=on_line)
    if out and (not task.logs or out.splitlines()[-1] not in task.logs[-1]):
        task.line(out, 90)
    return {"ok": code == 0, "output": out}


def task_add_napcat(task: Task, count: int) -> dict:
    task.line("\u6b63\u5728\u51c6\u5907\u521b\u5efa\u673a\u5668\u4eba\uff0c\u4f1a\u81ea\u52a8\u5206\u914d\u7aef\u53e3\u548c\u5bb9\u5668\u76ee\u5f55", 12)
    script = "DOCKER_PULL_TIMEOUT=${DOCKER_PULL_TIMEOUT:-120} add_napcat_instances %d; write_deploy_info" % count
    return task_shell(task, "\u5f00\u59cb\u521b\u5efa NapCat x%d" % count, script, 1800)


def task_apply_no_prefix(task: Task) -> dict:
    task.line("正在应用 AstrBot 群聊免 @ / 免前缀唤醒配置", 20)
    code, out = bash("apply_astrbot_no_prefix_wake; sync_astrbot_platforms; write_deploy_info", timeout=600)
    task.line(out, 90)
    return {"ok": code == 0, "output": out}


def delete_napcat(name: str, keep_data: bool) -> tuple[int, str]:
    st = shell_state()
    base = Path(st.get("NAPCAT_BASE_DIR", str(INSTALL_PREFIX / "napcat")))
    idx = Path(st.get("NAPCAT_INDEX_FILE", str(INSTALL_PREFIX / "napcat_index.tsv")))
    d = base / name
    output = []
    comp = d / "docker-compose.yml"
    if comp.exists():
        code, out = run_process(["bash", "-lc", "docker compose -f %s down --remove-orphans || docker-compose -f %s down --remove-orphans" % (sh_quote(str(comp)), sh_quote(str(comp)))], timeout=240)
        output.append(out)
    else:
        code, out = docker(["rm", "-f", name], timeout=120)
        output.append(out)
    for _ in range(60):
        status = container_status(name)
        if not status.get("exists"):
            output.append("容器已删除：%s" % name)
            break
        time.sleep(1)
    else:
        output.append("等待容器删除超时，已继续清理索引；可稍后刷新查看")
    if not keep_data and d.exists():
        shutil.rmtree(d)
        output.append("数据目录已删除")
    if idx.exists():
        rows = [x for x in idx.read_text(encoding="utf-8", errors="replace").splitlines() if not x.startswith(name + "\t")]
        idx.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    code, out = bash("port_state_remove %s || true; sync_napcat_reverse_configs; sync_astrbot_platforms; write_deploy_info" % sh_quote(name), timeout=420)
    output.append(out)
    return code, "\n".join(output)


def task_delete_napcat(task: Task, name: str, keep_data: bool) -> dict:
    task.line("正在停止并删除 %s" % name, 15)
    code, out = delete_napcat(name, keep_data)
    task.line(out, 85)
    for _ in range(10):
        if not any(r.get("name") == name for r in parse_napcat_index()):
            task.line("机器人索引已更新", 95)
            break
        time.sleep(1)
    return {"ok": code == 0, "output": out}


class Handler(BaseHTTPRequestHandler):
    server_version = "AstrBotPanel/%s" % APP_VERSION

    def log_message(self, fmt, *args):
        return

    def security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: http: https:; connect-src 'self'; frame-src http: https:; object-src 'none'; base-uri 'self'")

    def send_api(self, payload: dict, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.security_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def request_origin(self) -> str:
        return origin_from_headers(self.headers, getattr(self.server, "server_port", None))

    def read_body(self) -> bytes:
        n = int(self.headers.get("Content-Length", "0") or 0)
        return self.rfile.read(n) if n else b""

    def read_json(self) -> dict:
        b = self.read_body()
        return json.loads(b.decode("utf-8")) if b else {}

    def make_session(self, user: str) -> str:
        cfg = load_config()
        payload = base64.urlsafe_b64encode(json.dumps({"user": user, "exp": time.time() + 86400 * 7}).encode()).decode().rstrip("=")
        sig = hmac.new(cfg["session_secret"].encode(), payload.encode(), hashlib.sha256).hexdigest()
        return payload + "." + sig

    def current_user(self) -> str | None:
        cfg = load_config()
        token = ""
        for part in self.headers.get("Cookie", "").split(";"):
            if part.strip().startswith("adb_session="):
                token = part.strip().split("=", 1)[1]
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        if "." not in token:
            return None
        payload, sig = token.rsplit(".", 1)
        good = hmac.new(cfg["session_secret"].encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, sig):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(payload + "===").decode())
            return data["user"] if data.get("exp", 0) > time.time() else None
        except Exception:
            return None

    def require_auth(self) -> str | None:
        user = self.current_user()
        if not user:
            self.send_api(api(False, message="\u672a\u767b\u5f55", code="UNAUTHORIZED"), HTTPStatus.UNAUTHORIZED)
        return user

    def do_GET(self):
        try:
            p = urlparse(self.path)
            if p.path == "/" or p.path.startswith("/assets/"):
                return self.static(p.path)
            if p.path == "/api/health":
                return self.send_api(api(True, {"status": "ok"}))
            user = self.require_auth()
            if not user:
                return
            if p.path == "/api/me":
                return self.send_api(api(True, {"user": user, "config": sanitize_config(load_config())}))
            if p.path == "/api/dashboard":
                return self.send_api(api(True, dashboard_data(self.request_origin())))
            if p.path == "/api/astrbot":
                return self.send_api(api(True, astrbot_data(self.request_origin())))
            if p.path == "/api/plugins/astrbot":
                return self.send_api(api(True, plugins_data()))
            if p.path == "/api/napcat":
                return self.send_api(api(True, parse_napcat_index(self.request_origin())))
            if p.path == "/api/tasks":
                return self.send_api(api(True, [t.to_dict() for t in list(TASKS.values())[-50:]]))
            if p.path.startswith("/api/tasks/"):
                t = TASKS.get(p.path.split("/")[-1])
                return self.send_api(api(bool(t), t.to_dict() if t else None, "" if t else "任务不存在"))
            if p.path == "/api/logs":
                return self.handle_logs(p)
            if p.path == "/api/logs/stream":
                return self.handle_log_stream(p)
            if p.path == "/api/files":
                base = Path(load_config()["upload_dir"])
                return self.send_api(api(True, {"base": str(base), "files": list_files(base)}))
            if p.path == "/api/files/view":
                return self.handle_file_view(p)
            if p.path == "/api/files/download":
                return self.handle_file_download(p)
            if p.path == "/api/backups":
                return self.send_api(api(True, backups_data()))
            if p.path == "/api/backups/download":
                return self.handle_backup_download(p)
            if p.path == "/api/settings":
                return self.send_api(api(True, sanitize_config(load_config())))
            if p.path == "/api/https/status":
                return self.send_api(api(True, https_status()))
            if p.path == "/api/watchdog/status":
                return self.send_api(api(True, watchdog_status()))
            if p.path == "/api/config/astrbot":
                return self.handle_astrbot_config()
            if p.path == "/api/server-files":
                return self.handle_server_files(p)
            if p.path == "/api/server-files/view":
                return self.handle_server_file_view(p)
            if p.path == "/api/server-files/download":
                return self.handle_server_file_download(p)
            self.send_error(404)
        except PermissionError as e:
            self.send_api(api(False, message=str(e), code="FORBIDDEN"), 403)
        except ValueError as e:
            self.send_api(api(False, message=str(e), code="BAD_REQUEST"), 400)
        except Exception as e:
            self.send_api(api(False, message=str(e), code="SERVER_ERROR"), 500)

    def do_POST(self):
        try:
            p = urlparse(self.path)
            if p.path == "/api/login":
                return self.login()
            user = self.require_auth()
            if not user:
                return
            if p.path == "/api/astrbot/action":
                return self.astrbot_action(user)
            if p.path == "/api/astrbot/no-prefix":
                t = create_task("应用免 @ / 免前缀配置", "astrbot.no_prefix", task_apply_no_prefix, user)
                return self.send_api(api(True, t.to_dict()))
            if p.path == "/api/napcat/action":
                return self.napcat_action(user)
            if p.path == "/api/napcat/qq-login":
                return self.napcat_qq_login(user)
            if p.path == "/api/deploy/start":
                return self.deploy_start(user)
            if p.path == "/api/backup/create":
                t = create_task("一键备份", "backup", task_shell, user, "开始备份", "backup_all", 900)
                return self.send_api(api(True, t.to_dict()))
            if p.path == "/api/backup/restore":
                data = self.read_json()
                require_confirm(data, "RESTORE")
                if not load_config()["allow_dangerous"]:
                    raise ValueError("系统设置未开启危险操作")
                archive = path_under(INSTALL_PREFIX / "backups", data.get("file", ""))
                t = create_task("恢复备份", "backup.restore", task_shell, user, "开始恢复", "restore_backup %s" % sh_quote(str(archive)), 1800)
                return self.send_api(api(True, t.to_dict()))
            if p.path == "/api/update":
                data = self.read_json()
                target = data.get("target", "all")
                mapping = {"astrbot": "update_astrbot; write_deploy_info", "napcat": "update_napcat; write_deploy_info", "all": "update_all"}
                if target not in mapping:
                    raise ValueError("更新目标不支持")
                t = create_task("更新 " + target, "update." + target, task_shell, user, "开始更新", mapping[target], 1800)
                return self.send_api(api(True, t.to_dict()))
            if p.path == "/api/https/setup":
                return self.https_setup(user)
            if p.path == "/api/files/upload":
                return self.upload(user)
            if p.path == "/api/files/delete":
                return self.delete_file(user)
            if p.path == "/api/files/apply":
                return self.apply_file(user)
            if p.path == "/api/plugins/install":
                return self.install_plugin(user)
            if p.path == "/api/watchdog/restart":
                return self.watchdog_restart(user)
            if p.path == "/api/settings":
                cfg = save_config_patch(self.read_json())
                audit(user, "settings.save", {}, True)
                return self.send_api(api(True, sanitize_config(cfg)))
            if p.path == "/api/account/password":
                return self.change_password(user)
            if p.path == "/api/config/astrbot":
                return self.save_astrbot_config(user)
            self.send_error(404)
        except PermissionError as e:
            self.send_api(api(False, message=str(e), code="FORBIDDEN"), 403)
        except ValueError as e:
            self.send_api(api(False, message=str(e), code="BAD_REQUEST"), 400)
        except Exception as e:
            self.send_api(api(False, message=str(e), code="SERVER_ERROR"), 500)

    def static(self, path: str):
        rel = "index.html" if path == "/" else path.removeprefix("/assets/")
        file = path_under(STATIC_DIR, rel)
        if not file.exists() or file.is_dir():
            file = STATIC_DIR / "index.html"
        body = file.read_bytes()
        self.send_response(200)
        ctype = mimetypes.guess_type(str(file))[0] or "text/html"
        if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
            ctype += "; charset=utf-8"
        self.send_header("Content-Type", ctype)
        self.security_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def login(self):
        data = self.read_json()
        cfg = load_config()
        ip = self.client_address[0] if self.client_address else "unknown"
        now_ts = time.time()
        LOGIN_FAILS[ip] = [t for t in LOGIN_FAILS.get(ip, []) if now_ts - t < 600]
        if len(LOGIN_FAILS[ip]) >= 8:
            return self.send_api(api(False, message="\u767b\u5f55\u5931\u8d25\u6b21\u6570\u8fc7\u591a\uff0c\u8bf7 10 \u5206\u949f\u540e\u518d\u8bd5", code="RATE_LIMIT"), 429)
        if data.get("username") == cfg["username"] and verify_password(str(data.get("password", "")), cfg["password_hash"]):
            LOGIN_FAILS.pop(ip, None)
            token = self.make_session(cfg["username"])
            body = json.dumps(api(True, {"user": cfg["username"], "token": token}), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "adb_session=%s; Path=/; HttpOnly; SameSite=Lax" % token)
            self.security_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            audit(cfg["username"], "login", {}, True)
            return
        audit(str(data.get("username", "")), "login", {}, False)
        self.send_api(api(False, message="\u8d26\u53f7\u6216\u5bc6\u7801\u9519\u8bef", code="BAD_LOGIN"), 401)

    def astrbot_action(self, user: str):
        action = self.read_json().get("action")
        mapping = {"start": ["start", "astrbot"], "stop": ["stop", "astrbot"], "restart": ["restart", "astrbot"]}
        if action not in mapping:
            raise ValueError("操作不支持")
        code, out = docker(mapping[action], timeout=120)
        audit(user, "astrbot." + action, {}, code == 0)
        self.send_api(api(code == 0, {"output": out}, "完成" if code == 0 else out))

    def napcat_qq_login(self, user: str):
        data = self.read_json()
        name = safe_name(str(data.get("name", "")))
        action = str(data.get("action", "qrcode"))
        row = napcat_row(name)
        if action == "refresh":
            res = napcat_webui_call(row, "/QQLogin/RefreshQRcode")
            audit(user, "napcat.qq.refresh", {"name": name}, int(res.get("code", -1)) == 0)
            return self.send_api(api(int(res.get("code", -1)) == 0, res, res.get("message", "")))
        if action == "status":
            res = napcat_webui_call(row, "/QQLogin/CheckLoginStatus")
            if int(res.get("code", -1)) == 0 and (res.get("data") or {}).get("isLogin"):
                info = napcat_webui_call(row, "/QQLogin/GetQQLoginInfo")
                if int(info.get("code", -1)) == 0:
                    res.setdefault("data", {})["loginInfo"] = info.get("data") or {}
            audit(user, "napcat.qq.status", {"name": name}, int(res.get("code", -1)) == 0)
            return self.send_api(api(int(res.get("code", -1)) == 0, res, res.get("message", "")))
        if action == "qrcode":
            status = napcat_webui_call(row, "/QQLogin/CheckLoginStatus")
            if int(status.get("code", -1)) == 0 and (status.get("data") or {}).get("isLogin"):
                info = napcat_webui_call(row, "/QQLogin/GetQQLoginInfo")
                audit(user, "napcat.qq.already_login", {"name": name}, True)
                return self.send_api(api(True, {"name": name, "already_login": True, "status": status, "login_info": (info.get("data") if int(info.get("code", -1)) == 0 else {}) or {}}))
            res = napcat_webui_call(row, "/QQLogin/GetQQLoginQrcode")
            if int(res.get("code", -1)) != 0:
                return self.send_api(api(False, res, res.get("message", "获取二维码失败")))
            qrcode_url = (res.get("data") or {}).get("qrcode") or ""
            if not qrcode_url:
                return self.send_api(api(False, res, "NapCat 没有返回二维码链接，可能已经登录或二维码还没生成"))
            svg = qr_svg_for_text(qrcode_url)
            audit(user, "napcat.qq.qrcode", {"name": name}, True)
            return self.send_api(api(True, {"name": name, "already_login": False, "qrcode_url": qrcode_url, "svg": svg, "status": res}))
        raise ValueError("QQ 登录操作不支持")

    def napcat_action(self, user: str):
        data = self.read_json()
        action = data.get("action")
        if action == "add":
            count = int(data.get("count", 1))
            if count < 1 or count > 999:
                raise ValueError("数量必须是 1-999")
            t = create_task("\u65b0\u589e NapCat x%d" % count, "napcat.add", task_add_napcat, user, count)
            return self.send_api(api(True, t.to_dict()))
        if action == "restart_all":
            code, out = bash("while IFS=$'\\t' read -r name _; do [[ -n \"$name\" ]] && docker restart \"$name\"; done < \"$NAPCAT_INDEX_FILE\"", timeout=300)
            audit(user, "napcat.restart_all", {}, code == 0)
            return self.send_api(api(code == 0, {"output": out}))
        name = safe_name(str(data.get("name", "")))
        if action in {"start", "stop", "restart"}:
            code, out = docker([action, name], timeout=120)
            audit(user, "napcat." + action, {"name": name}, code == 0)
            return self.send_api(api(code == 0, {"output": out}))
        if action == "delete":
            require_confirm(data, name)
            keep_data = bool(data.get("keep_data", True))
            if not keep_data and not load_config()["allow_dangerous"]:
                raise ValueError("完全删除数据需要先在系统设置里开启危险操作")
            t = create_task("删除 %s" % name, "napcat.delete", task_delete_napcat, user, name, keep_data)
            return self.send_api(api(True, t.to_dict()))
        raise ValueError("操作不支持")

    def deploy_start(self, user: str):
        data = self.read_json()
        count = int(data.get("napcat_count", 1))
        if count < 0 or count > 999:
            raise ValueError("NapCat 数量必须是 0-999")
        token = str(data.get("reverse_token", "")).strip() or "yuyu521521"
        if not all(c.isalnum() or c in "._-+=" for c in token) or len(token) < 4:
            raise ValueError("连接 Token 格式不合法")
        cfg = load_config()
        cfg["default_reverse_ws_token"] = token
        write_json(PANEL_CONFIG, cfg)
        script = (
            "save_state_var ASTRBOT_REVERSE_WS_TOKEN %s; "
            ": \"${ASTRBOT_WEB_PORT:=$(find_free_port 6185)}\"; "
            ": \"${ASTRBOT_WS_PORT:=$(find_free_port 6199)}\"; "
            "save_state_var ASTRBOT_WEB_PORT \"$ASTRBOT_WEB_PORT\"; "
            "save_state_var ASTRBOT_WS_PORT \"$ASTRBOT_WS_PORT\"; "
            "ensure_network; deploy_astrbot; apply_astrbot_default_config; "
            % sh_quote(token)
        )
        if count > 0:
            script += "add_napcat_instances %d; " % count
        script += "write_deploy_info"
        t = create_task("初始化部署 AstrBot + NapCat", "deploy.start", task_shell, user, "开始初始化部署", script, 2400)
        self.send_api(api(True, t.to_dict()))

    def https_setup(self, user: str):
        data = self.read_json()
        domain = str(data.get("domain", "")).strip()
        email = str(data.get("email", "")).strip()
        if not domain or "." not in domain or "/" in domain:
            raise ValueError("请输入正确域名，例如 panel.example.com")
        script = "HTTPS_DOMAIN=%s HTTPS_EMAIL=%s bash scripts/https.sh" % (sh_quote(domain), sh_quote(email))
        t = create_task("自动配置 HTTPS", "https.setup", task_shell, user, "开始安装 Nginx / Certbot 并申请证书", script, 2400)
        self.send_api(api(True, t.to_dict()))

    def handle_logs(self, p):
        qs = parse_qs(p.query)
        target = qs.get("target", ["astrbot"])[0]
        keyword = qs.get("keyword", [""])[0].lower()
        lines = int(qs.get("lines", ["300"])[0])
        text = get_logs(target, lines)
        if keyword:
            text = "\n".join([x for x in text.splitlines() if keyword in x.lower()])
        self.send_api(api(True, {"target": target, "content": text}))

    def handle_log_stream(self, p):
        qs = parse_qs(p.query)
        target = qs.get("target", ["astrbot"])[0]
        keyword = qs.get("keyword", [""])[0].lower()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.security_headers()
        self.end_headers()
        try:
            self.wfile.write(b"retry: 2500\n\n")
            last = ""
            for _ in range(1800):
                text = get_logs(target, 220)
                if keyword:
                    text = "\n".join([x for x in text.splitlines() if keyword in x.lower()])
                if text != last:
                    payload = json.dumps({"target": target, "content": text, "ts": now()}, ensure_ascii=False)
                    self.wfile.write(("data: %s\n\n" % payload).encode("utf-8"))
                    self.wfile.flush()
                    last = text
                else:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError):
            return

    def handle_file_view(self, p):
        qs = parse_qs(p.query)
        f = path_under(Path(load_config()["upload_dir"]), qs.get("path", [""])[0])
        text = f.read_text(encoding="utf-8", errors="replace")[:100000]
        parsed = json.loads(text) if f.suffix.lower() == ".json" else None
        self.send_api(api(True, {"name": f.name, "content": text, "json": parsed}))

    def handle_file_download(self, p):
        f = path_under(Path(load_config()["upload_dir"]), parse_qs(p.query).get("path", [""])[0])
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.security_headers()
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''%s" % quote(f.name))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def server_path(self, raw: str) -> Path:
        if not raw:
            raw = str(INSTALL_PREFIX)
        return ensure_server_file_allowed(Path(raw))

    def handle_server_files(self, p):
        qs = parse_qs(p.query)
        current = self.server_path(qs.get("path", ["/"])[0])
        if not current.exists():
            return self.send_api(api(False, message="\u8def\u5f84\u4e0d\u5b58\u5728", code="NOT_FOUND"), 404)
        if current.is_file():
            current = current.parent
        items = []
        parent = str(current.parent) if current != current.parent else "/"
        for item in sorted(current.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            try:
                st = item.stat()
                items.append({
                    "name": item.name,
                    "path": str(item),
                    "is_dir": item.is_dir(),
                    "size": st.st_size,
                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                    "type": mimetypes.guess_type(str(item))[0] or "application/octet-stream",
                })
            except PermissionError:
                items.append({"name": item.name, "path": str(item), "is_dir": item.is_dir(), "size": 0, "mtime": "\u65e0\u6743\u9650", "type": "permission-denied"})
            except FileNotFoundError:
                continue
        self.send_api(api(True, {"path": str(current), "parent": parent, "items": items}))

    def handle_server_file_view(self, p):
        path = self.server_path(parse_qs(p.query).get("path", [""])[0])
        if not path.is_file():
            return self.send_api(api(False, message="\u4e0d\u662f\u6587\u4ef6", code="NOT_FILE"), 400)
        if path.stat().st_size > 1024 * 1024:
            return self.send_api(api(False, message="\u6587\u4ef6\u8d85\u8fc7 1MB\uff0c\u8bf7\u4e0b\u8f7d\u67e5\u770b", code="TOO_LARGE"), 400)
        text = path.read_text(encoding="utf-8", errors="replace")
        parsed = None
        if path.suffix.lower() == ".json":
            parsed = json.loads(text)
        self.send_api(api(True, {"name": path.name, "path": str(path), "content": text, "json": parsed}))

    def handle_server_file_download(self, p):
        path = self.server_path(parse_qs(p.query).get("path", [""])[0])
        if not path.is_file():
            return self.send_api(api(False, message="\u4e0d\u662f\u6587\u4ef6", code="NOT_FILE"), 400)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.security_headers()
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''%s" % quote(path.name))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def handle_backup_download(self, p):
        f = path_under(INSTALL_PREFIX / "backups", parse_qs(p.query).get("file", [""])[0])
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/gzip")
        self.security_headers()
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''%s" % quote(f.name))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def safe_upload_filename(self, raw: str) -> str:
        name = Path(raw).name.strip().replace("\x00", "")
        name = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", name)
        name = name.strip("._ ")[:120]
        if not name:
            name = "upload_" + secrets.token_hex(4)
        return name

    def upload(self, user: str):
        cfg = load_config()
        base = Path(cfg["upload_dir"])
        base.mkdir(parents=True, exist_ok=True)
        max_size = int(cfg.get("max_upload_mb", 256)) * 1024 * 1024
        ctype = self.headers.get("Content-Type", "")
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype})
        fields = form["files"] if "files" in form else []
        if not isinstance(fields, list):
            fields = [fields]
        saved = []
        for item in fields:
            if not getattr(item, "filename", ""):
                continue
            name = self.safe_upload_filename(item.filename)
            data = item.file.read(max_size + 1)
            if len(data) > max_size:
                raise ValueError("文件超过大小限制")
            if name.lower().endswith(".json"):
                json.loads(data.decode("utf-8"))
            dest = path_under(base, name)
            dest.write_bytes(data)
            saved.append({"name": name, "size": len(data)})
        audit(user, "files.upload", {"files": saved}, True)
        self.send_api(api(True, {"files": saved}))

    def delete_file(self, user: str):
        data = self.read_json()
        require_confirm(data, str(data.get("path", "")))
        if not load_config()["allow_dangerous"]:
            raise ValueError("系统设置未开启危险操作")
        f = path_under(Path(load_config()["upload_dir"]), data.get("path", ""))
        if f.is_dir():
            shutil.rmtree(f)
        else:
            f.unlink()
        audit(user, "files.delete", {"path": str(f)}, True)
        self.send_api(api(True, message="已删除"))

    def apply_file(self, user: str):
        data = self.read_json()
        kind = data.get("kind")
        f = path_under(Path(load_config()["upload_dir"]), data.get("path", ""))
        if kind == "astrbot_plugin":
            t = create_task("安装 AstrBot 插件", "plugin.install", task_install_plugin, user, data.get("path", ""), bool(data.get("restart", True)))
            return self.send_api(api(True, t.to_dict()))
        if kind != "astrbot_config":
            raise ValueError("应用类型不支持")
        obj = json.loads(f.read_text(encoding="utf-8"))
        dest = INSTALL_PREFIX / "data" / "cmd_config.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.copy2(dest, str(dest) + ".bak." + time.strftime("%Y%m%d_%H%M%S"))
        dest.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        audit(user, "files.apply_astrbot_config", {"file": f.name}, True)
        self.send_api(api(True, message="已应用 AstrBot 配置"))

    def install_plugin(self, user: str):
        data = self.read_json()
        source = str(data.get("path", ""))
        if not source:
            raise ValueError("请选择已上传的插件 zip")
        t = create_task("安装 AstrBot 插件", "plugin.install", task_install_plugin, user, source, bool(data.get("restart", True)))
        self.send_api(api(True, t.to_dict()))

    def watchdog_restart(self, user: str):
        code, out = run_process(["bash", "-lc", "systemctl daemon-reload; systemctl enable --now astrbot-napcat-watchdog.service; systemctl restart astrbot-napcat-watchdog.service; systemctl is-active astrbot-napcat-watchdog.service"], timeout=120)
        audit(user, "watchdog.restart", {}, code == 0)
        self.send_api(api(code == 0, {"output": out}, "已启动自动守护" if code == 0 else out))

    def handle_astrbot_config(self):
        path = INSTALL_PREFIX / "data" / "cmd_config.json"
        if not path.exists():
            return self.send_api(api(False, message="AstrBot 配置文件不存在，可能尚未部署", code="NOT_DEPLOYED"), 404)
        text = path.read_text(encoding="utf-8", errors="replace")
        parsed = json.loads(text)
        self.send_api(api(True, {"path": str(path), "content": json.dumps(parsed, ensure_ascii=False, indent=2)}))

    def save_astrbot_config(self, user: str):
        data = self.read_json()
        content = str(data.get("content", ""))
        parsed = json.loads(content)
        path = INSTALL_PREFIX / "data" / "cmd_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, str(path) + ".bak." + time.strftime("%Y%m%d_%H%M%S"))
        path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        restart = bool(data.get("restart", False))
        out = ""
        if restart:
            _, out = docker(["restart", "astrbot"], timeout=120)
        audit(user, "astrbot.config.save", {"restart": restart}, True)
        self.send_api(api(True, {"output": out}, "配置已保存"))

    def change_password(self, user: str):
        data = self.read_json()
        old = str(data.get("old_password", ""))
        new = str(data.get("new_password", ""))
        if len(new) < 8:
            raise ValueError("新密码至少 8 位")
        cfg = load_config()
        if not verify_password(old, cfg.get("password_hash", "")):
            raise ValueError("当前密码不正确")
        cfg["password_hash"] = hash_password(new)
        cfg.pop("initial_password", None)
        write_json(PANEL_CONFIG, cfg)
        audit(user, "account.password.change", {}, True)
        self.send_api(api(True, message="密码已修改，请重新登录"))


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("PANEL_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PANEL_PORT", "7070")))
    args = parser.parse_args()
    cfg = load_config()
    Path(cfg["upload_dir"]).mkdir(parents=True, exist_ok=True)
    ensure_parent(AUDIT_LOG)
    print("AstrBot-Deploy Panel %s listening on %s:%s" % (APP_VERSION, args.host, args.port))
    print("Panel account: %s" % cfg["username"])
    if cfg.get("initial_password"):
        print("Panel initial password: %s" % cfg["initial_password"])
    PanelServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
