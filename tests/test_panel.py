"""Unit tests for panel/backend/app.py. Run: python3 -m unittest discover -s tests"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = tempfile.TemporaryDirectory()
os.environ["INSTALL_PREFIX"] = str(Path(TMP.name) / "install")
os.environ["PROJECT_DIR"] = str(ROOT)
os.environ["PANEL_CONFIG"] = str(Path(TMP.name) / "panel_config.json")
os.environ["STATE_FILE"] = str(Path(TMP.name) / ".env")
os.environ["PANEL_AUDIT_LOG"] = str(Path(TMP.name) / "audit.log")
_spec = importlib.util.spec_from_file_location("panel_app_under_test", ROOT / "panel" / "backend" / "app.py")
app = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = app
_spec.loader.exec_module(app)


def multipart_body(boundary: str, parts: list[tuple[str, str | None, bytes]]) -> bytes:
    out = b""
    for name, filename, data in parts:
        disp = 'form-data; name="%s"' % name
        if filename is not None:
            disp += '; filename="%s"' % filename
        out += ("--%s\r\nContent-Disposition: %s\r\n\r\n" % (boundary, disp)).encode("utf-8") + data + b"\r\n"
    return out + ("--%s--\r\n" % boundary).encode()


class MultipartTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(dir=TMP.name))

    def parse(self, body: bytes, boundary: str = "XyZ", **kw):
        kw.setdefault("max_file_bytes", 10 * 1024 * 1024)
        return app.parse_multipart(io.BytesIO(body), "multipart/form-data; boundary=" + boundary, len(body), self.dir, **kw)

    def test_files_and_fields(self):
        big = os.urandom(300_000) + b"\r\n--Xy\r\n--XyY" + os.urandom(1000)
        body = multipart_body("XyZ", [("access", None, b"private"), ("files", "a.txt", b"hello"), ("files", "奶龙.bin", big), ("files", "", b"")])
        # Tiny chunks force delimiters to straddle reads.
        parts = self.parse(body, chunk_size=7)
        fields = {p.name: p.value for p in parts if p.filename is None}
        files = [p for p in parts if p.filename]
        self.assertEqual(fields, {"access": "private"})
        self.assertEqual([p.filename for p in files], ["a.txt", "奶龙.bin"])
        self.assertEqual(files[0].path.read_bytes(), b"hello")
        self.assertEqual(files[1].path.read_bytes(), big)
        self.assertEqual(files[1].size, len(big))
        for p in parts:
            p.discard()
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_quoted_boundary_and_preamble(self):
        body = b"preamble junk\r\n" + multipart_body("a b", [("file", "x.json", b"{}")])
        parts = app.parse_multipart(io.BytesIO(body), 'multipart/form-data; boundary="a b"', len(body), self.dir, max_file_bytes=100)
        self.assertEqual(parts[0].path.read_bytes(), b"{}")
        parts[0].discard()

    def test_file_too_large_cleans_up(self):
        body = multipart_body("XyZ", [("files", "a.bin", b"x" * 2048)])
        with self.assertRaises(app.PayloadTooLarge):
            self.parse(body, max_file_bytes=1024)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_truncated_body_rejected(self):
        body = multipart_body("XyZ", [("files", "a.bin", b"data")])[:-12]
        with self.assertRaises(ValueError):
            self.parse(body)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_too_many_files(self):
        body = multipart_body("XyZ", [("files", "%d.txt" % i, b"x") for i in range(3)])
        with self.assertRaises(ValueError):
            self.parse(body, max_files=2)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_wrong_content_type(self):
        with self.assertRaises(ValueError):
            app.parse_multipart(io.BytesIO(b""), "application/json", 0, self.dir, max_file_bytes=1)


class ClientIpTest(unittest.TestCase):
    def test_headers_ignored_from_remote_peer(self):
        self.assertEqual(app.trusted_client_ip("8.8.8.8", {"X-Forwarded-For": "1.1.1.1", "X-Real-IP": "1.1.1.1"}), "8.8.8.8")

    def test_proxy_headers_trusted_from_loopback(self):
        self.assertEqual(app.trusted_client_ip("127.0.0.1", {"X-Real-IP": "203.0.113.9"}), "203.0.113.9")
        # Nginx appends the real peer last; anything before it is client-supplied.
        self.assertEqual(app.trusted_client_ip("127.0.0.1", {"X-Forwarded-For": "6.6.6.6, 203.0.113.9"}), "203.0.113.9")
        self.assertEqual(app.trusted_client_ip("::1", {"X-Real-IP": "garbage"}), "::1")


class ConfigTest(unittest.TestCase):
    def test_cache_returns_copies_and_sees_writes(self):
        cfg = app.load_config()
        cfg["theme_color"] = "#000000"
        self.assertNotEqual(app.load_config()["theme_color"], "#000000")
        app.save_config(cfg)
        self.assertEqual(app.load_config()["theme_color"], "#000000")

    def test_load_does_not_rehash_password(self):
        app.load_config()
        calls = []
        original = app.hash_password
        app.hash_password = lambda *a, **k: calls.append(1) or original(*a, **k)
        try:
            for _ in range(20):
                app.load_config()
        finally:
            app.hash_password = original
        self.assertEqual(calls, [])

    def test_legacy_keys_migrate(self):
        cfg = app.load_config()
        for key in [k for k in cfg if k.startswith("nailong_remote_")]:
            cfg.pop(key)
        cfg["linyu_remote_owner_ids"] = "123"
        cfg["linyu_remote_public_login_enabled"] = True
        app.write_json(app.PANEL_CONFIG, cfg)
        migrated = app.load_config()
        self.assertEqual(migrated["nailong_remote_owner_ids"], "123")
        self.assertTrue(migrated["nailong_remote_public_login_enabled"])
        self.assertFalse(any(k.startswith("linyu_remote_") for k in migrated))
        on_disk = json.loads(app.PANEL_CONFIG.read_text(encoding="utf-8"))
        self.assertIn("nailong_remote_owner_ids", on_disk)


    def test_initial_password_not_resurrected(self):
        cfg = app.load_config()
        cfg.pop("initial_password", None)
        cfg["password_changed_at"] = app.now()
        app.save_config(cfg)
        self.assertNotIn("initial_password", app.load_config())
        cfg["initial_password"] = "stale-random"
        app.write_json(app.PANEL_CONFIG, cfg)
        self.assertNotIn("initial_password", app.load_config())


class PluginMigrationTest(unittest.TestCase):
    def test_legacy_plugin_replaced(self):
        root = Path(app.load_config()["astrbot_plugin_dir"])
        legacy = root / app.LEGACY_REMOTE_PLUGIN_NAME
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / "main.py").write_text("old", encoding="utf-8")
        legacy_cfg = app.INSTALL_PREFIX / "data" / "config" / (app.LEGACY_REMOTE_PLUGIN_NAME + "_config.json")
        legacy_cfg.parent.mkdir(parents=True, exist_ok=True)
        legacy_cfg.write_text("{}", encoding="utf-8")
        app.docker = lambda args, timeout=60: (1, "")  # no docker in tests
        result = app.migrate_legacy_remote_plugin()
        self.assertTrue(result["migrated"])
        self.assertFalse(legacy.exists())
        self.assertFalse(legacy_cfg.exists())
        self.assertTrue((root / app.REMOTE_PLUGIN_NAME / "main.py").exists())
        self.assertTrue((app.INSTALL_PREFIX / "data" / "config" / (app.REMOTE_PLUGIN_NAME + "_config.json")).exists())
        self.assertFalse(app.migrate_legacy_remote_plugin()["migrated"])


class RangeTest(unittest.TestCase):
    def rng(self, header: str, size: int = 100):
        dummy = type("D", (), {"headers": {"Range": header}})()
        return app.Handler.requested_range(dummy, size)

    def test_ranges(self):
        self.assertIsNone(self.rng(""))
        self.assertEqual(self.rng("bytes=0-9"), (0, 9))
        self.assertEqual(self.rng("bytes=90-"), (90, 99))
        self.assertEqual(self.rng("bytes=-10"), (90, 99))
        self.assertEqual(self.rng("bytes=50-500"), (50, 99))
        with self.assertRaises(app.RangeNotSatisfiable):
            self.rng("bytes=200-300")


class TaskTest(unittest.TestCase):
    def test_tasks_bounded(self):
        for i in range(app.MAX_TASKS + 20):
            t = app.Task(id="t%d" % i, title="x", kind="x", status="success")
            app.TASKS[t.id] = t
        app.prune_tasks()
        self.assertLessEqual(len(app.TASKS), app.MAX_TASKS)
        self.assertEqual(len(app.recent_tasks(5)), 5)


class LoginErrorTest(unittest.TestCase):
    def test_messages_are_readable(self):
        key = app.login_key_for_ip("127.0.0.1")
        with self.assertRaises(ValueError) as ctx:
            app.decrypt_login_payload({"mode": "crypto", "encrypted": {"challenge_id": "nope"}}, key)
        self.assertNotIn("?", str(ctx.exception))
        challenge = app.new_login_challenge(key)
        if challenge.get("enabled"):
            with self.assertRaises(ValueError) as ctx:
                app.decrypt_login_payload({"mode": "crypto", "encrypted": {"challenge_id": challenge["id"], "key": "!!"}}, key)
            self.assertIn("解密失败", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
