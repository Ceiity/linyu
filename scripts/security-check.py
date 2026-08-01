#!/usr/bin/env python3
"""Fast regression checks for the panel's highest-risk security boundaries."""
from __future__ import annotations

import importlib.util
import http.client
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import threading
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def load_app(tmp: Path):
    os.environ["INSTALL_PREFIX"] = str(tmp / "install")
    os.environ["PROJECT_DIR"] = str(ROOT)
    os.environ["PANEL_CONFIG"] = str(tmp / "panel_config.json")
    os.environ["STATE_FILE"] = str(tmp / ".env")
    spec = importlib.util.spec_from_file_location("panel_security_check_app", ROOT / "panel" / "backend" / "app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def expect_failure(fn, label: str) -> None:
    try:
        fn()
    except (ValueError, PermissionError):
        return
    raise AssertionError(label)


def main() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        app = load_app(tmp)
        cfg = app.default_config()
        cfg.update({
            "remote_api_token": "remote-secret",
            "linyu_remote_owner_ids": "10001",
            "linyu_remote_bot_self_ids": "20002",
            "linyu_remote_public_login_enabled": False,
        })
        app.write_json(app.PANEL_CONFIG, cfg)

        base = tmp / "base"
        base.mkdir()
        assert app.path_under(base, "ok/file.txt") == (base / "ok/file.txt").resolve()
        expect_failure(lambda: app.path_under(base, "../escape"), "path traversal accepted")

        good_zip = tmp / "good.zip"
        with zipfile.ZipFile(good_zip, "w") as z:
            z.writestr("plugin/main.py", "x = 1\n")
        assert app.safe_extract_zip(good_zip, tmp / "plugins")

        dot_zip = tmp / "dot.zip"
        with zipfile.ZipFile(dot_zip, "w") as z:
            z.writestr("./main.py", "x = 1\n")
        expect_failure(lambda: app.safe_extract_zip(dot_zip, tmp / "plugins-dot"), "dot-root ZIP accepted")

        traversal_zip = tmp / "traversal.zip"
        with zipfile.ZipFile(traversal_zip, "w") as z:
            z.writestr("../escape.py", "x = 1\n")
        expect_failure(lambda: app.safe_extract_zip(traversal_zip, tmp / "plugins-traversal"), "traversal ZIP accepted")

        symlink_zip = tmp / "symlink.zip"
        with zipfile.ZipFile(symlink_zip, "w") as z:
            info = zipfile.ZipInfo("plugin/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "/etc/passwd")
        expect_failure(lambda: app.safe_extract_zip(symlink_zip, tmp / "plugins-link"), "symlink ZIP accepted")

        good_tar = tmp / "good.tar.gz"
        payload = b"backup"
        with tarfile.open(good_tar, "w:gz") as t:
            info = tarfile.TarInfo("data/file.txt")
            info.size = len(payload)
            t.addfile(info, io.BytesIO(payload))
        app.validate_backup_archive(good_tar)

        bad_tar = tmp / "bad.tar.gz"
        with tarfile.open(bad_tar, "w:gz") as t:
            info = tarfile.TarInfo("../outside")
            info.size = len(payload)
            t.addfile(info, io.BytesIO(payload))
        expect_failure(lambda: app.validate_backup_archive(bad_tar), "traversal TAR accepted")

        class Dummy:
            def __init__(self, headers=None, body=b""):
                self.headers = headers or {}
                self.rfile = io.BytesIO(body)
                self.client_address = ("127.0.0.1", 12345)
                self.server = type("Server", (), {"server_port": 7070})()

        header_auth = Dummy({"X-Remote-Token": "remote-secret"})
        assert app.Handler.remote_auth_ok(header_auth, {})
        body_auth = Dummy()
        assert not app.Handler.remote_auth_ok(body_auth, {"remote_token": "remote-secret"})

        principal = Dummy()
        claimed_public = {"requester": "other", "bot_self_id": "20002", "public_login_enabled": True}
        assert not app.Handler.remote_principal_ok(principal, claimed_public, allow_public_login=True)
        cfg["linyu_remote_public_login_enabled"] = True
        app.write_json(app.PANEL_CONFIG, cfg)
        assert app.Handler.remote_principal_ok(principal, claimed_public, allow_public_login=True)

        raw_file_token = "fc_test_token"
        cfg["file_api_tokens"] = [{
            "id": "upload-only",
            "name": "Uploader",
            "hash": app.hashlib.sha256(raw_file_token.encode()).hexdigest(),
            "disabled": False,
            "scopes": ["files:upload"],
        }]
        app.write_json(app.PANEL_CONFIG, cfg)
        file_token = Dummy({"Authorization": "Bearer " + raw_file_token})
        assert app.Handler.file_api_user(file_token, "files:upload")
        assert not app.Handler.file_api_user(file_token, "files:read")
        assert not app.Handler.file_api_user(file_token, "files:delete")

        cross = Dummy({"Origin": "https://evil.example", "Host": "panel.example"})
        same = Dummy({"Origin": "https://panel.example", "Host": "panel.example", "X-Forwarded-Proto": "https"})
        assert not app.Handler.same_origin_request_ok(cross)
        assert app.Handler.same_origin_request_ok(same)

        oversized = Dummy({"Content-Length": str(app.MAX_JSON_BODY_BYTES + 1)}, b"")
        expect_failure(lambda: app.Handler.read_body(oversized), "oversized JSON body accepted")
        wrong_type = Dummy({"Content-Type": "text/plain", "Content-Length": "2"}, b"{}")
        expect_failure(lambda: app.Handler.read_json(wrong_type), "non-JSON content type accepted")

        for _ in range(app.LOGIN_CHALLENGE_LIMIT):
            allowed, _ = app.login_challenge_allowed("rate-test")
            assert allowed
        allowed, retry_after = app.login_challenge_allowed("rate-test")
        assert not allowed and retry_after > 0

        headers = []
        untrusted = Dummy({})
        untrusted.send_header = lambda key, value: headers.append((key.lower(), value))
        app.Handler.security_headers(untrusted, untrusted_content=True)
        csp = dict(headers).get("content-security-policy", "")
        assert "sandbox" in csp and "default-src 'none'" in csp
        assert app.untrusted_file_requires_download("text/html", "page.html")
        assert app.untrusted_file_requires_download("image/svg+xml", "image.svg")
        assert not app.untrusted_file_requires_download("image/png", "image.png")

        server = app.PanelServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_port
        try:
            def request(method: str, path: str, body: bytes | None = None, headers: dict | None = None):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request(method, path, body=body, headers=headers or {})
                response = conn.getresponse()
                payload = response.read()
                result = response.status, dict((k.lower(), v) for k, v in response.getheaders()), payload
                conn.close()
                return result

            status, _, _ = request("GET", "/api/settings")
            assert status == 401

            remote_body = json.dumps({
                "remote_token": "remote-secret",
                "requester": "10001",
                "bot_self_id": "20002",
            }).encode()
            status, _, _ = request("POST", "/api/remote/astrbot/no-prefix", remote_body, {"Content-Type": "application/json"})
            assert status == 403

            session = app.Handler.make_session(Dummy(), cfg["username"])
            cookie = "adb_session=" + session
            report = json.dumps({"system": "test"}).encode()
            status, _, _ = request(
                "POST",
                "/api/device/report",
                report,
                {"Content-Type": "application/json", "Cookie": cookie, "Origin": "https://evil.example"},
            )
            assert status == 403

            boundary = "----security-check-boundary"
            html = b"<script>document.body.textContent='unsafe'</script>"
            multipart = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"attack.html\"\r\n"
                "Content-Type: text/html\r\n\r\n"
            ).encode() + html + f"\r\n--{boundary}--\r\n".encode()
            status, _, payload = request(
                "POST",
                "/api/files/upload",
                multipart,
                {
                    "Content-Type": "multipart/form-data; boundary=" + boundary,
                    "Cookie": cookie,
                    "Origin": f"http://127.0.0.1:{port}",
                },
            )
            assert status == 200, payload
            uploaded = json.loads(payload)["data"]
            status, response_headers, _ = request("GET", f"/files/{uploaded['id']}/attack.html")
            assert status == 200
            assert response_headers.get("content-disposition", "").startswith("attachment;")
            assert "sandbox" in response_headers.get("content-security-policy", "")
        finally:
            server.shutdown()
            server.server_close()

    print("security regression checks passed")


if __name__ == "__main__":
    main()
