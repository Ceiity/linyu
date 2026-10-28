"""设备配对与访问令牌。

- 配对码由安装器写入 pairing.json（只存 SHA-256），一次性、10 分钟过期。
- 访问令牌 32 字节随机数，只保存哈希；30 天过期，可轮换、可撤销。
- 配对失败过多会锁定。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
import uuid
from pathlib import Path

from . import config

TOKEN_TTL = 30 * 86400
PAIR_FAIL_LIMIT = 5
PAIR_LOCK_SECONDS = 600

_LOCK = threading.RLock()
_FAILS: list[float] = []


def _devices_path() -> Path:
    return config.DATA_DIR / "devices.json"


def _pairing_path() -> Path:
    return config.DATA_DIR / "pairing.json"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _load() -> dict:
    return config.read_json(_devices_path(), {"devices": []})


def _save(data: dict) -> None:
    config.write_json(_devices_path(), data, 0o600)


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _issue(device: dict) -> str:
    token = secrets.token_urlsafe(32)
    device["token_hash"] = _hash(token)
    device["expires_at"] = int(time.time() + TOKEN_TTL)
    device["rotated_at"] = int(time.time())
    return token


def pair(code: str, device_name: str, device_id: str | None = None) -> dict:
    code = (code or "").strip().upper().replace("-", "").replace(" ", "")
    now = time.time()
    with _LOCK:
        recent = [t for t in _FAILS if now - t < PAIR_LOCK_SECONDS]
        _FAILS[:] = recent
        if len(recent) >= PAIR_FAIL_LIMIT:
            raise AuthError(429, "配对尝试过多，请 10 分钟后再试")
        pairing = config.read_json(_pairing_path(), {"codes": []})
        match = None
        for c in pairing.get("codes", []):
            if not c.get("used") and c.get("expires", 0) > now and hmac.compare_digest(c.get("hash", ""), _hash(code)):
                match = c
                break
        if not match:
            _FAILS.append(now)
            raise AuthError(401, "配对码无效或已过期")
        match["used"] = True
        config.write_json(_pairing_path(), pairing, 0o600)
        data = _load()
        name = (device_name or "Android").strip()[:40] or "Android"
        dev = {"id": device_id if device_id and len(device_id) <= 64 else str(uuid.uuid4()), "name": name,
               "created_at": int(now), "last_seen": int(now), "revoked": False}
        data["devices"] = [d for d in data["devices"] if d.get("id") != dev["id"]]
        token = _issue(dev)
        data["devices"].append(dev)
        _save(data)
        return {"device_id": dev["id"], "token": token, "expires_at": dev["expires_at"]}


def verify(token: str) -> dict:
    if not token:
        raise AuthError(401, "未授权")
    h = _hash(token)
    now = time.time()
    with _LOCK:
        data = _load()
        for d in data["devices"]:
            if d.get("revoked"):
                continue
            if hmac.compare_digest(d.get("token_hash", ""), h):
                if d.get("expires_at", 0) <= now:
                    raise AuthError(401, "授权已过期，请重新配对")
                if now - d.get("last_seen", 0) > 60:
                    d["last_seen"] = int(now)
                    _save(data)
                return {k: v for k, v in d.items() if k != "token_hash"}
    raise AuthError(401, "授权无效或已被撤销")


def rotate(device_id: str) -> dict:
    with _LOCK:
        data = _load()
        for d in data["devices"]:
            if d.get("id") == device_id and not d.get("revoked"):
                token = _issue(d)
                _save(data)
                return {"token": token, "expires_at": d["expires_at"]}
    raise AuthError(404, "设备不存在")


def devices() -> list[dict]:
    return [{k: v for k, v in d.items() if k != "token_hash"} for d in _load()["devices"]]


def revoke(device_id: str) -> bool:
    with _LOCK:
        data = _load()
        for d in data["devices"]:
            if d.get("id") == device_id:
                d["revoked"] = True
                d["token_hash"] = ""
                _save(data)
                return True
    return False
