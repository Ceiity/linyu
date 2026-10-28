"""AstrBot WebUI 客户端。

Agent 读取 AstrBot 数据目录里的 dashboard.jwt_secret，自行签发短期 JWT（HS256），
无需保存 AstrBot 登录密码。只调用 AstrBot 官方的兼容路由（/api/plugin/*、/api/config/*）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import config, docker_client
from .redact import add_secret


class AstrBotError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_jwt(secret: str, username: str, ttl: int = 600) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"username": username, "exp": int(time.time()) + ttl,
                               "auth_source": "nailong-agent"}, separators=(",", ":")).encode())
    signing = (header + "." + payload).encode()
    sig = _b64(hmac.new(secret.encode(), signing, hashlib.sha256).digest())
    return header + "." + payload + "." + sig


def info() -> dict | None:
    return config.load().get("astrbot")


def dashboard_conf() -> dict:
    a = info()
    if not a:
        raise AstrBotError("未接管 AstrBot")
    cfg = config.read_json(Path(a["data_dir"]) / "cmd_config.json", None)
    if not isinstance(cfg, dict):
        raise AstrBotError("读取 AstrBot 配置失败，可能尚未初始化")
    dash = cfg.get("dashboard") or {}
    if dash.get("jwt_secret"):
        add_secret(dash["jwt_secret"])
    return dash


def base_url() -> str:
    a = info()
    if not a:
        raise AstrBotError("未接管 AstrBot")
    port = int(dashboard_conf().get("port") or 6185)
    url = docker_client.service_url(a["container"], port, a.get("port"))
    if not url:
        raise AstrBotError("AstrBot 容器不存在")
    return url


def _headers() -> dict:
    dash = dashboard_conf()
    secret = dash.get("jwt_secret")
    if not secret:
        raise AstrBotError("AstrBot WebUI 尚未初始化（缺少 jwt_secret），请先启动 AstrBot")
    return {"Authorization": "Bearer " + make_jwt(secret, dash.get("username") or "astrbot"),
            "User-Agent": "Nailong-Agent"}


def request(method: str, path: str, body: dict | None = None, query: dict | None = None,
            raw_body: bytes | None = None, content_type: str | None = None, timeout: float = 60) -> dict:
    url = base_url() + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = _headers()
    data = None
    if raw_body is not None:
        data = raw_body
        headers["Content-Type"] = content_type or "application/octet-stream"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            msg = json.loads(payload).get("message") or str(e)
        except Exception:
            msg = "AstrBot 返回 HTTP %d" % e.code
        raise AstrBotError(msg) from e
    except urllib.error.URLError as e:
        raise AstrBotError("无法连接 AstrBot：%s" % e.reason) from e
    try:
        res = json.loads(payload)
    except ValueError:
        raise AstrBotError("AstrBot 返回了无法解析的数据") from None
    if isinstance(res, dict) and res.get("status") == "error":
        raise AstrBotError(res.get("message") or "AstrBot 操作失败")
    return res if isinstance(res, dict) else {"data": res}


def list_plugins() -> list[dict]:
    res = request("GET", "/api/plugin/get")
    data = res.get("data")
    if isinstance(data, dict):
        data = data.get("plugins") or data.get("items") or []
    out = []
    for p in data or []:
        out.append({
            "name": p.get("name"), "display_name": p.get("display_name") or p.get("name"),
            "desc": p.get("desc") or p.get("description") or "", "author": p.get("author") or "",
            "version": p.get("version") or "", "repo": p.get("repo") or "",
            "activated": bool(p.get("activated", p.get("enabled", True))),
            "reserved": bool(p.get("reserved", False)), "has_update": bool(p.get("has_update", False)),
            "online_version": p.get("online_version") or "",
        })
    return out


def install_from_url(repo_url: str, proxy: str = "") -> str:
    res = request("POST", "/api/plugin/install", {"url": repo_url, "proxy": proxy}, timeout=600)
    return res.get("message") or "安装成功"


def install_upload(filename: str, content: bytes) -> str:
    boundary = "----nailong" + uuid.uuid4().hex
    safe = filename.replace('"', "").replace("\r", "").replace("\n", "") or "plugin.zip"
    body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
             "Content-Type: application/zip\r\n\r\n") % (boundary, safe)).encode() + content + \
        ("\r\n--%s--\r\n" % boundary).encode()
    res = request("POST", "/api/plugin/install-upload", raw_body=body,
                  content_type="multipart/form-data; boundary=" + boundary, timeout=600)
    return res.get("message") or "安装成功"


def uninstall(name: str, delete_config: bool = False, delete_data: bool = False) -> str:
    res = request("POST", "/api/plugin/uninstall", {"name": name, "delete_config": delete_config,
                                                    "delete_data": delete_data}, timeout=120)
    return res.get("message") or "已卸载"


def update(name: str, proxy: str = "") -> str:
    res = request("POST", "/api/plugin/update", {"name": name, "proxy": proxy}, timeout=600)
    return res.get("message") or "已更新"


def set_enabled(name: str, enabled: bool) -> str:
    res = request("POST", "/api/plugin/on" if enabled else "/api/plugin/off", {"name": name}, timeout=60)
    return res.get("message") or ("已启用" if enabled else "已禁用")


def get_config(name: str) -> dict:
    res = request("GET", "/api/config/get", query={"plugin_name": name})
    return res.get("data") or {}


def save_config(name: str, conf: dict) -> str:
    res = request("POST", "/api/config/plugin/update", conf, query={"plugin_name": name})
    return res.get("message") or "已保存"
