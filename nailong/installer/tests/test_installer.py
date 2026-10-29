import json
import os
import pwd
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nailong_installer as ni  # noqa: E402

PUB = "ssh-ed25519 " + "A" * 68


def _report(**kw):
    base = {
        "is_root": True,
        "os": {"supported": True, "reason": "", "arch": "amd64"},
        "resources": {"disk_free": 50 * 1024 ** 3, "mem_total": 4 * 1024 ** 3},
        "sshd": {"known": True, "ok": True},
        "firewall": {},
        "tools": {"curl": "x", "tar": "x", "gpg": "x", "docker": None},
        "docker": {"installed": False, "running": False},
        "existing": {"astrbot": [], "napcat": [], "agent": []},
    }
    for k, v in kw.items():
        base[k] = v
    return base


def actions(plan):
    return {s["id"]: s["action"] for s in plan["steps"]}


def test_plan_fresh():
    p = ni.make_plan(_report())
    assert p["mode"] == "fresh" and not p["blockers"]
    a = actions(p)
    assert a["docker"] == "install" and a["astrbot"] == "install" and a["napcat"] == "install"


def test_plan_existing_docker_skips_install():
    p = ni.make_plan(_report(docker={"installed": True, "running": True}, tools={"curl": "x", "tar": "x", "gpg": "x", "docker": "Docker 27"}))
    assert actions(p)["docker"] == "skip" and p["mode"] == "partial"


def test_plan_takeover_keeps_everything():
    p = ni.make_plan(_report(docker={"installed": True, "running": True},
                             existing={"astrbot": ["astrbot"], "napcat": ["napcat01", "napcat02"], "agent": []}))
    a = actions(p)
    assert p["mode"] == "takeover"
    assert a["astrbot"] == "keep" and a["napcat"] == "keep" and a["onebot"] == "keep"


def test_plan_partial_only_adds_missing():
    p = ni.make_plan(_report(docker={"installed": True, "running": True}, existing={"astrbot": ["astrbot"], "napcat": [], "agent": []}))
    a = actions(p)
    assert a["astrbot"] == "keep" and a["napcat"] == "install" and p["mode"] == "partial"


def test_plan_blockers():
    p = ni.make_plan(_report(is_root=False, os={"supported": False, "reason": "暂不支持 CentOS", "arch": ""},
                             resources={"disk_free": 1024 ** 3, "mem_total": 512 * 1024 ** 2},
                             sshd={"known": True, "ok": False}))
    text = "；".join(p["blockers"])
    assert "root" in text and "CentOS" in text and "磁盘" in text and "转发" in text
    assert p["warnings"]


def test_classify_containers():
    rows = [
        {"name": "astrbot", "image": "soulter/astrbot:latest", "labels": {}, "mounts": []},
        {"name": "bot1", "image": "mlikiowa/napcat-docker:latest", "labels": {}, "mounts": []},
        {"name": "custom", "image": "my/img", "labels": {}, "mounts": [{"destination": "/app/napcat/config"}]},
        {"name": "nginx", "image": "nginx", "labels": {}, "mounts": []},
        {"name": "nailong-agent", "image": "python", "labels": {"com.nailong.role": "agent"}, "mounts": []},
    ]
    c = ni.classify_containers(rows)
    assert [x["name"] for x in c["astrbot"]] == ["astrbot"]
    assert [x["name"] for x in c["napcat"]] == ["bot1", "custom"]
    assert [x["name"] for x in c["agent"]] == ["nailong-agent"]


@pytest.fixture()
def home(tmp_path, monkeypatch):
    me = pwd.getpwuid(os.getuid())
    fake = me._replace(pw_dir=str(tmp_path)) if hasattr(me, "_replace") else None
    entry = pwd.struct_passwd((me.pw_name, "x", me.pw_uid, me.pw_gid, "", str(tmp_path), "/bin/sh"))
    monkeypatch.setattr(ni.pwd, "getpwnam", lambda u: entry)
    return tmp_path


def test_authorize_key_restricted(home):
    ni.authorize_key("root", PUB, "nl-device0001", 18180)
    ni.authorize_key("root", PUB, "nl-device0001", 18181)  # 同设备重复授权只保留一行
    lines = (home / ".ssh" / "authorized_keys").read_text().strip().splitlines()
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith('restrict,port-forwarding,permitopen="127.0.0.1:18181",command="echo nailong-tunnel-only" ')
    assert line.endswith(" nailong:nl-device0001")
    assert oct(os.stat(home / ".ssh" / "authorized_keys").st_mode & 0o777) == "0o600"
    assert ni.revoke_key("root", "nl-device0001")["removed"] == 1


@pytest.mark.parametrize("pub,dev,user", [
    (PUB + '\ncommand="rm -rf /"', "nl-device0001", "root"),
    ("ssh-rsa " + "A" * 68, "nl-device0001", "root"),
    (PUB, "x; rm -rf /", "root"),
    (PUB, "nl-device0001", "root;id"),
])
def test_authorize_key_rejects_injection(home, pub, dev, user):
    with pytest.raises(ni.InstallError):
        ni.authorize_key(user, pub, dev, 18180)


def test_gpg_fingerprint_parser():
    assert ni.gpg_fingerprints(b"not a key") == []


def test_registry_host_requires_https():
    assert ni.registry_host("https://mirror.example.com/") == "mirror.example.com"
    with pytest.raises(ni.InstallError):
        ni.registry_host("http://mirror.example.com")
    with pytest.raises(ni.InstallError):
        ni.registry_host("mirror.example.com; rm -rf /")


def test_redact():
    ni.add_secret("SuperSecretToken123")
    assert "SuperSecretToken123" not in ni.redact("token SuperSecretToken123")
    assert "abc12345" not in ni.redact('{"token": "abc12345"}')


def test_napcat_template():
    c = ni.napcat_onebot_config("ws://astrbot:6199/ws", "tok123456")
    ws = c["network"]["websocketClients"][0]
    assert ws["url"] == "ws://astrbot:6199/ws" and ws["token"] == "tok123456" and ws["enable"]


def test_fail2ban_jail_text():
    t = ni.fail2ban_jail_text([22, 2222], systemd=True)
    assert "[sshd]" in t and "enabled = true" in t and "port = 22,2222" in t
    assert "maxretry = 5" in t and "bantime = 1h" in t
    assert "backend = systemd" in t and "_COMM=sshd-session" in t
    t2 = ni.fail2ban_jail_text([22], systemd=False)
    assert "backend" not in t2 and "port = 22" in t2


def test_plan_fail2ban():
    def f2b_action(**kw):
        p = ni.make_plan(_report(fail2ban=kw))
        return next(s for s in p["steps"] if s["id"] == "fail2ban")["action"]
    assert f2b_action(installed=False) == "install"
    assert f2b_action(installed=True, active=False, sshd_jail=False) == "install"
    # 用户自己已经启用 SSH 防护：保留
    assert f2b_action(installed=True, active=True, sshd_jail=True, managed=False) == "keep"
    # 奶龙之前配的：允许幂等更新
    assert f2b_action(installed=True, active=True, sshd_jail=True, managed=True) == "install"
    # 旧报告没有该字段也不报错
    p = ni.make_plan(_report())
    assert any(s["id"] == "fail2ban" for s in p["steps"])
