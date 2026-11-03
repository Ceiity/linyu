"""Offline regression tests for discovery, caching and exact config rollback."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mirror_catalog", ROOT / "scripts" / "mirror-catalog.py")
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)


class MirrorCatalogTest(unittest.TestCase):
    def test_normalization(self):
        for bad in ("http://bad.example", "https://127.0.0.1", "https://foo.local", "https://user:pass@a.example", "https://a.example/?x=y", "https://a.example;id/x", "https://a.example/a/../b"):
            self.assertEqual(catalog.normalize(bad, "docker"), "", bad)
        self.assertEqual(catalog.normalize("https://Docker.Example/", "docker"), "https://docker.example")
        self.assertEqual(catalog.normalize("https://proxy.example", "github"), "https://proxy.example/")
        self.assertEqual(catalog.normalize("https://pypi.example/simple/", "pip"), "https://pypi.example/simple")

    def test_schema_dedupe_and_limit(self):
        value = {"version": 1, "docker": ["https://docker.example/"] * 3 + ["$(touch x)"]}
        self.assertEqual(catalog.parse_catalog(json.dumps(value))["docker"], ["https://docker.example"])
        for invalid in ({"version": 99}, [], {"version": 1, "docker": "not a list"}):
            with self.assertRaises(ValueError):
                catalog.parse_catalog(json.dumps(invalid))
        self.assertEqual(len(catalog.unique(str(i) for i in range(100))), 32)

    def test_markdown_only_active_address_column(self):
        text = """## DockerHub国内镜像加速源列表
| Name | Address |
| --- | --- |
| [Info](https://wrong.example) | `https://ok.example/` |
| Legacy | ~~`https://dead.example`~~ |
| 需要注册登录获取令牌 | `https://paid.example` |
| 只支持内网 | `https://internal.example` |
| Bare | `bare.example` |
### 已失效DockerHub加速镜像仓库
| Old | `https://expired.example` |
"""
        self.assertEqual(catalog.parse_docker_markdown(text)["docker"], ["https://ok.example", "https://bare.example"])
        with self.assertRaises(ValueError):
            catalog.parse_docker_markdown("<html>Bad gateway</html>")

    def test_atomic_config_preserves_other_keys_and_exact_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "daemon.json"
            original = b'{ "log-driver": "json-file", "registry-mirrors": ["https://old.example"] }\n'
            p.write_bytes(original)
            result = catalog.configure_docker(p, ["https://new.example"])
            self.assertTrue(result["changed"])
            self.assertEqual(Path(result["backup"]).read_bytes(), original)
            self.assertEqual(json.loads(p.read_text())["log-driver"], "json-file")
            self.assertFalse(catalog.configure_docker(p, ["https://new.example"])["changed"])
            catalog.restore_docker(p, result["backup"])
            self.assertEqual(p.read_bytes(), original)
            self.assertEqual(len(list(Path(tmp).glob("*.bak"))), 1)

    def test_new_config_restore_and_corrupt_config_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "docker" / "daemon.json"
            result = catalog.configure_docker(p, ["http://127.0.0.1:5000"])
            self.assertEqual(result["backup"], "-")
            catalog.restore_docker(p, "-")
            self.assertFalse(p.exists())
            for bad in (b"broken-json", b"[]", b"null"):
                p.write_bytes(bad)
                with self.assertRaises(ValueError):
                    catalog.configure_docker(p, ["https://new.example"])
                self.assertEqual(p.read_bytes(), bad)

    def test_cache_reuse_and_offline_stale_fallback(self):
        class Response(io.BytesIO):
            url = "https://catalog.example/list.json"

        data = json.dumps({"version": 1, "docker": ["https://one.example"]}).encode()
        with tempfile.TemporaryDirectory() as tmp, patch.object(catalog, "urlopen", return_value=Response(data)) as request:
            args = ("https://catalog.example/list.json", catalog.parse_catalog, Path(tmp), 2, 60)
            first = catalog.cached_source(*args)
            second = catalog.cached_source(*args)
            self.assertEqual(first, second)
            self.assertEqual(request.call_count, 1)
            p = next(Path(tmp).glob("*.json"))
            old = json.loads(p.read_text())
            old["checked_at"] = 0
            p.write_text(json.dumps(old))
            with patch.object(catalog, "urlopen", side_effect=OSError("offline")):
                self.assertEqual(catalog.cached_source(*args), first)

    def test_size_limit_and_invalid_catalog_fallback(self):
        class Response(io.BytesIO):
            url = "https://catalog.example/list.json"

        with tempfile.TemporaryDirectory() as tmp:
            args = ("https://catalog.example/list.json", catalog.parse_catalog, Path(tmp), 2, 60)
            with patch.object(catalog, "urlopen", return_value=Response(b"x" * (catalog.MAX_BYTES + 1))):
                self.assertEqual(catalog.cached_source(*args), {})

    def test_discovery_off_uses_local_catalog_without_network(self):
        args = type("Args", (), {"kind": "docker", "cache_dir": "unused", "timeout": 1, "ttl": 60})()
        with patch.dict(os.environ, {"MIRROR_DISCOVERY": "off"}), patch.object(catalog, "urlopen") as request, patch("sys.stdout", new_callable=io.StringIO) as stdout:
            catalog.candidates(args)
            request.assert_not_called()
            self.assertIn("https://docker.1ms.run", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
