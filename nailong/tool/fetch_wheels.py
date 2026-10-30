#!/usr/bin/env python3
"""下载 Agent 依赖的离线 wheel（py3.12 / manylinux / amd64+arm64），逐个核对 requirements.lock 里的 SHA-256。

结果放在 agent/wheels/，由 bundle_server.py 打进 App。服务器上安装时仍然 --require-hashes 再校验一次。
"""
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "agent" / "wheels"
LOCK = ROOT / "agent" / "requirements.lock"
ARCH = ("x86_64", "aarch64")


def parse_lock() -> dict[str, tuple[str, set[str]]]:
    pins: dict[str, tuple[str, set[str]]] = {}
    cur = None
    for line in LOCK.read_text().splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", line)
        if m:
            cur = m.group(1).lower().replace("_", "-")
            pins[cur] = (m.group(2), set())
        h = re.search(r"--hash=sha256:([0-9a-f]{64})", line)
        if h and cur:
            pins[cur][1].add(h.group(1))
    return pins


def wanted(fn: str) -> bool:
    if not fn.endswith(".whl"):
        return False
    tags = fn[:-4].split("-")[-3:]
    py, abi, plat = tags
    if plat == "any":
        return "py3" in py or "cp312" in py
    if "cp312" not in py or "cp312" not in abi:
        return False
    return any(a in plat for a in ARCH) and "manylinux" in plat and "musllinux" not in plat


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.whl"):
        old.unlink()
    total = 0
    for name, (ver, hashes) in parse_lock().items():
        meta = json.loads(get("https://pypi.org/pypi/%s/%s/json" % (name, ver)))
        picked = [f for f in meta["urls"] if wanted(f["filename"]) and f["digests"]["sha256"] in hashes]
        if not picked:
            print("没有可用的 wheel：%s==%s" % (name, ver), file=sys.stderr)
            return 1
        # 同一架构只留一个（优先最老的 manylinux 标签，兼容性最好）
        seen: dict[str, dict] = {}
        for f in sorted(picked, key=lambda f: f["filename"]):
            key = "any" if f["filename"].endswith("-any.whl") else next(a for a in ARCH if a in f["filename"])
            seen.setdefault(key, f)
        for f in seen.values():
            data = get(f["url"])
            if hashlib.sha256(data).hexdigest() != f["digests"]["sha256"]:
                print("哈希不一致：" + f["filename"], file=sys.stderr)
                return 1
            (OUT / f["filename"]).write_bytes(data)
            total += len(data)
            print("%-60s %6d KB" % (f["filename"], len(data) // 1024))
    print("合计 %.1f MB" % (total / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
