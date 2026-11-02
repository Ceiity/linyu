"""Tests for panel/backend/nailong_ng (NG 2.0). Run: python3 -m unittest discover -s tests"""
from __future__ import annotations

import json
import re
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "panel" / "backend"))

from nailong_ng import login_codes as lc  # noqa: E402
from nailong_ng import rfb  # noqa: E402
from nailong_ng.host import Host  # noqa: E402
from nailong_ng.login_state import LoginAbort, LoginDriver, LoginManager  # noqa: E402
from nailong_ng.manager import ProtocolManager  # noqa: E402
from nailong_ng.protocols import ProtocolError, parse_proc_net_tcp, snowluma_container_for  # noqa: E402
from nailong_ng.sshdeploy import SecretBox, SSHError, SSHServers, evaluate  # noqa: E402


class LoginCodesTest(unittest.TestCase):
    def test_napcat_qr_expired_string(self):
        err = lc.parse_napcat_login_error("二维码已过期，请刷新")
        self.assertEqual(err["code"], "QR_EXPIRED")
        self.assertEqual(err["state"], "EXPIRED")
        self.assertEqual(err["protocol"], "napcat")

    def test_napcat_login_failed_keeps_server_code(self):
        raw = '登录失败: [1,{"serverErrorCode":12345,"message":"当前网络不稳定，请稍后重试"}]'
        err = lc.parse_napcat_login_error(raw, "WAITING_CONFIRMATION")
        self.assertEqual(err["code"], "NETWORK_ERROR")
        self.assertEqual(err["raw_code"], "12345")
        self.assertIn("当前网络不稳定", err["raw_message"])
        self.assertEqual(err["stage"], "WAITING_CONFIRMATION")

    def test_napcat_verified_result_codes(self):
        self.assertEqual(lc.parse_napcat_login_error('登录失败: [0,{"serverErrorCode":"140022010","message":"x"}]')["code"], "DEVICE_VERIFY")
        self.assertEqual(lc.parse_napcat_login_error('登录失败: [0,{"serverErrorCode":"140022008","message":"x"}]')["code"], "NEED_VERIFY")
        self.assertEqual(lc.parse_napcat_login_error('登录失败: [0,{"serverErrorCode":"140022011","message":"x"}]')["code"], "ENV_ABNORMAL")

    def test_unknown_is_preserved_not_invented(self):
        err = lc.parse_napcat_login_error('登录失败: [0,{"serverErrorCode":99,"message":"奇怪的错误"}]')
        self.assertEqual(err["code"], "UNKNOWN")
        self.assertEqual(err["raw_code"], "99")
        self.assertEqual(err["classified_by"], "default")

    def test_rejection_classified_from_message(self):
        err = lc.parse_napcat_login_error('登录失败: [0,{"serverErrorCode":7,"message":"你已拒绝本次登录"}]')
        self.assertEqual(err["code"], "USER_REJECTED")
        self.assertEqual(err["state"], "REJECTED")

    def test_napcat_log_errtype(self):
        log = "x\n[Core] [Login] Login Error,ErrType:  1  ErrCode: 3\n[Core] [Login] Login Error,ErrType:  1  ErrCode: 17\n"
        errs = lc.parse_napcat_log(log)
        self.assertEqual([e["code"] for e in errs], ["QR_EXPIRED", "UNKNOWN"])
        self.assertEqual(errs[1]["raw_code"], "ErrType=1 ErrCode=17")

    def test_snowluma_log(self):
        log = ("[x] awaiting login: PID=42\n[x] login identity discovered: PID=42 UIN=10001; awaiting readiness\n"
               "[x] session started: UIN=10001\n[x] QQ runtime unavailable: PID=42 err=boom\n")
        ev = lc.parse_snowluma_log(log)
        self.assertEqual([e["kind"] for e in ev], ["awaiting", "identity", "session_started", "error"])
        self.assertEqual(ev[1]["uin"], "10001")
        self.assertEqual(ev[3]["error"]["code"], "CLIENT_ERROR")

    def test_catalog_has_required_states(self):
        need = {"QR_FETCH_FAILED", "QR_EXPIRED", "QR_INVALID", "USER_REJECTED", "USER_CANCELLED", "CONFIRM_TIMEOUT", "NEED_VERIFY",
                "DEVICE_VERIFY", "ENV_ABNORMAL", "NETWORK_ERROR", "CLIENT_ERROR", "LOGIN_DENIED", "ACCOUNT_RESTRICTED", "UNKNOWN"}
        self.assertTrue(need <= set(lc.CATALOG))


# ---------------------------------------------------------------------------
class FakeVNC(threading.Thread):
    """RFB 3.8 server with VNC auth; draws a 'window' on a flat desktop and records clicks."""

    def __init__(self, password="s3cret", w=200, h=120, image=None):
        super().__init__(daemon=True)
        self.password, self.w, self.h = password, w, h
        self.image = image
        if image is not None:
            self.w, self.h = image.size
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.clicks = []
        self.auth_ok = None

    def run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            try:
                self.serve(conn)
            except Exception:
                pass
            finally:
                conn.close()

    def recv(self, c, n):
        b = b""
        while len(b) < n:
            x = c.recv(n - len(b))
            if not x:
                raise EOFError
            b += x
        return b

    def serve(self, c):
        c.sendall(b"RFB 003.008\n")
        self.recv(c, 12)
        c.sendall(b"\x01\x02")
        assert self.recv(c, 1) == b"\x02"
        chal = bytes(range(16))
        c.sendall(chal)
        resp = self.recv(c, 16)
        self.auth_ok = resp == rfb.vnc_des_response(self.password, chal)
        if not self.auth_ok:
            c.sendall(struct.pack(">I", 1) + struct.pack(">I", 5) + b"wrong")
            return
        c.sendall(struct.pack(">I", 0))
        self.recv(c, 1)
        c.sendall(struct.pack(">HH", self.w, self.h) + b"\0" * 16 + struct.pack(">I", 4) + b"test")
        while True:
            t = self.recv(c, 1)[0]
            if t == 0:
                self.recv(c, 19)
            elif t == 2:
                _, n = struct.unpack(">BH", self.recv(c, 3))
                self.recv(c, 4 * n)
            elif t == 3:
                self.recv(c, 9)
                if self.image is not None:
                    fb = bytearray(self.image.convert("RGBX").tobytes("raw", "BGRX"))
                    c.sendall(struct.pack(">BxH", 0, 1) + struct.pack(">HHHHi", 0, 0, self.w, self.h, 0) + bytes(fb))
                    continue
                fb = bytearray(b"\x40\x30\x20\x00" * (self.w * self.h))
                for y in range(30, 90):
                    for x in range(60, 140):
                        i = (y * self.w + x) * 4
                        fb[i:i + 4] = b"\xff\xff\xff\x00"
                c.sendall(struct.pack(">BxH", 0, 1) + struct.pack(">HHHHi", 0, 0, self.w, self.h, 0) + bytes(fb))
            elif t == 5:
                mask, x, y = struct.unpack(">BHH", self.recv(c, 5))
                if mask:
                    self.clicks.append((x, y))
            else:
                return


class RFBTest(unittest.TestCase):
    def test_capture_crops_to_window_and_click_maps_back(self):
        srv = FakeVNC()
        srv.start()
        shot = rfb.capture("127.0.0.1", srv.port, "s3cret")
        self.assertTrue(srv.auth_ok)
        self.assertEqual(shot["screen"], {"width": 200, "height": 120})
        x0, y0, x1, y1 = shot["box"]
        self.assertTrue(40 <= x0 <= 60 and 16 <= y0 <= 30 and 140 <= x1 <= 160 and 90 <= y1 <= 106, shot["box"])
        self.assertFalse(shot["blank"])
        sx, sy = rfb.map_click(10, 10, shot)
        rfb.click("127.0.0.1", srv.port, "s3cret", sx, sy)
        for _ in range(50):
            if srv.clicks:
                break
            time.sleep(0.02)
        self.assertEqual(srv.clicks[-1], (x0 + 10, y0 + 10))
        srv.sock.close()

    def _qq_screen(self, box_size=4, logo=True):
        import qrcode
        from PIL import Image, ImageDraw
        q = qrcode.QRCode(box_size=box_size, border=0, error_correction=qrcode.constants.ERROR_CORRECT_H)
        q.add_data("https://txz.qq.com/p?k=nailong-test-0123456789&f=716027609")
        q.make()
        qi = q.make_image().convert("RGB")
        if logo:
            c = qi.size[0] // 2
            ImageDraw.Draw(qi).rounded_rectangle((c - 14, c - 14, c + 14, c + 14), 6, fill=(18, 183, 245))
        scr = Image.new("RGB", (640, 480), (45, 52, 64))
        win = Image.new("RGB", (260, 360), "white")
        d = ImageDraw.Draw(win)
        for i in range(4):
            d.text((20, 12 + i * 12), "QQ login %d" % i, fill="black")
        win.paste(qi, (130 - qi.size[0] // 2, 190 - qi.size[1] // 2))
        scr.paste(win, (190, 60))
        ImageDraw.Draw(scr).rectangle((0, 460, 640, 480), fill=(20, 20, 20))  # toolbar
        return scr, (190 + 130 - qi.size[0] // 2, 60 + 190 - qi.size[1] // 2, qi.size[0])

    def test_find_qr_exact(self):
        scr, (qx, qy, side) = self._qq_screen()
        win_box = rfb.content_box(scr)
        self.assertTrue(win_box[0] <= 190 and win_box[2] >= 450 and win_box[2] < 500, win_box)  # toolbar ignored
        found = rfb.find_qr(scr.crop(win_box))
        self.assertIsNotNone(found)
        x0, y0, x1, y1, m = found
        self.assertAlmostEqual(win_box[0] + x0, qx, delta=1.5)
        self.assertAlmostEqual(win_box[1] + y0, qy, delta=1.5)
        self.assertAlmostEqual(x1 - x0, side, delta=2)
        self.assertAlmostEqual(m, 4, delta=0.5)

    def test_find_qr_none_without_code(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (300, 300), "white")
        ImageDraw.Draw(img).text((20, 20), "扫码成功 请在手机上确认", fill="black")
        self.assertIsNone(rfb.find_qr(img))

    def test_capture_centres_qr_and_clicks_map_back(self):
        scr, (qx, qy, side) = self._qq_screen()
        srv = FakeVNC(image=scr)
        srv.start()
        shot = rfb.capture("127.0.0.1", srv.port, "s3cret")
        self.assertTrue(shot["qr_found"])
        self.assertEqual(shot["image"]["width"], 360)
        x0, y0, x1, y1 = shot["box"]
        self.assertEqual(x1 - x0, y1 - y0)  # square
        # QR centred inside the crop
        self.assertAlmostEqual((x0 + x1) / 2, qx + side / 2, delta=2)
        self.assertAlmostEqual((y0 + y1) / 2, qy + side / 2, delta=2)
        sx, sy = rfb.map_click(180, 180, shot)  # click the middle of the shown code
        self.assertAlmostEqual(sx, qx + side / 2, delta=3)
        self.assertAlmostEqual(sy, qy + side / 2, delta=3)
        srv.sock.close()

    def test_wrong_password(self):
        srv = FakeVNC()
        srv.start()
        with self.assertRaises(rfb.RFBError):
            rfb.capture("127.0.0.1", srv.port, "nope")
        srv.sock.close()


# ---------------------------------------------------------------------------
class ScriptDriver(LoginDriver):
    protocol = "napcat"
    poll_interval = 0.02
    max_qr_refreshes = 2

    def __init__(self, script, precheck_abort=None):
        self.script = list(script)
        self.precheck_abort = precheck_abort
        self.refreshes = 0

    def precheck(self, task):
        if self.precheck_abort:
            raise LoginAbort(self.precheck_abort)

    def start(self, task):
        task.set_qr({"kind": "url", "key": "u1", "url": "u1"})

    def poll(self, task):
        return self.script.pop(0) if self.script else {}

    def refresh(self, task):
        self.refreshes += 1
        task.set_qr({"kind": "url", "key": "r%d" % self.refreshes, "url": "r%d" % self.refreshes})


def wait_terminal(mgr, slot, seconds=3):
    deadline = time.time() + seconds
    while time.time() < deadline:
        t = mgr.current(slot)
        if t and t.terminal:
            return t
        time.sleep(0.01)
    return mgr.current(slot)


class LoginStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def mgr(self, driver, **kw):
        return LoginManager(lambda slot: driver, self.tmp / "login.log", **kw)

    def test_happy_path_timeline(self):
        drv = ScriptDriver([{}, {"state": "SCANNED"}, {"state": "WAITING_CONFIRMATION"}, {"state": "SUCCESS", "account": {"uin": "1"}}])
        done = []
        m = self.mgr(drv, on_success=lambda t: done.append(t.id))
        task = m.request("napcat01")
        t = wait_terminal(m, "napcat01")
        self.assertEqual(t.state, "SUCCESS")
        for _ in range(200):  # post-login checks run right after SUCCESS is published
            if done:
                break
            time.sleep(0.01)
        self.assertEqual(done, [task.id])
        snap = t.to_dict()
        self.assertEqual([r["status"] for r in snap["timeline"]], ["done"] * 6)
        self.assertEqual(snap["account"]["uin"], "1")
        self.assertTrue((self.tmp / "login.log").read_text())

    def test_single_task_per_slot_and_restart_generation(self):
        drv = ScriptDriver([{}] * 1000)
        m = self.mgr(drv)
        a = m.request("napcat01")
        b = m.request("napcat01")
        self.assertIs(a, b)
        c = m.request("napcat01", restart=True)
        self.assertEqual(a.state, "CANCELLED")
        self.assertEqual(c.generation, a.generation + 1)
        m.cancel("napcat01", c.id)
        self.assertEqual(wait_terminal(m, "napcat01").state, "CANCELLED")

    def test_qr_seq_and_unchanged_payload(self):
        drv = ScriptDriver([{"qr": {"kind": "url", "key": "u2", "url": "u2"}}] + [{}] * 1000)
        m = self.mgr(drv)
        t = m.request("napcat01")
        time.sleep(0.2)
        snap = t.to_dict(True, 0)
        self.assertEqual(snap["qr"]["url"], "u2")
        self.assertEqual(snap["qr_seq"], 2)
        again = t.to_dict(True, 2)
        self.assertTrue(again["qr"]["unchanged"])
        self.assertNotIn("url", again["qr"])
        m.cancel("napcat01")

    def test_expiry_auto_refresh_is_bounded(self):
        drv = ScriptDriver([{"expired": True}] * 10)
        m = self.mgr(drv)
        m.request("napcat01")
        t = wait_terminal(m, "napcat01")
        self.assertEqual(t.state, "EXPIRED")
        self.assertEqual(t.error["code"], "QR_EXPIRED")
        self.assertEqual(drv.refreshes, 2)

    def test_rejection_error(self):
        err = lc.make_error("USER_REJECTED", "napcat", "WAITING_CONFIRMATION", "7", "拒绝")
        m = self.mgr(ScriptDriver([{"state": "SCANNED"}, {"error": err}]))
        m.request("napcat01")
        t = wait_terminal(m, "napcat01")
        self.assertEqual(t.state, "REJECTED")
        self.assertEqual(t.error["raw_code"], "7")

    def test_deadline_and_confirm_timeout(self):
        m = self.mgr(ScriptDriver([{}] * 10000), timeout=0)
        m.request("napcat01")
        self.assertEqual(wait_terminal(m, "napcat01").state, "EXPIRED")
        m2 = self.mgr(ScriptDriver([{"state": "SCANNED"}] + [{}] * 10000), confirm_timeout=0)
        m2.request("napcat02")
        t = wait_terminal(m2, "napcat02")
        self.assertEqual(t.error["code"], "CONFIRM_TIMEOUT")

    def test_precheck_abort_and_consecutive_errors(self):
        m = self.mgr(ScriptDriver([], lc.make_error("PROTOCOL_UNREACHABLE", "napcat")))
        m.request("napcat01")
        self.assertEqual(wait_terminal(m, "napcat01").error["code"], "PROTOCOL_UNREACHABLE")

        class Boom(ScriptDriver):
            def poll(self, task):
                raise RuntimeError("down")
        m2 = self.mgr(Boom([]))
        m2.request("napcat01")
        t = wait_terminal(m2, "napcat01")
        self.assertEqual(t.state, "FAILED")
        self.assertEqual(t.error["code"], "PROTOCOL_UNREACHABLE")

    def test_stale_task_actions_rejected(self):
        m = self.mgr(ScriptDriver([{}] * 1000))
        t = m.request("napcat01")
        with self.assertRaises(ValueError):
            m.refresh("napcat01", "other")
        m.cancel("napcat01", t.id)
        wait_terminal(m, "napcat01")
        with self.assertRaises(ValueError):
            m.refresh("napcat01", t.id)


# ---------------------------------------------------------------------------
class FakeDocker:
    def __init__(self, root: Path):
        self.root = root
        self.c = {}  # name -> dict(running, restart, ips)
        self.calls = []
        self.fail_start = set()
        self.tcp = {}

    def add(self, name, running=True, restart="always"):
        self.c[name] = {"running": running, "restart": restart, "ip": "172.20.0.%d" % (len(self.c) + 2)}

    def __call__(self, args, timeout=60):
        self.calls.append(list(args))
        cmd = args[0]
        if cmd == "inspect":
            n = args[-1]
            if n not in self.c:
                return 1, "Error: No such object"
            x = self.c[n]
            return 0, json.dumps([{"State": {"Running": x["running"], "Status": "running" if x["running"] else "exited"},
                                   "Config": {"Image": "img:%s" % n, "Labels": {}}, "Image": "sha256:1",
                                   "HostConfig": {"RestartPolicy": {"Name": x["restart"]}},
                                   "NetworkSettings": {"Networks": {"astrbot_network": {"IPAddress": x["ip"]}}, "Ports": {}}}])
        if cmd == "start":
            n = args[-1]
            if n in self.fail_start:
                return 1, "failed to start"
            self.c[n]["running"] = True
            return 0, n
        if cmd == "stop":
            self.c[args[-1]]["running"] = False
            return 0, args[-1]
        if cmd == "restart":
            self.c[args[-1]]["running"] = True
            return 0, args[-1]
        if cmd == "update":
            self.c[args[-1]]["restart"] = args[1].split("=", 1)[1]
            return 0, ""
        if cmd == "exec":
            n = args[1]
            if args[2] == "supervisorctl":
                return 0, "qq                               RUNNING   pid 1\nsnowluma                         RUNNING   pid 2\n"
            if args[2] == "cat":
                return 0, self.tcp.get(n, "")
        if cmd == "logs":
            return 0, ""
        if cmd in ("ps", "network", "pull", "tag", "version", "image"):
            return 0, ""
        return 0, ""


class ProtocolSwitchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.prefix = self.tmp / "install"
        (self.prefix / "napcat" / "napcat01" / "config").mkdir(parents=True)
        (self.prefix / "napcat" / "napcat01" / "config" / "onebot11.json").write_text(json.dumps(
            {"network": {"websocketClients": [{"name": "rws", "url": "ws://astrbot:6199/ws", "token": "tok"}]}}))
        (self.prefix / "data").mkdir(parents=True)
        (self.prefix / "data" / "cmd_config.json").write_text(json.dumps({"platform": [
            {"id": "napcat01", "type": "aiocqhttp", "enable": True, "ws_reverse_port": 6199, "ws_reverse_token": "tok"}]}))
        self.d = FakeDocker(self.tmp)
        self.d.add("astrbot")
        self.d.add("napcat01")
        self.bash_calls = []

        def bash(script, timeout=120):
            self.bash_calls.append(script)
            m = re.search(r"snowluma/(snowluma\d+)/docker-compose\.yml' (.*)$", script)
            if m:
                name, sub = m.group(1), m.group(2)
                if sub.startswith("up -d"):
                    if name in self.d.fail_start:
                        return 1, "boom"
                    self.d.c.setdefault(name, {"running": False, "restart": "unless-stopped", "ip": "172.20.0.9"})
                    self.d.c[name]["running"] = True
                elif sub.startswith("up --no-start"):
                    self.d.c.setdefault(name, {"running": False, "restart": "unless-stopped", "ip": "172.20.0.9"})
                elif sub.startswith("down"):
                    self.d.c.pop(name, None)
            return 0, "ok"

        def webui(row, path, payload=None, timeout=10):
            return {"code": 0, "data": {"isLogin": False, "loginPhase": "waiting_qrcode"}}

        self.host = Host(install_prefix=self.prefix, project_dir=ROOT, run=lambda *a, **k: (0, ""), docker=self.d, bash=bash,
                         shell_state=lambda: {"ASTRBOT_REVERSE_WS_TOKEN": "tok", "ASTRBOT_CONTAINER": "astrbot", "NETWORK_NAME": "astrbot_network",
                                              "NAPCAT_BASE_DIR": str(self.prefix / "napcat"), "DATA_DIR": str(self.prefix / "data")},
                         audit=lambda *a, **k: None, napcat_rows=lambda: [{"name": "napcat01", "webui_port": "6099"}], napcat_webui_call=webui)
        self.m = ProtocolManager(self.host)
        sl = self.m.adapters["snowluma"]
        # simulate an installed SnowLuma without pulling anything
        self.m.store.set_consent("tester")
        ports = {"webui": 15099, "novnc": 16081, "vnc": 15900, "http": 13000}
        sl.write_files("napcat01", ports, "motricseven7/snowluma:latest")
        sl.apply_onebot("napcat01", "ws://astrbot:6199/ws", "tok")
        self.m.store.set_snowluma_instance("napcat01", {"container": "snowluma01", "ports": ports, "image": "motricseven7/snowluma:latest"})
        self.d.add("snowluma01", running=False, restart="unless-stopped")
        sl.ready = lambda slot: (True, "ok")
        self.m.adapters["napcat"].ready = lambda slot: (True, "ok")

    def test_autoconfigure_restores_both_sides(self):
        sl = self.m.adapters["snowluma"]
        path = self.prefix / "snowluma" / "snowluma01" / "data" / "config" / "onebot.json"
        cfg = json.loads(path.read_text())
        cfg["networks"]["wsClients"] = []  # e.g. removed in the SnowLuma WebUI
        path.write_text(json.dumps(cfg))
        (self.prefix / "snowluma" / "snowluma01" / "data" / "config" / "onebot_10001.json").write_text(json.dumps(
            {"mode": "snapshot", "networks": {"wsClients": [{"name": "x", "url": "ws://astrbot:6199/ws", "accessToken": "old"}]}}))
        self.assertFalse(sl.onebot_token_ok("napcat01")[0])
        out = self.m.autoconfigure("napcat01", "snowluma", logged_in=True)
        self.assertTrue(out["files_changed"])
        self.assertTrue(out["needs_restart"])
        self.assertTrue(sl.onebot_token_ok("napcat01")[0])
        per = json.loads((self.prefix / "snowluma" / "snowluma01" / "data" / "config" / "onebot_10001.json").read_text())
        urls = [c["url"] for c in per["networks"]["wsClients"]]
        self.assertEqual(urls.count("ws://astrbot:6199/ws"), 1)  # no duplicate client → no double events
        self.assertEqual(per["mode"], "snapshot")

    def test_autoconfigure_napcat_live(self):
        calls = []

        def webui(row, path, payload=None, timeout=10):
            calls.append((path, payload))
            if path == "/OB11Config/GetConfig":
                return {"code": 0, "data": {"network": {"websocketClients": [], "httpServers": []}}}
            return {"code": 0, "data": None}
        self.host.napcat_webui_call = webui
        out = self.m.autoconfigure("napcat01", "napcat", logged_in=True)
        self.assertTrue(out["live"]["changed"])
        sent = json.loads(calls[-1][1]["config"])
        ws = sent["network"]["websocketClients"][0]
        self.assertEqual((ws["url"], ws["token"], ws["enable"]), ("ws://astrbot:6199/ws", "tok", True))

    def test_after_login_autoconfigures_when_not_connected(self):
        from nailong_ng.login_state import LoginTask
        hit = []
        self.m.autoconfigure = lambda slot, proto, log=None, logged_in=True: hit.append((slot, proto)) or {
            "network": True, "platform": "ok", "files_changed": True, "live": None, "needs_restart": False}
        self.m._wait_link = lambda slot, c, seconds, task=None: {"port": 6199, "listening": True, "connected": bool(hit)}
        t = LoginTask("napcat01", "napcat", 1)
        t.account = {"uin": "10001", "nickname": "nl"}
        self.m._after_login(t)
        self.assertEqual(hit, [("napcat01", "napcat")])
        ids = {c["id"]: c["ok"] for c in t.checks}
        self.assertTrue(ids["autoconfig"] and ids["astrbot_link"])
        self.assertEqual(self.m.store.slot("napcat01")["login"]["uin"], "10001")

    def test_container_name(self):
        self.assertEqual(snowluma_container_for("napcat01"), "snowluma01")
        self.assertEqual(snowluma_container_for("napcat120"), "snowluma120")
        with self.assertRaises(ProtocolError):
            snowluma_container_for("../x")

    def test_snowluma_onebot_config(self):
        cfg = json.loads((self.prefix / "snowluma" / "snowluma01" / "data" / "config" / "onebot.json").read_text())
        ws = cfg["networks"]["wsClients"][0]
        self.assertEqual(ws["url"], "ws://astrbot:6199/ws")
        self.assertEqual(ws["accessToken"], "tok")
        self.assertEqual(ws["role"], "Universal")
        self.assertEqual(cfg["networks"]["httpServers"][0]["port"], 3000)
        self.assertTrue(cfg["networks"]["httpServers"][0]["accessToken"])
        ok, _ = self.m.adapters["snowluma"].onebot_token_ok("napcat01")
        self.assertTrue(ok)
        compose = (self.prefix / "snowluma" / "snowluma01" / "docker-compose.yml").read_text()
        self.assertIn('"127.0.0.1:15099:5099"', compose)
        self.assertIn("SYS_PTRACE", compose)
        self.assertNotIn("no-new-privileges:true", compose)
        env = self.prefix / "snowluma" / "snowluma01" / ".env"
        self.assertEqual(env.stat().st_mode & 0o777, 0o600)

    def test_switch_to_snowluma_and_back(self):
        res = self.m.switch("napcat01", "snowluma", log=lambda s: None)
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.m.active("napcat01"), "snowluma")
        self.assertFalse(self.d.c["napcat01"]["running"])
        self.assertEqual(self.d.c["napcat01"]["restart"], "no")  # must not come back after reboot
        self.assertTrue(self.d.c["snowluma01"]["running"])
        self.assertTrue(res["needs_login"])
        # AstrBot was not restarted / reconfigured: its data stays untouched
        self.assertFalse(any("sync_astrbot_platforms" in s for s in self.bash_calls))
        self.assertFalse(any(c[:1] == ["restart"] and c[-1] == "astrbot" for c in self.d.calls))
        res = self.m.switch("napcat01", "napcat", log=lambda s: None)
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.m.active("napcat01"), "napcat")
        self.assertTrue(self.d.c["napcat01"]["running"])
        self.assertEqual(self.d.c["napcat01"]["restart"], "always")
        self.assertFalse(self.d.c["snowluma01"]["running"])
        hist = self.m.store.slot("napcat01")["history"]
        self.assertEqual([h["to"] for h in hist], ["snowluma", "napcat"])

    def test_failed_switch_rolls_back(self):
        self.d.fail_start.add("snowluma01")
        res = self.m.switch("napcat01", "snowluma", log=lambda s: None)
        self.assertFalse(res["ok"])
        self.assertTrue(res["rolled_back"])
        self.assertEqual(self.m.active("napcat01"), "napcat")
        self.assertTrue(self.d.c["napcat01"]["running"])
        self.assertEqual(self.d.c["napcat01"]["restart"], "always")
        self.assertFalse(self.d.c["snowluma01"]["running"])
        self.assertFalse(self.m.store.slot("napcat01").get("switching"))

    def test_protocol_error_after_stop_rolls_back(self):
        def boom(slot):
            raise ProtocolError("目标端异常")
        self.m.adapters["snowluma"].activate = boom
        res = self.m.switch("napcat01", "snowluma", log=lambda s: None)
        self.assertFalse(res["ok"])
        self.assertTrue(res["rolled_back"])
        self.assertTrue(self.d.c["napcat01"]["running"])
        self.assertEqual(self.d.c["napcat01"]["restart"], "always")
        self.assertEqual(self.m.active("napcat01"), "napcat")

    def test_not_ready_rolls_back(self):
        self.m.adapters["snowluma"].ready = lambda slot: (False, "QQ 未启动")
        import nailong_ng.manager as mm
        orig = mm.time.sleep
        mm.time.sleep = lambda s: None
        try:
            res = self.m.switch("napcat01", "snowluma", log=lambda s: None)
        finally:
            mm.time.sleep = orig
        self.assertFalse(res["ok"])
        self.assertEqual(self.m.active("napcat01"), "napcat")
        self.assertTrue(self.d.c["napcat01"]["running"])

    def test_start_inactive_protocol_refused(self):
        with self.assertRaises(ProtocolError):
            self.m.action("napcat01", "snowluma", "start")
        self.assertFalse(self.d.c["snowluma01"]["running"])

    def test_reconcile_stops_inactive(self):
        self.d.c["snowluma01"]["running"] = True  # e.g. somebody started it by hand
        actions = self.m.reconcile()
        self.assertEqual(actions[0]["stopped"], "snowluma")
        self.assertFalse(self.d.c["snowluma01"]["running"])
        self.assertTrue(self.d.c["napcat01"]["running"])

    def test_concurrent_switch_rejected(self):
        lock = self.m._lock("napcat01")
        lock.acquire()
        try:
            with self.assertRaises(ProtocolError):
                self.m.switch("napcat01", "snowluma", log=lambda s: None)
        finally:
            lock.release()

    def test_busy_blocks_switch(self):
        self.host.busy = lambda slot: "正在更新"
        with self.assertRaises(ProtocolError):
            self.m.switch("napcat01", "snowluma", log=lambda s: None)
        self.assertTrue(self.d.c["napcat01"]["running"])

    def test_link_detection_from_proc_net_tcp(self):
        # AstrBot listening on 6199 (0x1837) with an ESTABLISHED peer 172.20.0.9 (snowluma01)
        self.d.c["snowluma01"]["ip"] = "172.20.0.9"
        self.d.tcp["astrbot"] = (
            "  sl  local_address rem_address   st\n"
            "   0: 00000000:1837 00000000:0000 0A 0\n"
            "   1: 020014AC:1837 090014AC:C350 01 0\n")
        link = self.m.astrbot.link("napcat01", "snowluma01")
        self.assertTrue(link["listening"])
        self.assertTrue(link["connected"])
        self.assertEqual(link["peers"], ["172.20.0.9"])

    def test_diagnose_report(self):
        rep = self.m.diagnose("napcat01")
        ids = [c["id"] for c in rep["checks"]]
        for need in ("protocol_running", "qq_online", "onebot_port", "ws_connected", "token", "astrbot_platform", "network"):
            self.assertIn(need, ids)
        self.assertIn("奶龙一键诊断", self.m.diagnose_text(rep))

    def test_napcat_apply_onebot(self):
        na = self.m.adapters["napcat"]
        changed = na.apply_onebot("napcat01", "ws://astrbot:6199/ws", "tok2")
        self.assertTrue(changed)
        data = json.loads((self.prefix / "napcat" / "napcat01" / "config" / "onebot11.json").read_text())
        self.assertEqual(data["network"]["websocketClients"][0]["token"], "tok2")


class MiscTest(unittest.TestCase):
    def test_proc_net_tcp_ipv6_mapped(self):
        rows = parse_proc_net_tcp("  0: 0000000000000000FFFF0000020014AC:1837 0000000000000000FFFF0000090014AC:C350 01 0\n")
        self.assertEqual(rows[0]["local_ip"], "172.20.0.2")
        self.assertEqual(rows[0]["remote_ip"], "172.20.0.9")

    def test_secretbox_and_ssh_store(self):
        tmp = Path(tempfile.mkdtemp())
        box = SecretBox(tmp / ".k")
        ct = box.encrypt("pässword")
        self.assertNotIn("pässword", ct)
        self.assertEqual(box.decrypt(ct), "pässword")
        self.assertEqual((tmp / ".k").stat().st_mode & 0o777, 0o600)
        store = SSHServers(tmp)
        row = store.save({"host": "192.0.2.10", "port": 22, "username": "root", "password": "hunter2"})
        self.assertNotIn("password_enc", row)
        self.assertNotIn("hunter2", (tmp / "ssh_servers.json").read_text())
        with self.assertRaises(SSHError):
            store.save({"host": "bad host;rm", "password": "x"})
        with self.assertRaises(SSHError):
            store.save({"host": "192.0.2.11", "username": "root"})

    def test_ssh_env_evaluate(self):
        checks = evaluate({"ARCH": "x86_64", "OS": "Debian GNU/Linux 12", "MEM_MB": "4000", "DISK_FREE_MB": "20000", "CURL": "yes", "GITHUB": "200"})
        self.assertTrue(all(c["ok"] or c["level"] == "warn" for c in checks))
        bad = evaluate({"ARCH": "mips", "CURL": "no"})
        self.assertTrue(any(c["id"] == "arch" and not c["ok"] for c in bad))


if __name__ == "__main__":
    unittest.main()
