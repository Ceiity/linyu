import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from test_agent import env  # noqa: F401


@pytest.fixture()
def client(env):  # noqa: F811
    import importlib
    from nailong_agent import main
    importlib.reload(main)
    (env["data"] / "pairing.json").write_text(json.dumps({"codes": [
        {"hash": hashlib.sha256(b"PAIRCODE2345").hexdigest(), "expires": time.time() + 60, "used": False}]}))
    with TestClient(main.app) as c:
        yield c


def test_api_requires_auth(client):
    assert client.get("/healthz").json()["ok"]
    for path in ("/api/overview", "/api/plugins", "/api/backups", "/api/devices", "/api/sources"):
        r = client.get(path)
        assert r.status_code == 401, path
    r = client.get("/api/overview", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_pair_and_use(client):
    r = client.post("/api/pair", json={"code": "PAIRCODE2345", "device_name": "Test"})
    assert r.status_code == 200, r.text
    tok = r.json()["data"]["token"]
    h = {"Authorization": "Bearer " + tok}
    assert client.get("/api/me", headers=h).json()["data"]["device"]["name"] == "Test"
    m = client.get("/api/metrics", headers=h).json()["data"]
    assert m["mem_total"] > 0 and "net_rx_bps" in m
    # 非奶龙管理的容器不可操作
    r = client.post("/api/docker/containers/some-other/stop", headers=h)
    assert r.status_code == 403
    r = client.post("/api/services/astrbot/rm", headers=h)
    assert r.status_code == 400
    # 下载源只接受 HTTPS
    r = client.put("/api/sources", headers=h, json={"github": [{"type": "prefix", "url": "http://x.example.com/"}]})
    assert r.status_code == 400
    r = client.put("/api/sources", headers=h, json={"github": [{"type": "prefix", "url": "https://gh.example.com/"}],
                                                    "registries": ["https://mirror.example.com"], "pypi": ["https://pypi.example.com/simple"]})
    assert r.status_code == 200, r.text
    srcs = client.get("/api/sources", headers=h).json()["data"]
    assert srcs["github"][0]["id"] == "official" and srcs["registries"] == ["mirror.example.com"]
    # 恢复必须输入文件名确认
    r = client.post("/api/backups/nailong-backup-20260101-000000.tar.gz/restore", headers=h, json={"confirm": "x"})
    assert r.status_code == 400
    # 轮换后旧令牌失效
    new = client.post("/api/token/rotate", headers=h).json()["data"]["token"]
    assert client.get("/api/me", headers=h).status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer " + new}).status_code == 200


def test_ws_logs_requires_token(client):
    with client.websocket_connect("/ws/logs") as ws:
        ws.send_text(json.dumps({"token": "bad", "target": "astrbot"}))
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "error"
