"""奶龙 Agent HTTP / WebSocket 接口。

只监听 127.0.0.1，由 App 通过 SSH 隧道访问；所有接口（除 /healthz、/api/pair）都需要设备令牌。
没有任何执行任意命令的接口；Docker 操作仅限 AstrBot / NapCat 容器的启动、停止、重启。
"""
from __future__ import annotations

import asyncio
import json
import re
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import __version__, astrbot, auth, backup, config, docker_client, downloader, napcat
from .metrics import Sampler
from .redact import add_secret, parse_line, redact

app = FastAPI(title="Nailong Agent", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
sampler = Sampler(disk_path="/mnt/astrbot")


@app.on_event("startup")
def _startup() -> None:
    sampler.start()
    cfg = config.load()
    for n in cfg.get("napcat") or []:
        conf = config.read_json(Path(n.get("config_dir") or "/nonexistent") / "onebot11.json", {})
        for c in (conf.get("network") or {}).get("websocketClients") or []:
            add_secret(c.get("token"))


# ---------------------------------------------------------------- 通用

def ok(data: Any = None, message: str = "") -> dict:
    return {"ok": True, "data": data, "message": message}


@app.exception_handler(auth.AuthError)
async def _auth_err(_: Request, e: auth.AuthError):
    return JSONResponse({"ok": False, "code": "AUTH", "message": str(e)}, status_code=e.status)


for _exc, _code in ((astrbot.AstrBotError, "ASTRBOT"), (napcat.NapCatError, "NAPCAT"),
                    (downloader.DownloadError, "DOWNLOAD"), (backup.BackupError, "BACKUP"),
                    (docker_client.DockerError, "DOCKER"), (ValueError, "BAD_REQUEST")):
    def _make(code):
        async def handler(_: Request, e: Exception):
            status = 400 if code in ("BAD_REQUEST", "BACKUP", "DOWNLOAD") else 502
            if isinstance(e, docker_client.DockerError) and e.status == 503:
                status = 503
            return JSONResponse({"ok": False, "code": code, "message": redact(str(e))}, status_code=status)
        return handler
    app.add_exception_handler(_exc, _make(_code))


def device(authorization: str = Header(default="")) -> dict:
    token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    return auth.verify(token)


# ---------------------------------------------------------------- 后台任务

class Task:
    def __init__(self, title: str):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.status = "running"
        self.progress: float | None = None
        self.message = ""
        self.result: Any = None
        self.created = time.time()

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "status": self.status, "progress": self.progress,
                "message": self.message, "result": self.result, "created": int(self.created)}


TASKS: dict[str, Task] = {}


def start_task(title: str, fn) -> Task:
    t = Task(title)
    TASKS[t.id] = t
    if len(TASKS) > 100:
        for k in sorted(TASKS, key=lambda k: TASKS[k].created)[:20]:
            TASKS.pop(k, None)

    def runner():
        try:
            t.result = fn(t)
            t.status = "success"
            t.progress = 100
        except Exception as e:  # noqa: BLE001
            t.status = "failed"
            t.message = redact(str(e))
    threading.Thread(target=runner, daemon=True).start()
    return t


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, _: dict = Depends(device)):
    t = TASKS.get(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return ok(t.to_dict())


# ---------------------------------------------------------------- 配对与设备

class PairBody(BaseModel):
    code: str = Field(min_length=8, max_length=32)
    device_name: str = Field(default="Android", max_length=40)
    device_id: str | None = Field(default=None, max_length=64)


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__}


@app.post("/api/pair")
def pair(body: PairBody):
    return ok(auth.pair(body.code, body.device_name, body.device_id), "配对成功")


@app.get("/api/me")
def me(dev: dict = Depends(device)):
    return ok({"device": dev, "version": __version__})


@app.post("/api/token/rotate")
def rotate(dev: dict = Depends(device)):
    return ok(auth.rotate(dev["id"]))


@app.get("/api/devices")
def devices(dev: dict = Depends(device)):
    return ok({"current": dev["id"], "devices": auth.devices()})


@app.delete("/api/devices/{device_id}")
def revoke(device_id: str, _: dict = Depends(device)):
    if not auth.revoke(device_id):
        raise HTTPException(404, "设备不存在")
    return ok(None, "已撤销授权")


# ---------------------------------------------------------------- 总览

def managed_roles() -> dict[str, str]:
    cfg = config.load()
    roles = {}
    if cfg.get("astrbot"):
        roles[cfg["astrbot"]["container"]] = "astrbot"
    for n in cfg.get("napcat") or []:
        roles[n["container"]] = "napcat"
    return roles


def _container_state(name: str) -> dict:
    info = docker_client.inspect(name)
    if not info:
        return {"container": name, "exists": False, "state": "missing", "running": False}
    st = info.get("State") or {}
    return {"container": name, "exists": True, "state": st.get("Status"), "running": bool(st.get("Running")),
            "health": (st.get("Health") or {}).get("Status", ""), "started_at": st.get("StartedAt"),
            "restart_count": info.get("RestartCount", 0), "image": (info.get("Config") or {}).get("Image", "")}


@app.get("/api/overview")
def overview(_: dict = Depends(device)):
    cfg = config.load()
    docker_ok = docker_client.ping()
    data = {"agent_version": __version__, "hostname": socket.gethostname(), "server": cfg.get("server") or {},
            "docker": {"ok": docker_ok}, "metrics": sampler.current(), "astrbot": None, "napcat": []}
    if docker_ok:
        try:
            data["docker"]["version"] = docker_client.version().get("Version")
        except Exception:
            pass
        if cfg.get("astrbot"):
            data["astrbot"] = _container_state(cfg["astrbot"]["container"])
        data["napcat"] = [_container_state(n["container"]) for n in cfg.get("napcat") or []]
    return ok(data)


@app.get("/api/metrics")
def metrics(_: dict = Depends(device)):
    return ok(sampler.current())


# ---------------------------------------------------------------- 服务与 Docker

@app.post("/api/services/{role}/{action}")
def service_action(role: str, action: str, name: str | None = None, _: dict = Depends(device)):
    if action not in ("start", "stop", "restart"):
        raise HTTPException(400, "不支持的操作")
    roles = managed_roles()
    targets = [c for c, r in roles.items() if r == role and (name is None or c == name)]
    if not targets:
        raise HTTPException(404, "没有可操作的 %s 容器" % role)
    for c in targets:
        docker_client.action(c, action)
    return ok([_container_state(c) for c in targets], "操作成功")


@app.get("/api/docker/containers")
def docker_containers(_: dict = Depends(device)):
    roles = managed_roles()
    rows = docker_client.containers()
    for r in rows:
        r["role"] = roles.get(r["name"]) or (r["labels"].get("com.nailong.role") if r["name"] == "nailong-agent" else "")
        r["controllable"] = r["name"] in roles
        r.pop("labels", None)
    return ok(rows)


@app.post("/api/docker/containers/{name}/{action}")
def docker_action(name: str, action: str, _: dict = Depends(device)):
    if name not in managed_roles():
        raise HTTPException(403, "只能管理 AstrBot 与 NapCat 容器")
    docker_client.action(name, action)
    return ok(_container_state(name), "操作成功")


@app.get("/api/docker/containers/{name}/stats")
def docker_stats(name: str, _: dict = Depends(device)):
    if name not in managed_roles():
        raise HTTPException(403, "只能查看奶龙管理的容器")
    s = docker_client.stats(name)
    cpu = s.get("cpu_stats") or {}
    pre = s.get("precpu_stats") or {}
    d_cpu = (cpu.get("cpu_usage") or {}).get("total_usage", 0) - (pre.get("cpu_usage") or {}).get("total_usage", 0)
    d_sys = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
    ncpu = cpu.get("online_cpus") or 1
    mem = s.get("memory_stats") or {}
    return ok({"cpu_percent": round(d_cpu / d_sys * ncpu * 100, 1) if d_sys > 0 else 0,
               "mem_usage": mem.get("usage", 0), "mem_limit": mem.get("limit", 0)})


# ---------------------------------------------------------------- NapCat / QQ

@app.get("/api/napcat")
def napcat_list(_: dict = Depends(device)):
    rows = []
    for n in napcat.instances():
        row = {"container": n["container"], **_container_state(n["container"])}
        rows.append(row)
    return ok(rows)


@app.get("/api/napcat/{name}/login")
def napcat_login(name: str, _: dict = Depends(device)):
    return ok(napcat.login_status(name))


@app.post("/api/napcat/{name}/qrcode/refresh")
def napcat_refresh(name: str, _: dict = Depends(device)):
    return ok(napcat.refresh_qrcode(name))


# ---------------------------------------------------------------- 插件

@app.get("/api/plugins")
def plugins(_: dict = Depends(device)):
    return ok(astrbot.list_plugins())


class InstallBody(BaseModel):
    repo: str = Field(max_length=300)
    ref: str | None = Field(default=None, max_length=100)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


@app.post("/api/plugins/install")
def plugin_install(body: InstallBody, _: dict = Depends(device)):
    owner, name = downloader.parse_repo(body.repo)
    if body.ref and not re.fullmatch(r"[A-Za-z0-9._/\-]{1,100}", body.ref):
        raise HTTPException(400, "版本格式不正确")

    def run(t: Task):
        def progress(src, cur, total, speed):
            t.progress = round(cur * 90 / total, 1) if total else None
            t.message = "从 %s 下载 %.1f MB（%.0f KB/s）" % (src, cur / 1048576, speed / 1024)
        res = downloader.download_repo(body.repo, body.ref, body.sha256, progress)
        t.progress = 92
        t.message = "下载完成（SHA-256 %s…，来源 %s），正在交给 AstrBot 安装" % (res["sha256"][:12], res["source"])
        msg = astrbot.install_upload("%s.zip" % name, res.pop("data"))
        res["message"] = msg
        return res
    return ok(start_task("安装插件 %s/%s" % (owner, name), run).to_dict())


@app.post("/api/plugins/upload")
async def plugin_upload(file: UploadFile, _: dict = Depends(device)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "只支持 .zip 插件包")
    data = await file.read(downloader.MAX_SIZE + 1)
    if len(data) > downloader.MAX_SIZE:
        raise HTTPException(400, "插件包过大")
    downloader.verify_zip(data)

    def run(t: Task):
        t.message = "正在交给 AstrBot 安装"
        return {"message": astrbot.install_upload(file.filename or "plugin.zip", data)}
    return ok(start_task("上传安装 %s" % file.filename, run).to_dict())


class NameBody(BaseModel):
    delete_config: bool = False
    delete_data: bool = False


def _plugin_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,100}", name):
        raise HTTPException(400, "插件名不合法")
    return name


@app.post("/api/plugins/{name}/uninstall")
def plugin_uninstall(name: str, body: NameBody, _: dict = Depends(device)):
    return ok(None, astrbot.uninstall(_plugin_name(name), body.delete_config, body.delete_data))


@app.post("/api/plugins/{name}/update")
def plugin_update(name: str, _: dict = Depends(device)):
    name = _plugin_name(name)
    return ok(start_task("更新插件 %s" % name, lambda t: {"message": astrbot.update(name)}).to_dict())


@app.post("/api/plugins/{name}/enable")
def plugin_enable(name: str, _: dict = Depends(device)):
    return ok(None, astrbot.set_enabled(_plugin_name(name), True))


@app.post("/api/plugins/{name}/disable")
def plugin_disable(name: str, _: dict = Depends(device)):
    return ok(None, astrbot.set_enabled(_plugin_name(name), False))


@app.get("/api/plugins/{name}/config")
def plugin_config(name: str, _: dict = Depends(device)):
    return ok(astrbot.get_config(_plugin_name(name)))


@app.put("/api/plugins/{name}/config")
async def plugin_config_save(name: str, request: Request, _: dict = Depends(device)):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "配置必须是 JSON 对象")
    return ok(None, astrbot.save_config(_plugin_name(name), body))


@app.get("/api/plugins/{name}/logs")
def plugin_logs(name: str, tail: int = 2000, _: dict = Depends(device)):
    name = _plugin_name(name)
    cfg = config.load()
    if not cfg.get("astrbot"):
        raise HTTPException(404, "未接管 AstrBot")
    text = docker_client.logs(cfg["astrbot"]["container"], tail)
    key = name.lower().replace("astrbot_plugin_", "")
    lines = [parse_line(l) for l in text.splitlines() if key in l.lower()]
    return ok(lines[-500:])


# ---------------------------------------------------------------- 日志

def _log_target(target: str) -> str:
    cfg = config.load()
    if target == "astrbot" and cfg.get("astrbot"):
        return cfg["astrbot"]["container"]
    if target == "agent":
        return "nailong-agent"
    for n in cfg.get("napcat") or []:
        if target in ("napcat", n["container"]):
            return n["container"]
    raise HTTPException(404, "日志目标不存在")


@app.get("/api/logs")
def logs(target: str = "astrbot", tail: int = 500, _: dict = Depends(device)):
    text = docker_client.logs(_log_target(target), tail)
    return ok([parse_line(l) for l in text.splitlines() if l.strip()])


@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket):
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
        auth.verify(str(first.get("token") or ""))
        container = _log_target(str(first.get("target") or "astrbot"))
    except Exception as e:  # noqa: BLE001
        await ws.send_text(json.dumps({"type": "error", "message": str(getattr(e, "detail", e))}, ensure_ascii=False))
        await ws.close(code=4401)
        return
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
    stop = threading.Event()

    def reader():
        gen = None
        try:
            gen = docker_client.follow_logs(container, int(first.get("tail") or 200))
            for line in gen:
                if stop.is_set():
                    break
                loop.call_soon_threadsafe(queue.put_nowait, parse_line(line))
        except Exception as e:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(e)})
        finally:
            if gen:
                gen.close()
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=reader, daemon=True).start()
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            await ws.send_text(json.dumps(item, ensure_ascii=False))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        stop.set()


# ---------------------------------------------------------------- 备份

class BackupBody(BaseModel):
    scopes: list[str] = Field(default_factory=lambda: list(backup.SCOPES))
    note: str = Field(default="", max_length=200)


class RestoreBody(BaseModel):
    confirm: str


@app.get("/api/backups")
def backups(_: dict = Depends(device)):
    return ok({"scopes": backup.SCOPES, "items": backup.listing()})


@app.post("/api/backups")
def backup_create(body: BackupBody, _: dict = Depends(device)):
    return ok(start_task("创建备份", lambda t: backup.create(body.scopes, body.note)).to_dict())


@app.get("/api/backups/{name}/download")
def backup_download(name: str, _: dict = Depends(device)):
    p = backup.path_of(name)
    return FileResponse(p, media_type="application/gzip", filename=p.name)


@app.post("/api/backups/upload")
async def backup_upload(file: UploadFile, _: dict = Depends(device)):
    return ok(await asyncio.to_thread(backup.save_upload, file.filename or "", file.file, file.size), "上传成功，已通过校验")


@app.post("/api/backups/{name}/verify")
def backup_verify(name: str, _: dict = Depends(device)):
    m = backup.verify(backup.path_of(name))
    return ok({"files": len(m.get("files", {})), "scopes": m.get("scopes", []), "created_at": m.get("created_at")},
              "校验通过")


@app.post("/api/backups/{name}/restore")
def backup_restore(name: str, body: RestoreBody, _: dict = Depends(device)):
    if body.confirm != name:
        raise HTTPException(400, "请输入备份文件名确认恢复")
    backup.path_of(name)
    return ok(start_task("恢复备份", lambda t: backup.restore(name)).to_dict())


@app.delete("/api/backups/{name}")
def backup_delete(name: str, _: dict = Depends(device)):
    backup.delete(name)
    return ok(None, "已删除")


# ---------------------------------------------------------------- 下载源

class SourcesBody(BaseModel):
    github: list[dict] = Field(default_factory=list, max_length=20)
    registries: list[str] = Field(default_factory=list, max_length=20)
    pypi: list[str] = Field(default_factory=list, max_length=10)
    docker_apt: list[str] = Field(default_factory=list, max_length=10)


def _https_list(items: list[str], field: str) -> list[str]:
    out = []
    for u in items:
        u = u.strip().rstrip("/")
        if not u:
            continue
        if not re.fullmatch(r"https://[A-Za-z0-9.\-]+(:\d+)?(/[A-Za-z0-9._\-/]*)?", u):
            raise HTTPException(400, "%s 地址必须是 HTTPS：%s" % (field, u))
        out.append(u)
    return out


@app.get("/api/sources")
def get_sources(_: dict = Depends(device)):
    s = config.load().get("sources") or {}
    return ok({"github": downloader.sources(), "registries": s.get("registries") or [],
               "pypi": s.get("pypi") or [], "docker_apt": s.get("docker_apt") or []})


@app.put("/api/sources")
def put_sources(body: SourcesBody, _: dict = Depends(device)):
    gh = [downloader.validate_source(s) for s in body.github if s.get("id") != "official"]
    regs = []
    for r in body.registries:
        r = r.strip().removeprefix("https://").rstrip("/")
        if not r:
            continue
        if not re.fullmatch(r"[A-Za-z0-9.\-]+(:\d+)?(/[A-Za-z0-9._\-/]+)?", r):
            raise HTTPException(400, "镜像加速地址格式不正确：%s" % r)
        regs.append(r)
    cfg = config.load()
    cfg["sources"] = {"github": gh, "registries": regs, "pypi": _https_list(body.pypi, "PyPI"),
                      "docker_apt": _https_list(body.docker_apt, "Docker 软件源")}
    config.save(cfg)
    return ok(cfg["sources"], "已保存")


@app.post("/api/sources/github/test")
def test_sources(fresh: bool = True, _: dict = Depends(device)):
    return ok(downloader.speedtest(fresh))
