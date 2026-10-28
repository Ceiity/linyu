"""最小化 Docker Engine API 客户端（标准库，经 /var/run/docker.sock）。"""
from __future__ import annotations

import http.client
import json
import os
import socket
import urllib.parse
from typing import Iterator

SOCK = os.environ.get("NAILONG_DOCKER_SOCK", "/var/run/docker.sock")


class DockerError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class _UnixConn(http.client.HTTPConnection):
    def __init__(self, timeout: float):
        super().__init__("localhost", timeout=timeout)

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(SOCK)
        self.sock = s


def q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def api(method: str, path: str, body=None, timeout: float = 30, raw: bool = False):
    conn = _UnixConn(timeout)
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        payload = resp.read()
    except (FileNotFoundError, ConnectionRefusedError, PermissionError) as e:
        raise DockerError(503, "Docker 不可用：%s" % e) from e
    finally:
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
    except ValueError:
        return payload.decode(errors="replace")


def ping() -> bool:
    try:
        api("GET", "/_ping", timeout=3, raw=True)
        return True
    except Exception:
        return False


def version() -> dict:
    return api("GET", "/version", timeout=5) or {}


def containers(all_: bool = True) -> list[dict]:
    rows = api("GET", "/containers/json?all=%d" % int(all_)) or []
    out = []
    for c in rows:
        out.append({
            "id": c.get("Id", "")[:12],
            "name": (c.get("Names") or ["/?"])[0].lstrip("/"),
            "image": c.get("Image", ""),
            "state": c.get("State", ""),
            "status": c.get("Status", ""),
            "created": c.get("Created", 0),
            "labels": c.get("Labels") or {},
            "ports": [{"private": p.get("PrivatePort"), "public": p.get("PublicPort"), "ip": p.get("IP", ""),
                       "type": p.get("Type")} for p in (c.get("Ports") or [])],
        })
    return out


def inspect(name: str) -> dict | None:
    try:
        return api("GET", "/containers/%s/json" % q(name))
    except DockerError as e:
        if e.status == 404:
            return None
        raise


def action(name: str, act: str) -> None:
    if act not in ("start", "stop", "restart"):
        raise ValueError("unsupported action")
    path = "/containers/%s/%s" % (q(name), act)
    if act in ("stop", "restart"):
        path += "?t=20"
    api("POST", path, timeout=90)


def stats(name: str) -> dict:
    return api("GET", "/containers/%s/stats?stream=0&one-shot=1" % q(name), timeout=15) or {}


def container_ip(info: dict) -> str:
    for net in ((info.get("NetworkSettings") or {}).get("Networks") or {}).values():
        if net.get("IPAddress"):
            return net["IPAddress"]
    return ""


def published(info: dict, private: int) -> tuple[str, int] | None:
    for p in ((info.get("NetworkSettings") or {}).get("Ports") or {}).get("%d/tcp" % private) or []:
        if p.get("HostPort"):
            host = p.get("HostIp") or "127.0.0.1"
            if host in ("0.0.0.0", "::", ""):
                host = "127.0.0.1"
            return host, int(p["HostPort"])
    return None


def service_url(name: str, private: int, fallback_port: int | None = None) -> str | None:
    """容器服务地址：优先本机发布端口，否则用容器 IP（Agent 运行在 host 网络）。"""
    info = inspect(name)
    if not info:
        return None
    pub = published(info, private)
    if pub:
        host = pub[0] if ":" not in pub[0] else "[%s]" % pub[0]
        return "http://%s:%d" % (host, pub[1])
    ip = container_ip(info)
    if ip:
        return "http://%s:%d" % (ip, private)
    if fallback_port:
        return "http://127.0.0.1:%d" % fallback_port
    return None


def demux(raw: bytes) -> str:
    out = []
    i = 0
    while i + 8 <= len(raw) and raw[i] in (0, 1, 2) and raw[i + 1:i + 4] == b"\x00\x00\x00":
        size = int.from_bytes(raw[i + 4:i + 8], "big")
        out.append(raw[i + 8:i + 8 + size])
        i += 8 + size
    if i == 0:
        return raw.decode(errors="replace")
    return b"".join(out).decode(errors="replace")


def logs(name: str, tail: int = 300, since: int = 0) -> str:
    path = "/containers/%s/logs?stdout=1&stderr=1&timestamps=1&tail=%d" % (q(name), max(1, min(tail, 5000)))
    if since:
        path += "&since=%d" % since
    return demux(api("GET", path, raw=True, timeout=30))


def follow_logs(name: str, tail: int = 200) -> Iterator[str]:
    """持续读取容器日志，逐行产出。调用方关闭生成器即结束。"""
    info = inspect(name) or {}
    tty = bool((info.get("Config") or {}).get("Tty"))
    conn = _UnixConn(timeout=3600)
    conn.request("GET", "/containers/%s/logs?follow=1&stdout=1&stderr=1&timestamps=1&tail=%d" % (q(name), tail))
    resp = conn.getresponse()
    if resp.status >= 400:
        conn.close()
        raise DockerError(resp.status, resp.read().decode(errors="replace"))
    pending = b""
    try:
        while True:
            if tty:
                chunk = resp.read1(65536)
                if not chunk:
                    break
                pending += chunk
            else:
                header = resp.read(8)
                if len(header) < 8:
                    break
                size = int.from_bytes(header[4:8], "big")
                pending += resp.read(size)
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                yield line.decode(errors="replace")
    finally:
        conn.close()
