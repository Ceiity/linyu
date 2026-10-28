"""备份与恢复。

备份为 tar.gz，内含 manifest.json（每个文件的 SHA-256）。恢复前：校验整体 SHA-256（若有）、
逐文件校验、拒绝不安全路径/链接，先自动做一次恢复前备份，再停服务→覆盖→启动。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import time
from pathlib import Path

from . import config, docker_client

NAME_RE = re.compile(r"^nailong-backup-\d{8}-\d{6}(?:-[a-z0-9]+)?\.tar\.gz$")
SCOPES = {
    "astrbot_config": "AstrBot 配置",
    "plugins": "插件",
    "plugin_data": "插件数据",
    "napcat_config": "NapCat 配置",
}
MAX_UPLOAD = 2 * 1024 ** 3


class BackupError(Exception):
    pass


def backups_dir() -> Path:
    d = Path(config.load().get("backups_dir") or "/backups")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sources(scopes: list[str]) -> list[tuple[str, Path]]:
    """(归档内前缀, 源路径)"""
    cfg = config.load()
    out = []
    astr = cfg.get("astrbot")
    if astr:
        data = Path(astr["data_dir"])
        if "astrbot_config" in scopes:
            out.append(("astrbot/cmd_config.json", data / "cmd_config.json"))
            out.append(("astrbot/config", data / "config"))
        if "plugins" in scopes:
            out.append(("astrbot/plugins", data / "plugins"))
        if "plugin_data" in scopes:
            out.append(("astrbot/plugin_data", data / "plugin_data"))
    if "napcat_config" in scopes:
        for i, n in enumerate(cfg.get("napcat") or []):
            if n.get("config_dir"):
                out.append(("napcat/%d/config" % i, Path(n["config_dir"])))
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk(prefix: str, src: Path):
    if src.is_file():
        yield prefix, src
        return
    if not src.is_dir():
        return
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules")]
        for f in files:
            p = Path(root) / f
            if p.is_symlink() or not p.is_file():
                continue
            yield prefix + "/" + str(p.relative_to(src)), p


def create(scopes: list[str] | None = None, note: str = "") -> dict:
    scopes = [s for s in (scopes or list(SCOPES)) if s in SCOPES]
    if not scopes:
        raise BackupError("请选择备份内容")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = "nailong-backup-%s.tar.gz" % stamp
    dest = backups_dir() / name
    if dest.exists():
        name = "nailong-backup-%s-%s.tar.gz" % (stamp, os.urandom(2).hex())
        dest = backups_dir() / name
    files = {}
    tmp = dest.with_suffix(".partial")
    with tarfile.open(tmp, "w:gz") as tar:
        for prefix, src in _sources(scopes):
            for arc, path in _walk(prefix, src):
                files[arc] = {"sha256": _sha256_file(path), "size": path.stat().st_size}
                tar.add(str(path), arcname="data/" + arc, recursive=False)
        manifest = {"format": 1, "created_at": int(time.time()), "scopes": scopes, "note": note[:200],
                    "files": files}
        raw = json.dumps(manifest, ensure_ascii=False, indent=1).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(raw)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(raw))
    os.replace(tmp, dest)
    digest = _sha256_file(dest)
    (dest.with_name(name + ".sha256")).write_text("%s  %s\n" % (digest, name))
    return {"name": name, "size": dest.stat().st_size, "sha256": digest, "files": len(files), "scopes": scopes}


def listing() -> list[dict]:
    rows = []
    for p in sorted(backups_dir().glob("nailong-backup-*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True):
        sha_file = p.with_name(p.name + ".sha256")
        rows.append({"name": p.name, "size": p.stat().st_size, "mtime": int(p.stat().st_mtime),
                     "sha256": sha_file.read_text().split()[0] if sha_file.exists() else ""})
    return rows


def path_of(name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise BackupError("备份文件名不合法")
    p = backups_dir() / name
    if not p.exists():
        raise BackupError("备份不存在")
    return p


def delete(name: str) -> None:
    p = path_of(name)
    p.unlink()
    sha = p.with_name(p.name + ".sha256")
    if sha.exists():
        sha.unlink()


def verify(path: Path) -> dict:
    """完整性校验：结构安全 + manifest 中每个文件 SHA-256。"""
    sha_file = path.with_name(path.name + ".sha256")
    if sha_file.exists():
        expected = sha_file.read_text().split()[0]
        if _sha256_file(path) != expected:
            raise BackupError("备份文件 SHA-256 不匹配，可能已损坏")
    try:
        tar = tarfile.open(path, "r:gz")
    except (tarfile.TarError, OSError) as e:
        raise BackupError("备份文件无法读取：%s" % e) from e
    with tar:
        members = tar.getmembers()
        mf = next((m for m in members if m.name == "manifest.json"), None)
        if not mf:
            raise BackupError("备份缺少 manifest.json，不是奶龙备份")
        manifest = json.loads(tar.extractfile(mf).read())
        seen = {}
        for m in members:
            if m.name == "manifest.json":
                continue
            if not m.isfile():
                raise BackupError("备份包含不允许的条目类型：%s" % m.name)
            parts = m.name.split("/")
            if m.name.startswith("/") or ".." in parts or parts[0] != "data":
                raise BackupError("备份包含不安全路径：%s" % m.name)
            arc = m.name[len("data/"):]
            if arc not in manifest.get("files", {}):
                raise BackupError("备份包含未登记的文件：%s" % arc)
            h = hashlib.sha256()
            f = tar.extractfile(m)
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
            if h.hexdigest() != manifest["files"][arc]["sha256"]:
                raise BackupError("文件校验失败：%s" % arc)
            seen[arc] = True
        missing = set(manifest["files"]) - set(seen)
        if missing:
            raise BackupError("备份缺少文件：%s" % next(iter(missing)))
    return manifest


def save_upload(filename: str, stream, size_hint: int | None = None) -> dict:
    if size_hint and size_hint > MAX_UPLOAD:
        raise BackupError("文件过大")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = "nailong-backup-%s-up%s.tar.gz" % (stamp, os.urandom(2).hex())
    dest = backups_dir() / name
    tmp = dest.with_suffix(".partial")
    total = 0
    with open(tmp, "wb") as out:
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD:
                out.close()
                tmp.unlink()
                raise BackupError("文件过大")
            out.write(chunk)
    os.replace(tmp, dest)
    try:
        manifest = verify(dest)
    except BackupError:
        dest.unlink()
        raise
    digest = _sha256_file(dest)
    dest.with_name(name + ".sha256").write_text("%s  %s\n" % (digest, name))
    return {"name": name, "size": total, "sha256": digest, "scopes": manifest.get("scopes", []),
            "original": filename[:100]}


def _target_for(arc: str) -> tuple[Path, Path] | None:
    """归档路径 → (目标文件, 允许的根目录)。"""
    cfg = config.load()
    astr = cfg.get("astrbot")
    if arc.startswith("astrbot/") and astr:
        root = Path(astr["data_dir"])
        return root / arc[len("astrbot/"):], root
    m = re.match(r"^napcat/(\d+)/config/(.+)$", arc)
    if m:
        napcats = cfg.get("napcat") or []
        i = int(m.group(1))
        if i < len(napcats) and napcats[i].get("config_dir"):
            root = Path(napcats[i]["config_dir"])
            return root / m.group(2), root
    return None


def restore(name: str) -> dict:
    path = path_of(name)
    manifest = verify(path)
    safety = create(manifest.get("scopes") or list(SCOPES), note="恢复 %s 前的自动备份" % name)
    cfg = config.load()
    containers = []
    if cfg.get("astrbot") and any(a.startswith("astrbot/") for a in manifest["files"]):
        containers.append(cfg["astrbot"]["container"])
    if any(a.startswith("napcat/") for a in manifest["files"]):
        containers += [n["container"] for n in cfg.get("napcat") or []]
    for c in containers:
        try:
            docker_client.action(c, "stop")
        except Exception:
            pass
    restored = 0
    try:
        with tarfile.open(path, "r:gz") as tar, tempfile.TemporaryDirectory() as tmpd:
            for m in tar.getmembers():
                if m.name == "manifest.json":
                    continue
                arc = m.name[len("data/"):]
                hit = _target_for(arc)
                if hit is None:
                    continue
                target, root = hit
                if not target.resolve().is_relative_to(root.resolve()):
                    raise BackupError("恢复路径不安全：%s" % arc)
                staged = Path(tmpd) / str(restored)
                with tar.extractfile(m) as src, open(staged, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    st = target.stat()
                    os.chown(staged, st.st_uid, st.st_gid)
                    os.chmod(staged, st.st_mode & 0o777)
                shutil.move(str(staged), target)
                restored += 1
    finally:
        for c in containers:
            try:
                docker_client.action(c, "start")
            except Exception:
                pass
    return {"restored": restored, "safety_backup": safety["name"]}
