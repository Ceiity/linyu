#!/usr/bin/env python3
"""Bounded mirror discovery and atomic Docker configuration, stdlib only.

Online input is data, never shell code. Built-in sources remain usable offline.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

KINDS = ("apt", "pip", "github", "docker")
DEFAULT_CATALOG = "https://raw.githubusercontent.com/Ceiity/linyu/main/config/mirrors.json"
DEFAULT_DOCKER_LIST = "https://raw.githubusercontent.com/dongyubin/DockerHub/main/README.md"
MAX_BYTES = 1024 * 1024
MAX_CANDIDATES = 32


def normalize(value: str, kind: str) -> str:
    if not isinstance(value, str) or len(value) > 512 or re.search(r"[\s\\]", value):
        return ""
    try:
        u = urlsplit(value)
        host = u.hostname or ""
        if (u.scheme != "https" or u.username or u.password or u.query or u.fragment
                or u.port not in (None, 443) or "." not in host
                or not re.fullmatch(r"[a-z0-9.-]+", host)):
            return ""
        try:
            ipaddress.ip_address(host)
            return ""
        except ValueError:
            pass
        if host.endswith((".local", ".localhost", ".internal")) or ".." in u.path:
            return ""
        if kind in ("apt", "docker") and u.path not in ("", "/"):
            return ""
        path = u.path.rstrip("/") + ("/" if kind == "github" else "")
        return urlunsplit(("https", host, path, "", ""))
    except (ValueError, TypeError):
        return ""


def unique(values, limit=MAX_CANDIDATES):
    return list(dict.fromkeys(x for x in values if x))[:limit]


def parse_catalog(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Unsupported mirror catalog")
    result = {}
    for kind in KINDS:
        items = data.get(kind, [])
        if not isinstance(items, list) or len(items) > 256:
            raise ValueError("Invalid candidate list")
        result[kind] = unique(normalize(x, kind) for x in items)
    return result


def parse_docker_markdown(text: str) -> dict:
    active = False
    found = []
    for line in text.splitlines():
        if line.startswith("## ") and "DockerHub国内镜像加速源列表" in line.replace(" ", ""):
            active = True
            continue
        if active and line.startswith("#"):
            break
        if (not active or not line.startswith("|") or "~~" in line
                or any(word in line for word in ("会员版", "需要注册", "需要登录", "获取令牌", "只支持内网"))):
            continue
        columns = line.split("|")
        if len(columns) < 4:
            continue
        # Only the registry-address column, never arbitrary linked articles.
        for raw in re.findall(r"`([^`]+)`", columns[2]):
            raw = raw.strip()
            if "://" not in raw:
                raw = "https://" + raw
            found.append(normalize(raw, "docker"))
    result = unique(found)
    if not result:
        raise ValueError("No active registry table found")
    return {"docker": result}


def atomic_write(path: Path, data: bytes, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def cached_source(url, parser, cache_dir: Path, timeout: float, ttl: int):
    if not normalize(url, "pip"):
        return {}
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    path = cache_dir / (key + ".json")
    old = {}
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(old, dict) or old.get("source") != url:
            old = {}
    except (OSError, ValueError):
        pass
    now = time.time()
    previous = old.get("data", {})
    if not isinstance(previous, dict):
        previous = {}
    try:
        fresh = 0 <= now - float(old.get("checked_at", 0)) < ttl
    except (TypeError, ValueError):
        fresh = False
    if fresh:
        return previous
    data = previous
    try:
        req = Request(url, headers={"User-Agent": "linyu-mirror-discovery/1.0"})
        with urlopen(req, timeout=timeout) as response:
            if urlsplit(response.url).scheme != "https":
                raise ValueError("Non-HTTPS redirect")
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Catalog exceeds 1 MiB")
        data = parser(raw.decode("utf-8-sig"))
        print("Mirror catalog refreshed: " + url, file=sys.stderr)
    except (OSError, ValueError) as exc:
        print("Mirror catalog unavailable; using cache/built-ins: " + str(exc), file=sys.stderr)
    try:
        atomic_write(path, json.dumps({"source": url, "checked_at": now, "data": data}).encode())
    except OSError as exc:
        print("Mirror cache write skipped: " + str(exc), file=sys.stderr)
    return data


def candidates(args):
    values = []
    # Local project catalog is the offline fallback, and is read even if discovery is off.
    local = Path(__file__).resolve().parents[1] / "config" / "mirrors.json"
    online = os.environ.get("MIRROR_DISCOVERY", "auto") != "off"
    if online:
        cache = Path(args.cache_dir)
        urls = os.environ.get("MIRROR_CATALOG_URLS", DEFAULT_CATALOG).replace(",", " ").split()[:3]
        for url in urls:
            data = cached_source(url, parse_catalog, cache, args.timeout, args.ttl)
            values.extend(data.get(args.kind, []) if isinstance(data.get(args.kind), list) else [])
        if args.kind == "docker":
            url = os.environ.get("DOCKER_MIRROR_LIST_URL", DEFAULT_DOCKER_LIST)
            data = cached_source(url, parse_docker_markdown, cache, args.timeout, args.ttl)
            values.extend(data.get("docker", []) if isinstance(data.get("docker"), list) else [])
    try:
        values.extend(parse_catalog(local.read_text(encoding="utf-8"))[args.kind])
    except (OSError, ValueError):
        pass
    for value in unique(normalize(x, args.kind) for x in values):
        print(value)


def configure_docker(path: Path, mirrors: list[str]) -> dict:
    # Explicit user-configured local HTTP registries are supported here, but never discovered.
    for mirror in mirrors:
        u = urlsplit(mirror)
        if (u.scheme not in ("http", "https") or not u.hostname or u.username or u.password
                or u.query or u.fragment or u.path not in ("", "/")):
            raise ValueError("Invalid Docker mirror URL")
    existed = path.exists()
    cfg = json.loads(path.read_text(encoding="utf-8-sig")) if existed else {}
    if not isinstance(cfg, dict):
        raise ValueError("Docker daemon config must be an object; original file was not changed")
    if cfg.get("registry-mirrors") == mirrors:
        return {"changed": False}
    backup = str(path) + ".nailong-" + time.strftime("%Y%m%d_%H%M%S") + "-" + str(time.time_ns()) + ".bak"
    if existed:
        shutil.copy2(path, backup)
    cfg["registry-mirrors"] = mirrors
    mode = (path.stat().st_mode & 0o777) if existed else 0o644
    atomic_write(path, (json.dumps(cfg, indent=2) + "\n").encode(), mode)
    assert json.loads(path.read_text(encoding="utf-8"))["registry-mirrors"] == mirrors
    return {"changed": True, "backup": backup if existed else "-"}


def restore_docker(path: Path, backup: str):
    if backup == "-":
        path.unlink(missing_ok=True)
    else:
        original = Path(backup)
        # This command restores only a snapshot made for this exact config path.
        if not str(original).startswith(str(path) + ".nailong-") or not original.name.endswith(".bak"):
            raise ValueError("Backup does not belong to this Docker config")
        atomic_write(path, original.read_bytes(), original.stat().st_mode & 0o777)
        assert path.read_bytes() == original.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    discover = sub.add_parser("candidates")
    discover.add_argument("kind", choices=KINDS)
    discover.add_argument("--cache-dir", required=True)
    discover.add_argument("--timeout", type=float, default=4)
    discover.add_argument("--ttl", type=int, default=86400)
    write = sub.add_parser("configure-docker")
    write.add_argument("path", type=Path)
    write.add_argument("mirrors", nargs="+")
    restore = sub.add_parser("restore-docker")
    restore.add_argument("path", type=Path)
    restore.add_argument("backup")
    args = parser.parse_args()
    try:
        if args.command == "candidates":
            args.timeout = min(15, max(1, args.timeout))
            args.ttl = max(60, args.ttl)
            candidates(args)
        elif args.command == "configure-docker":
            result = configure_docker(args.path, args.mirrors)
            print("updated\t" + result["backup"] if result["changed"] else "unchanged")
        else:
            restore_docker(args.path, args.backup)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
