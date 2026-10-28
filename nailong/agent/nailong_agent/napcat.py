"""NapCat WebUI 客户端：二维码、登录状态。"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config, docker_client
from .redact import add_secret


class NapCatError(Exception):
    pass


_CRED: dict[str, dict] = {}


def instances() -> list[dict]:
    return config.load().get("napcat") or []


def instance(name: str) -> dict:
    for n in instances():
        if n["container"] == name:
            return n
    raise NapCatError("未找到 NapCat 实例：%s" % name)


def _webui(n: dict) -> tuple[str, str]:
    conf = config.read_json(Path(n.get("config_dir") or "/nonexistent") / "webui.json", {})
    token = str(conf.get("token") or "")
    add_secret(token)
    port = int(conf.get("port") or n.get("webui_container_port") or 6099)
    url = docker_client.service_url(n["container"], port, n.get("webui_port"))
    if not url:
        raise NapCatError("NapCat 容器不存在")
    if not token:
        raise NapCatError("未找到 NapCat WebUI Token")
    return url, token


def _post(url: str, payload: dict | None, headers: dict | None = None, timeout: float = 10) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}")
        except ValueError:
            return {"code": -1, "message": "HTTP %d" % e.code}
    except urllib.error.URLError as e:
        raise NapCatError("无法连接 NapCat WebUI：%s" % e.reason) from e


def _credential(n: dict, url: str, token: str, force: bool = False) -> str:
    key = n["container"]
    c = _CRED.get(key)
    now = time.time()
    if c and c.get("blocked_until", 0) > now:
        raise NapCatError("NapCat 登录过于频繁，请 %d 秒后再试" % int(c["blocked_until"] - now))
    if c and not force and c.get("expires", 0) > now:
        return c["cred"]
    res = _post(url + "/api/auth/login", {"hash": hashlib.sha256((token + ".napcat").encode()).hexdigest()})
    if int(res.get("code", -1)) != 0:
        msg = str(res.get("message", ""))
        if "rate" in msg.lower() or "频繁" in msg:
            _CRED[key] = {"blocked_until": now + 75}
        raise NapCatError("NapCat WebUI 鉴权失败：%s" % msg)
    cred = (res.get("data") or {}).get("Credential")
    if not cred:
        raise NapCatError("NapCat WebUI 没有返回凭据")
    _CRED[key] = {"cred": cred, "expires": now + 3000}
    return cred


def call(name: str, path: str, payload: dict | None = None) -> dict:
    n = instance(name)
    url, token = _webui(n)
    last = {}
    for force in (False, True):
        cred = _credential(n, url, token, force)
        last = _post(url + "/api/" + path.lstrip("/"), payload, {"Authorization": "Bearer " + cred})
        if "Unauthorized" not in str(last.get("message", "")):
            return last
    return last


def login_status(name: str) -> dict:
    st = call(name, "/QQLogin/CheckLoginStatus")
    data = st.get("data") or {}
    out = {"name": name, "is_login": bool(data.get("isLogin")), "is_offline": bool(data.get("isOffline")),
           "error": data.get("loginError") or "", "qrcode": "", "phase": data.get("loginPhase") or "",
           "core_ready": data.get("coreReady")}
    if out["is_login"]:
        info = call(name, "/QQLogin/GetQQLoginInfo").get("data") or {}
        out["uin"] = str(info.get("uin") or "")
        out["nick"] = str(info.get("nick") or info.get("nickname") or "")
    else:
        out["qrcode"] = (data.get("qrcodeurl") or "")
        if not out["qrcode"]:
            res = call(name, "/QQLogin/GetQQLoginQrcode")
            out["qrcode"] = (res.get("data") or {}).get("qrcode") or ""
        if not out["qrcode"] and not out["error"]:
            out["error"] = "QQ 正在启动，二维码生成中…" if out["core_ready"] is False else "暂时获取不到二维码，请点刷新"
    return out


def refresh_qrcode(name: str) -> dict:
    call(name, "/QQLogin/RefreshQRcode")
    time.sleep(1)
    return login_status(name)
