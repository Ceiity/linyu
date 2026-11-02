"""SSH remote deployment: server IP + port + user + password → full install.

* Passwords are encrypted at rest with AES-256-GCM; the key lives in
  ``<INSTALL_PREFIX>/.secret.key`` (0600) and is never returned by the API.
* Host keys are trust-on-first-use: the fingerprint seen on the first
  successful connection is pinned, a later mismatch is refused.
* The remote side runs this project's own one-line installer, so the remote
  server ends up exactly like a local install (panel first, NapCat / AstrBot,
  SnowLuma optional from the remote panel).
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

INSTALL_CMD = "bash <(curl -fsSL https://raw.githubusercontent.com/Ceiity/linyu/main/install.sh)"
INSTALL_CMD_MIRROR = "bash <(curl -fsSL https://ghfast.top/https://raw.githubusercontent.com/Ceiity/linyu/main/install.sh)"

DETECT_SCRIPT = r"""
echo "ARCH=$(uname -m)"
. /etc/os-release 2>/dev/null; echo "OS=${PRETTY_NAME:-unknown}"
echo "UID=$(id -u)"
echo "DOCKER=$(docker --version 2>/dev/null | head -n1)"
echo "COMPOSE=$( (docker compose version 2>/dev/null || docker-compose version 2>/dev/null) | head -n1)"
echo "MEM_MB=$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo 2>/dev/null)"
echo "MEM_AVAIL_MB=$(awk '/MemAvailable/{printf "%d", $2/1024}' /proc/meminfo 2>/dev/null)"
echo "DISK_FREE_MB=$(df -Pm / 2>/dev/null | awk 'NR==2{print $4}')"
echo "CURL=$(command -v curl >/dev/null && echo yes || echo no)"
echo "SUDO=$(command -v sudo >/dev/null && echo yes || echo no)"
echo "GITHUB=$(curl -sS -o /dev/null -m 8 -w '%{http_code}' https://github.com 2>/dev/null || echo 000)"
echo "PTRACE=$(cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || echo n/a)"
"""


class SSHError(ValueError):
    pass


class SecretBox:
    def __init__(self, key_path: Path):
        self.key_path = key_path
        self._lock = threading.Lock()

    def _key(self) -> bytes:
        with self._lock:
            if self.key_path.exists():
                raw = self.key_path.read_bytes()
                if len(raw) == 32:
                    return raw
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            key = secrets.token_bytes(32)
            fd = os.open(str(self.key_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key)
            return key

    def encrypt(self, plaintext: str) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = secrets.token_bytes(12)
        ct = AESGCM(self._key()).encrypt(nonce, plaintext.encode("utf-8"), b"nailong-ssh")
        return "v1:" + base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if not str(token or "").startswith("v1:"):
            raise SSHError("密文格式不正确")
        raw = base64.b64decode(token[3:])
        return AESGCM(self._key()).decrypt(raw[:12], raw[12:], b"nailong-ssh").decode("utf-8")


def _valid_host(host: str) -> str:
    host = str(host or "").strip()
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if re.fullmatch(r"(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", host):
        return host
    raise SSHError("服务器地址不合法")


class SSHServers:
    def __init__(self, install_prefix: Path):
        self.path = install_prefix / "ssh_servers.json"
        self.box = SecretBox(install_prefix / ".secret.key")
        self.lock = threading.RLock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if not isinstance(data.get("servers"), dict):
            data["servers"] = {}
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    @staticmethod
    def public(row: dict) -> dict:
        return {k: v for k, v in row.items() if k not in ("password_enc",)} | {"has_password": bool(row.get("password_enc"))}

    def list(self) -> list[dict]:
        with self.lock:
            return [self.public(r) for r in self._load()["servers"].values()]

    def get(self, sid: str) -> dict:
        with self.lock:
            row = self._load()["servers"].get(sid)
        if not row:
            raise SSHError("服务器不存在")
        return dict(row)

    def save(self, payload: dict) -> dict:
        host = _valid_host(payload.get("host"))
        try:
            port = int(payload.get("port") or 22)
        except (TypeError, ValueError):
            raise SSHError("SSH 端口不合法")
        if not 1 <= port <= 65535:
            raise SSHError("SSH 端口不合法")
        user = str(payload.get("username") or "root").strip()
        if not re.fullmatch(r"[a-z_][a-z0-9_.-]{0,31}", user):
            raise SSHError("用户名不合法")
        name = str(payload.get("name") or host).strip()[:40]
        with self.lock:
            data = self._load()
            sid = str(payload.get("id") or "") or secrets.token_hex(6)
            row = data["servers"].get(sid, {"id": sid, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
            if row.get("host") != host or int(row.get("port") or 0) != port:
                row.pop("host_key", None)  # new target → new TOFU pin
            row.update({"name": name, "host": host, "port": port, "username": user})
            pw = payload.get("password")
            if pw:
                row["password_enc"] = self.box.encrypt(str(pw))
            if not row.get("password_enc"):
                raise SSHError("请填写 SSH 密码")
            data["servers"][sid] = row
            self._save(data)
            return self.public(row)

    def update(self, sid: str, **patch) -> None:
        with self.lock:
            data = self._load()
            if sid in data["servers"]:
                data["servers"][sid].update(patch)
                self._save(data)

    def delete(self, sid: str) -> None:
        with self.lock:
            data = self._load()
            data["servers"].pop(sid, None)
            self._save(data)

    # ------------------------------------------------------------------
    def connect(self, sid: str):
        try:
            import paramiko
        except Exception as e:
            raise SSHError("服务器缺少 paramiko：请执行 apt-get install -y python3-paramiko 后重启面板") from e
        row = self.get(sid)
        password = self.box.decrypt(row["password_enc"])
        cli = paramiko.SSHClient()
        pinned = row.get("host_key")

        class Pin(paramiko.MissingHostKeyPolicy):
            def missing_host_key(inner, client, hostname, key):  # noqa: N805
                fp = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
                if pinned and pinned.get("fingerprint") != fp:
                    raise SSHError("主机指纹已变化（%s → %s），可能遭遇中间人攻击；确认无误后请删除并重新添加该服务器" % (pinned.get("fingerprint"), fp))
                client._nailong_fp = {"type": key.get_name(), "fingerprint": fp}

        cli.set_missing_host_key_policy(Pin())
        try:
            cli.connect(row["host"], port=int(row["port"]), username=row["username"], password=password,
                        timeout=15, banner_timeout=20, auth_timeout=20, look_for_keys=False, allow_agent=False)
        except SSHError:
            raise
        except Exception as e:
            raise SSHError("SSH 连接失败：%s" % e) from e
        fp = getattr(cli, "_nailong_fp", None)
        if fp and not pinned:
            self.update(sid, host_key=fp)
        return cli, row, password

    @staticmethod
    def run(cli, command: str, password: str = "", sudo: bool = False, timeout: int = 60, on_line=None) -> tuple[int, str]:
        if sudo:
            command = "sudo -S -p '' bash -c %s" % _sq(command)
        stdin, stdout, stderr = cli.exec_command("bash -lc %s" % _sq(command), timeout=timeout, get_pty=bool(on_line))
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        out = []
        if on_line:
            for line in iter(stdout.readline, ""):
                out.append(line)
                on_line(line.rstrip("\n").replace(password, "***") if password else line.rstrip("\n"))
        else:
            out.append(stdout.read().decode("utf-8", errors="replace"))
            out.append(stderr.read().decode("utf-8", errors="replace"))
        code = stdout.channel.recv_exit_status()
        text = "".join(out)
        if password:
            text = text.replace(password, "***")
        return code, text

    def detect(self, sid: str) -> dict:
        cli, row, password = self.connect(sid)
        try:
            code, out = self.run(cli, DETECT_SCRIPT, timeout=60)
        finally:
            cli.close()
        info = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info[k.strip()] = v.strip()
        checks = evaluate(info)
        self.update(sid, last_check={"time": time.strftime("%Y-%m-%d %H:%M:%S"), "info": info, "ok": all(c["ok"] or c["level"] == "warn" for c in checks)})
        return {"server": self.public(self.get(sid)), "info": info, "checks": checks}

    def deploy(self, sid: str, log, mirror: bool = False, napcat_count: int = 0) -> dict:
        cli, row, password = self.connect(sid)
        try:
            log("已连接 %s@%s:%s" % (row["username"], row["host"], row["port"]))
            code, out = self.run(cli, DETECT_SCRIPT, timeout=60)
            info = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
            for c in evaluate(info):
                log("[%s] %s：%s" % ("OK" if c["ok"] else c["level"].upper(), c["title"], c["detail"]))
                if not c["ok"] and c["level"] == "error":
                    raise SSHError("环境检测未通过：%s" % c["title"])
            sudo = info.get("UID") != "0"
            if sudo and info.get("SUDO") != "yes":
                raise SSHError("非 root 用户且没有 sudo，无法安装")
            env = ""
            if napcat_count > 0:
                env = "ASTRBOT_DEPLOY_MODE=full NAPCAT_COUNT=%d " % int(napcat_count)
            cmd = env + (INSTALL_CMD_MIRROR if mirror or info.get("GITHUB", "000")[:1] not in ("2", "3") else INSTALL_CMD)
            log("执行安装：%s%s" % ("sudo " if sudo else "", cmd))
            code, out = self.run(cli, cmd, password, sudo=sudo, timeout=3600, on_line=log)
            panel = ""
            for line in out.splitlines()[::-1]:
                m = re.search(r"(https?://[^\s]+:\d+/)", line)
                if m:
                    panel = m.group(1)
                    break
            self.update(sid, last_deploy={"time": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": code == 0, "panel": panel})
            if code != 0:
                raise SSHError("远程安装失败（退出码 %d），请查看任务日志" % code)
            return {"ok": True, "panel_url": panel, "message": "远程安装完成，请打开远程面板继续（初始账号密码见任务日志）"}
        finally:
            cli.close()


def evaluate(info: dict) -> list[dict]:
    checks = []

    def add(cid, title, ok, detail, level="error"):
        checks.append({"id": cid, "title": title, "ok": bool(ok), "detail": detail, "level": "ok" if ok else level})

    arch = info.get("ARCH", "")
    add("arch", "CPU 架构", arch in ("x86_64", "amd64", "aarch64", "arm64"), arch or "未知")
    osn = info.get("OS", "")
    add("os", "操作系统", any(x in osn.lower() for x in ("debian", "ubuntu")), osn or "未知", "warn")
    add("docker", "Docker", bool(info.get("DOCKER")), info.get("DOCKER") or "未安装（安装脚本会自动安装）", "warn")
    add("compose", "Docker Compose", bool(info.get("COMPOSE")), info.get("COMPOSE") or "未安装（安装脚本会自动安装）", "warn")
    try:
        mem = int(info.get("MEM_MB") or 0)
    except ValueError:
        mem = 0
    add("memory", "内存", mem >= 1500, "%d MB（AstrBot + 1 个协议端建议 ≥ 2 GB）" % mem, "warn")
    try:
        disk = int(info.get("DISK_FREE_MB") or 0)
    except ValueError:
        disk = 0
    add("disk", "磁盘空间", disk >= 8192, "可用 %.1f GB（建议 ≥ 8 GB）" % (disk / 1024), "warn" if disk >= 4096 else "error")
    add("curl", "必要依赖 curl", info.get("CURL") == "yes", "curl %s" % ("已安装" if info.get("CURL") == "yes" else "缺失"))
    gh = info.get("GITHUB", "000")
    add("network", "网络连接", gh[:1] in ("2", "3"), "GitHub HTTP %s（不可达时自动走镜像加速）" % gh, "warn")
    add("ptrace", "ptrace 限制（SnowLuma）", info.get("PTRACE") != "3", "ptrace_scope=%s" % info.get("PTRACE", "n/a"), "warn")
    return checks


def _sq(s: str) -> str:
    return "'" + str(s).replace("'", "'\"'\"'") + "'"
