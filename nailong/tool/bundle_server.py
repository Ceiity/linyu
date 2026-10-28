#!/usr/bin/env python3
"""把安装器与 Agent 打包进 App 资源：app/assets/server/bundle.tar.gz + bundle.json（SHA-256）。

App 通过 SFTP 上传后，在服务器上校验 SHA-256 一致才会解压执行。
"""
import hashlib
import io
import json
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "assets" / "server"


def add_tree(tar, src: Path, arc: str):
    for p in sorted(src.rglob("*")):
        if "__pycache__" in p.parts or p.suffix == ".pyc" or not p.is_file():
            continue
        info = tar.gettarinfo(str(p), arcname=arc + "/" + str(p.relative_to(src)))
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        info.mtime = 0
        info.mode = 0o755 if p.suffix in (".py", ".sh") else 0o644
        with open(p, "rb") as f:
            tar.addfile(info, f)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    # 确定性打包：固定 mtime/属主，gzip mtime=0
    import gzip
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            installer = ROOT / "installer" / "nailong_installer.py"
            info = tar.gettarinfo(str(installer), arcname="nailong_installer.py")
            info.uid = info.gid = 0; info.uname = info.gname = "root"; info.mtime = 0; info.mode = 0o755
            with open(installer, "rb") as f:
                tar.addfile(info, f)
            add_tree(tar, ROOT / "agent" / "nailong_agent", "agent/nailong_agent")
            for name in ("requirements.lock",):
                p = ROOT / "agent" / name
                info = tar.gettarinfo(str(p), arcname="agent/" + name)
                info.uid = info.gid = 0; info.uname = info.gname = "root"; info.mtime = 0; info.mode = 0o644
                with open(p, "rb") as f:
                    tar.addfile(info, f)
    data = buf.getvalue()
    (OUT / "bundle.tar.gz").write_bytes(data)
    version = next(l.split('"')[1] for l in (ROOT / "installer" / "nailong_installer.py").read_text().splitlines()
                   if l.startswith("VERSION ="))
    meta = {"version": version, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    (OUT / "bundle.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
