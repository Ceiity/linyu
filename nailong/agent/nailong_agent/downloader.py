"""GitHub 下载加速。

来源只来自用户配置（默认仅 GitHub 官方），支持：
  official  GitHub 官方
  prefix    前缀代理：<url><原始 GitHub 地址>
  replace   替换域名：把 https://github.com 换成 <url>

流程：解析仓库 → 尽量把分支/标签固定到提交 SHA → 测速排序（缓存 6 小时）→
断点续传下载 → 失败指数退避并切换来源 → 校验 HTTPS、ZIP 结构、SHA-256。
下载内容只作为插件包交给 AstrBot，不会被 Agent 执行。
"""
from __future__ import annotations

import hashlib
import io
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from typing import Callable

from . import config

OFFICIAL = {"id": "official", "name": "GitHub 官方", "type": "official", "url": "https://github.com", "enabled": True}
MAX_SIZE = 64 * 1024 * 1024
CACHE_TTL = 6 * 3600
PROBE_BYTES = 256 * 1024
TEST_REPO = ("AstrBotDevs", "AstrBot", "v4.29.3")

_SSL = ssl.create_default_context()
_REPO_RE = re.compile(r"^(?:https://github\.com/)?([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+?)(?:\.git)?/?$")


class DownloadError(Exception):
    pass


def sources() -> list[dict]:
    rows = (config.load().get("sources") or {}).get("github") or []
    out = [OFFICIAL] + [s for s in rows if s.get("id") != "official"]
    return out


def validate_source(s: dict) -> dict:
    url = str(s.get("url") or "").strip()
    kind = s.get("type")
    if kind not in ("prefix", "replace"):
        raise DownloadError("来源类型必须是 prefix 或 replace")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DownloadError("下载源必须是有效的 HTTPS 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DownloadError("下载源地址不能包含账号、查询参数")
    if kind == "prefix" and not url.endswith("/"):
        url += "/"
    sid = re.sub(r"[^a-z0-9\-]", "-", (s.get("id") or parsed.hostname).lower())[:40]
    return {"id": sid, "name": (s.get("name") or parsed.hostname)[:40], "type": kind, "url": url.rstrip("/") if kind == "replace" else url,
            "enabled": bool(s.get("enabled", True))}


def parse_repo(repo: str) -> tuple[str, str]:
    m = _REPO_RE.match(repo.strip())
    if not m:
        raise DownloadError("仓库地址格式不正确，例如 https://github.com/owner/repo")
    return m.group(1), m.group(2)


def map_url(source: dict, github_url: str) -> str:
    if source["type"] == "official":
        return github_url
    if source["type"] == "prefix":
        return source["url"] + github_url
    for host in ("https://github.com", "https://codeload.github.com", "https://api.github.com"):
        if github_url.startswith(host):
            return source["url"] + github_url[len(host):] if host == "https://github.com" else github_url
    return github_url


def _open(url: str, headers: dict | None = None, timeout: float = 15):
    if not url.startswith("https://"):
        raise DownloadError("拒绝非 HTTPS 下载")
    req = urllib.request.Request(url, headers={"User-Agent": "Nailong-Agent", **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout, context=_SSL)


def resolve_commit(owner: str, name: str, ref: str | None) -> str | None:
    if ref and re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    api = "https://api.github.com/repos/%s/%s/commits/%s" % (owner, name, urllib.parse.quote(ref or "HEAD", safe=""))
    for src in [s for s in sources() if s.get("enabled")]:
        url = map_url(src, api)
        try:
            with _open(url, {"Accept": "application/vnd.github.sha"}, timeout=10) as r:
                text = r.read(200).decode().strip()
                if re.fullmatch(r"[0-9a-f]{40}", text):
                    return text
        except Exception:
            continue
    return None


def archive_url(owner: str, name: str, ref: str) -> str:
    return "https://github.com/%s/%s/archive/%s.zip" % (owner, name, urllib.parse.quote(ref, safe=""))


@dataclass
class Probe:
    source: dict
    ok: bool = False
    latency_ms: int | None = None
    speed_bps: int = 0
    resume: bool = False
    error: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.source["id"], "name": self.source["name"], "type": self.source["type"],
                "url": self.source["url"], "ok": self.ok, "latency_ms": self.latency_ms, "speed_bps": self.speed_bps,
                "resume": self.resume, "error": self.error}


def probe(source: dict, github_url: str) -> Probe:
    p = Probe(source)
    url = map_url(source, github_url)
    t0 = time.time()
    try:
        with _open(url, {"Range": "bytes=0-%d" % (PROBE_BYTES - 1)}, timeout=10) as r:
            p.latency_ms = int((time.time() - t0) * 1000)
            t1 = time.time()
            data = r.read(PROBE_BYTES)
            p.speed_bps = int(len(data) / max(time.time() - t1, 0.05))
            p.resume = r.status == 206
            ctype = r.headers.get("Content-Type", "")
            if "html" in ctype or (data[:2] != b"PK" and not p.resume):
                p.error = "返回内容不是 ZIP（可能是错误页）"
                return p
            p.ok = True
    except ssl.SSLError as e:
        p.error = "TLS 证书无效：%s" % e.reason
    except urllib.error.HTTPError as e:
        p.error = "HTTP %d" % e.code
    except urllib.error.URLError as e:
        p.error = "DNS 或网络错误：%s" % e.reason
    except Exception as e:  # noqa: BLE001
        p.error = str(e)[:120]
    return p


def speedtest(fresh: bool = False) -> list[dict]:
    cache_path = config.DATA_DIR / "github-speedtest.json"
    srcs = [s for s in sources() if s.get("enabled")]
    key = "|".join(s["id"] + s["url"] for s in srcs)
    cache = config.read_json(cache_path, {})
    if not fresh and cache.get("key") == key and time.time() - cache.get("ts", 0) < CACHE_TTL:
        return cache["results"]
    test = archive_url(*TEST_REPO)
    results = [probe(s, test).to_dict() for s in srcs]
    results.sort(key=lambda r: (not r["ok"], -(r["speed_bps"] or 0)))
    config.write_json(cache_path, {"key": key, "ts": time.time(), "results": results}, 0o600)
    return results


def _download_one(url: str, progress: Callable[[int, int, int], None] | None, attempts: int = 3) -> bytes:
    buf = io.BytesIO()
    total = 0
    delay = 1.0
    last_err = ""
    for _ in range(attempts):
        try:
            headers = {"Range": "bytes=%d-" % buf.tell()} if buf.tell() else {}
            with _open(url, headers, timeout=30) as r:
                if buf.tell() and r.status != 206:
                    buf = io.BytesIO()  # 来源不支持续传，重新开始
                length = r.headers.get("Content-Length")
                if length:
                    total = buf.tell() + int(length)
                    if total > MAX_SIZE:
                        raise DownloadError("文件超过 %d MB 上限" % (MAX_SIZE // 1024 // 1024))
                t0 = time.time()
                start = buf.tell()
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    buf.write(chunk)
                    if buf.tell() > MAX_SIZE:
                        raise DownloadError("文件超过上限")
                    if progress:
                        progress(buf.tell(), total, int((buf.tell() - start) / max(time.time() - t0, 0.05)))
            return buf.getvalue()
        except DownloadError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = str(getattr(e, "reason", e))[:160]
            time.sleep(delay)
            delay = min(delay * 2, 8)
    raise DownloadError(last_err or "下载失败")


def verify_zip(data: bytes) -> list[str]:
    if data[:4] != b"PK\x03\x04":
        raise DownloadError("下载内容不是 ZIP 文件，已拒绝")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise DownloadError("ZIP 文件损坏") from e
    names = zf.namelist()
    total = 0
    for info in zf.infolist():
        n = info.filename
        if n.startswith("/") or ".." in n.replace("\\", "/").split("/") or ":" in n.split("/")[0]:
            raise DownloadError("ZIP 包含不安全的路径：%s" % n)
        total += info.file_size
    if total > 512 * 1024 * 1024:
        raise DownloadError("ZIP 解压后过大")
    bad = zf.testzip()
    if bad:
        raise DownloadError("ZIP 校验失败：%s" % bad)
    return names


def download_repo(repo: str, ref: str | None = None, expected_sha256: str | None = None,
                  progress: Callable[[str, int, int, int], None] | None = None) -> dict:
    owner, name = parse_repo(repo)
    commit = resolve_commit(owner, name, ref)
    pinned = commit or ref or "HEAD"
    gh_url = archive_url(owner, name, pinned)
    ranked = speedtest()
    order = {r["id"]: i for i, r in enumerate(ranked)}
    srcs = sorted([s for s in sources() if s.get("enabled")], key=lambda s: order.get(s["id"], 99))
    errors = []
    for src in srcs:
        url = map_url(src, gh_url)
        try:
            data = _download_one(url, (lambda c, t, s, src=src: progress(src["name"], c, t, s)) if progress else None)
            verify_zip(data)
            digest = hashlib.sha256(data).hexdigest()
            if expected_sha256 and digest != expected_sha256.lower():
                raise DownloadError("SHA-256 不匹配，内容可能被篡改，已拒绝")
            return {"owner": owner, "name": name, "commit": commit, "ref": ref or "HEAD", "pinned": bool(commit),
                    "sha256": digest, "size": len(data), "source": src["name"], "data": data}
        except DownloadError as e:
            errors.append("%s：%s" % (src["name"], e))
    raise DownloadError("所有下载源都失败了：" + "；".join(errors))
