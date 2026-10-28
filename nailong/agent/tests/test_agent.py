import hashlib
import io
import json
import os
import tarfile
import time
import zipfile
from pathlib import Path

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    astr = tmp_path / "astrbot"
    (astr / "plugins" / "demo").mkdir(parents=True)
    (astr / "plugins" / "demo" / "main.py").write_text("print('hi')\n")
    (astr / "cmd_config.json").write_text(json.dumps({"dashboard": {"jwt_secret": "s3cret-jwt-value", "username": "astrbot"}}))
    nap = tmp_path / "napcat"
    nap.mkdir()
    (nap / "webui.json").write_text(json.dumps({"token": "napcat-webui-token", "port": 6099}))
    cfg = {"astrbot": {"container": "astrbot", "data_dir": str(astr)},
           "napcat": [{"container": "napcat", "config_dir": str(nap)}],
           "backups_dir": str(tmp_path / "backups"), "sources": {}}
    (data / "config.json").write_text(json.dumps(cfg))
    monkeypatch.setenv("NAILONG_CONFIG", str(data / "config.json"))
    import importlib
    from nailong_agent import config, auth, backup, downloader
    importlib.reload(config)
    for m in (auth, backup, downloader):
        importlib.reload(m)
    return {"tmp": tmp_path, "data": data, "astr": astr, "nap": nap}


def _code(data_dir: Path, code: str):
    (data_dir / "pairing.json").write_text(json.dumps({"codes": [
        {"hash": hashlib.sha256(code.encode()).hexdigest(), "expires": time.time() + 600, "used": False}]}))


def test_pair_verify_rotate_revoke(env):
    from nailong_agent import auth
    _code(env["data"], "ABCDEFGH2345")
    res = auth.pair("abcd-efgh-2345", "Pixel", "dev-0001")
    assert res["device_id"] == "dev-0001"
    assert auth.verify(res["token"])["name"] == "Pixel"
    with pytest.raises(auth.AuthError):  # 一次性
        auth.pair("ABCDEFGH2345", "x")
    new = auth.rotate("dev-0001")
    with pytest.raises(auth.AuthError):
        auth.verify(res["token"])
    assert auth.verify(new["token"])
    devices = auth.devices()
    assert "token_hash" not in devices[0]
    assert auth.revoke("dev-0001")
    with pytest.raises(auth.AuthError):
        auth.verify(new["token"])


def test_pair_bruteforce_lock(env):
    from nailong_agent import auth
    auth._FAILS.clear()
    for _ in range(5):
        with pytest.raises(auth.AuthError):
            auth.pair("WRONGWRONG22", "x")
    _code(env["data"], "ABCDEFGH2345")
    with pytest.raises(auth.AuthError) as e:
        auth.pair("ABCDEFGH2345", "x")
    assert e.value.status == 429
    auth._FAILS.clear()


def test_expired_token(env):
    from nailong_agent import auth
    _code(env["data"], "ABCDEFGH2345")
    res = auth.pair("ABCDEFGH2345", "x", "dev-0002")
    data = json.loads((env["data"] / "devices.json").read_text())
    data["devices"][0]["expires_at"] = 1
    (env["data"] / "devices.json").write_text(json.dumps(data))
    with pytest.raises(auth.AuthError):
        auth.verify(res["token"])


def test_backup_roundtrip_and_tamper(env, monkeypatch):
    from nailong_agent import backup, docker_client
    monkeypatch.setattr(docker_client, "action", lambda *a, **k: None)
    b = backup.create(["plugins", "astrbot_config", "napcat_config"])
    assert b["files"] == 3
    p = backup.path_of(b["name"])
    m = backup.verify(p)
    assert "astrbot/plugins/demo/main.py" in m["files"]
    (env["astr"] / "plugins" / "demo" / "main.py").write_text("changed\n")
    res = backup.restore(b["name"])
    assert res["restored"] == 3
    assert (env["astr"] / "plugins" / "demo" / "main.py").read_text() == "print('hi')\n"
    # 篡改：替换文件内容后 manifest 校验应失败
    bad = env["tmp"] / "bad.tar.gz"
    with tarfile.open(p) as src, tarfile.open(bad, "w:gz") as dst:
        for mem in src.getmembers():
            f = src.extractfile(mem)
            raw = f.read()
            if mem.name.endswith("main.py"):
                raw = b"evil"
                mem.size = len(raw)
            dst.addfile(mem, io.BytesIO(raw))
    with pytest.raises(backup.BackupError):
        backup.save_upload("bad.tar.gz", open(bad, "rb"))


def test_backup_rejects_traversal(env):
    from nailong_agent import backup
    evil = env["tmp"] / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as t:
        raw = json.dumps({"files": {"../x": {"sha256": "0"}}}).encode()
        i = tarfile.TarInfo("manifest.json"); i.size = len(raw); t.addfile(i, io.BytesIO(raw))
        i = tarfile.TarInfo("data/../../etc/passwd"); i.size = 1; t.addfile(i, io.BytesIO(b"x"))
    with pytest.raises(backup.BackupError):
        backup.save_upload("evil.tar.gz", open(evil, "rb"))
    with pytest.raises(backup.BackupError):
        backup.path_of("../../etc/passwd")


def test_zip_checks(env):
    from nailong_agent import downloader
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("repo-abc/main.py", "x")
    assert downloader.verify_zip(buf.getvalue()) == ["repo-abc/main.py"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.py", "x")
    with pytest.raises(downloader.DownloadError):
        downloader.verify_zip(buf.getvalue())
    with pytest.raises(downloader.DownloadError):
        downloader.verify_zip(b"<html>proxy error</html>")


def test_sources_and_repo(env):
    from nailong_agent import downloader
    assert downloader.parse_repo("https://github.com/Soulter/astrbot_plugin_x.git") == ("Soulter", "astrbot_plugin_x")
    assert downloader.parse_repo("a/b") == ("a", "b")
    with pytest.raises(downloader.DownloadError):
        downloader.parse_repo("https://evil.com/a/b")
    s = downloader.validate_source({"type": "prefix", "url": "https://gh.example.com"})
    assert downloader.map_url(s, "https://github.com/a/b/archive/x.zip") == "https://gh.example.com/https://github.com/a/b/archive/x.zip"
    r = downloader.validate_source({"type": "replace", "url": "https://hub.example.com"})
    assert downloader.map_url(r, "https://github.com/a/b/archive/x.zip") == "https://hub.example.com/a/b/archive/x.zip"
    with pytest.raises(downloader.DownloadError):
        downloader.validate_source({"type": "prefix", "url": "http://insecure.example.com/"})


def test_jwt_and_redact(env):
    import base64, hmac
    from nailong_agent import astrbot, redact
    tok = astrbot.make_jwt("k", "astrbot")
    h, p, s = tok.split(".")
    calc = base64.urlsafe_b64encode(hmac.new(b"k", (h + "." + p).encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    assert calc == s
    assert json.loads(base64.urlsafe_b64decode(p + "==").decode())["username"] == "astrbot"
    redact.add_secret("napcat-webui-token")
    line = redact.parse_line('2026-10-28T06:00:00.123Z \x1b[31m[ERRO]\x1b[0m token="abcdef123" napcat-webui-token Bearer abcdefghijk')
    assert line["level"] == "ERROR"
    assert "abcdef123" not in line["text"] and "napcat-webui-token" not in line["text"] and "abcdefghijk" not in line["text"]
    assert line["time"] == "2026-10-28 06:00:00"
    assert "\x1b" not in line["text"]
