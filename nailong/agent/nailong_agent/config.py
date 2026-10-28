"""Agent 配置：由安装器写入 /data/config.json。"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("NAILONG_CONFIG", "/data/config.json"))
DATA_DIR = CONFIG_PATH.parent
_LOCK = threading.RLock()


def load() -> dict:
    with _LOCK:
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"astrbot": None, "napcat": [], "backups_dir": str(DATA_DIR / "backups"), "sources": {}}


def save(cfg: dict) -> None:
    with _LOCK:
        tmp = CONFIG_PATH.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, data, mode: int = 0o600) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
