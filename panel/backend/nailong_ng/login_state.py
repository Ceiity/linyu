"""Unified QR-login task / state machine for every protocol end.

States::

    IDLE → REQUESTING → QR_READY → SCANNED → WAITING_CONFIRMATION → SUCCESS
                                  ↘ EXPIRED / REJECTED / FAILED / CANCELLED

Guarantees
* at most one running task per bot slot (a new request returns the running
  task; "重新申请" cancels it first and bumps the generation);
* the QR payload carries a monotonically increasing ``seq`` and the task id,
  so the browser can drop stale responses and never paints an old code over a
  new one;
* bounded: overall deadline, scan→confirm deadline, a cap on automatic QR
  refreshes and on consecutive protocol errors – it never retries forever;
* all transitions are written to ``logs/login.log`` (redacted).
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from typing import Callable

from .login_codes import make_error, parse_napcat_log, parse_napcat_login_error, parse_snowluma_log

STATES = ("IDLE", "REQUESTING", "QR_READY", "SCANNED", "WAITING_CONFIRMATION", "SUCCESS", "EXPIRED", "REJECTED", "FAILED", "CANCELLED")
TERMINAL = {"SUCCESS", "EXPIRED", "REJECTED", "FAILED", "CANCELLED"}
ORDER = {s: i for i, s in enumerate(STATES)}
STATE_TEXT = {
    "IDLE": "空闲", "REQUESTING": "正在申请登录", "QR_READY": "等待手机扫码", "SCANNED": "已扫码",
    "WAITING_CONFIRMATION": "等待手机确认", "SUCCESS": "登录成功", "EXPIRED": "二维码已过期",
    "REJECTED": "登录被拒绝", "FAILED": "登录失败", "CANCELLED": "已取消",
}
TIMELINE = [
    ("REQUESTING", "正在申请登录"),
    ("QR_FETCH", "正在获取二维码"),
    ("QR_READY", "等待手机扫码"),
    ("SCANNED", "已扫码"),
    ("WAITING_CONFIRMATION", "等待确认"),
    ("SUCCESS", "登录成功"),
]

DEFAULT_TIMEOUT = 600          # whole task
CONFIRM_TIMEOUT = 180          # scanned → confirmed
MAX_CONSECUTIVE_ERRORS = 5


class LoginAbort(Exception):
    def __init__(self, error: dict):
        super().__init__(error.get("title", "登录失败"))
        self.error = error


class LoginTask:
    def __init__(self, slot: str, protocol: str, generation: int, timeout: int = DEFAULT_TIMEOUT, user: str = ""):
        self.id = secrets.token_hex(6)
        self.slot = slot
        self.protocol = protocol
        self.generation = generation
        self.user = user
        self.lock = threading.RLock()
        self.state = "REQUESTING"
        self.steps: dict[str, float] = {}
        self.events: list[dict] = []
        self.qr: dict | None = None
        self.qr_key = ""
        self.qr_seq = 0
        self.qr_issued_at = 0.0
        self.qr_refreshes = 0
        self.error: dict | None = None
        self.warnings: list[dict] = []
        self.account: dict = {}
        self.checks: list[dict] = []
        self.already = False
        self.started = time.time()
        self.deadline = self.started + timeout
        self.scanned_at = 0.0
        self.finished_at = 0.0
        self.cancel_event = threading.Event()
        self.wake = threading.Event()
        self.refresh_requested = False
        self.pending_clicks: list[tuple[float, float]] = []
        self.baseline: dict = {}
        self.notes: dict = {}
        self._log: Callable[[dict], None] | None = None
        self.step("REQUESTING")

    # ------------------------------------------------------------------
    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL

    def event(self, text: str, level: str = "info", **extra) -> None:
        with self.lock:
            ev = {"ts": time.time(), "time": time.strftime("%H:%M:%S"), "state": self.state, "text": text, "level": level}
            ev.update(extra)
            self.events.append(ev)
            self.events = self.events[-80:]
        if self._log:
            self._log({"task": self.id, "slot": self.slot, "protocol": self.protocol, **ev})

    def step(self, step: str) -> None:
        with self.lock:
            self.steps.setdefault(step, time.time())

    def set_state(self, state: str, text: str = "") -> bool:
        with self.lock:
            if self.terminal or state == self.state:
                return False
            if state not in STATES:
                return False
            # Never step backwards in the happy path, except a fresh QR after a scan
            # that went nowhere (NapCat re-issues a code after a rejection).
            if state not in TERMINAL and ORDER[state] < ORDER[self.state] and state != "QR_READY":
                return False
            self.state = state
            if state in ("QR_READY", "SCANNED", "WAITING_CONFIRMATION", "SUCCESS"):
                self.step(state)
            if state == "SCANNED" and not self.scanned_at:
                self.scanned_at = time.time()
            if state == "WAITING_CONFIRMATION" and not self.scanned_at:
                self.scanned_at = time.time()
            if state in TERMINAL:
                self.finished_at = time.time()
                self.cancel_event.set()
                self.wake.set()
        self.event(text or STATE_TEXT.get(state, state))
        return True

    def set_qr(self, qr: dict, reason: str = "") -> bool:
        key = str(qr.get("key") or qr.get("url") or qr.get("sha") or "")
        with self.lock:
            if self.terminal or not key:
                return False
            if key == self.qr_key:
                # same code – only refresh geometry/image metadata
                if self.qr:
                    self.qr.update({k: v for k, v in qr.items() if k in ("geometry",)})
                return False
            first = not self.qr_key
            self.qr_key = key
            self.qr_seq += 1
            self.qr_issued_at = time.time()
            self.qr = {**qr, "seq": self.qr_seq, "task_id": self.id, "issued_at": self.qr_issued_at}
            if not first:
                self.qr_refreshes += 1
            self.step("QR_FETCH")
        if first:
            self.event(reason or "二维码已就绪")
        else:
            self.event(reason or "协议端返回了新的二维码")
        if self.state in ("REQUESTING", "SCANNED", "WAITING_CONFIRMATION") and qr.get("kind") == "url":
            # A new code after a scan means the previous attempt ended.
            self.state = "QR_READY" if self.state != "REQUESTING" else self.state
        if self.state == "REQUESTING":
            self.set_state("QR_READY")
        return True

    def fail(self, error: dict) -> None:
        with self.lock:
            if self.terminal:
                return
            self.error = error
        state = error.get("state") or "FAILED"
        if state == "SUCCESS":
            state = "FAILED"
        self.set_state(state if state in TERMINAL else "FAILED", "%s：%s" % (error.get("title"), error.get("raw_message") or error.get("description")))

    def warn(self, error: dict) -> None:
        with self.lock:
            key = (error.get("code"), error.get("raw_code"), error.get("raw_message"))
            if any((w.get("code"), w.get("raw_code"), w.get("raw_message")) == key for w in self.warnings):
                return
            self.warnings.append(error)
            self.warnings = self.warnings[-10:]
        self.event("%s：%s" % (error.get("title"), (error.get("raw_message") or "")[:160]), "warn")

    def to_dict(self, include_qr: bool = True, since_seq: int = 0) -> dict:
        with self.lock:
            qr = None
            if include_qr and self.qr:
                if since_seq and since_seq >= self.qr_seq:
                    qr = {"seq": self.qr_seq, "task_id": self.id, "unchanged": True, "issued_at": self.qr_issued_at,
                          "kind": self.qr.get("kind"), "expires_hint": self.qr.get("expires_hint"), "geometry": self.qr.get("geometry")}
                else:
                    qr = dict(self.qr)
            now = time.time()
            timeline = []
            reached = set(self.steps)
            for step, label in TIMELINE:
                st = "done" if step in reached else "todo"
                if step == "SCANNED" and step not in reached and "WAITING_CONFIRMATION" in reached:
                    st = "skipped"
                timeline.append({"step": step, "label": label, "status": st, "at": self.steps.get(step)})
            # mark the current step
            if not self.terminal:
                cur = {"REQUESTING": "QR_FETCH" if "REQUESTING" in reached else "REQUESTING", "QR_READY": "SCANNED",
                       "SCANNED": "WAITING_CONFIRMATION", "WAITING_CONFIRMATION": "SUCCESS"}.get(self.state)
                for row in timeline:
                    if row["step"] == cur and row["status"] == "todo":
                        row["status"] = "current"
            elif self.state != "SUCCESS":
                for row in timeline:
                    if row["status"] == "todo":
                        row["status"] = "failed"
                        break
            return {
                "task_id": self.id, "slot": self.slot, "protocol": self.protocol, "generation": self.generation,
                "state": self.state, "state_text": STATE_TEXT.get(self.state, self.state), "terminal": self.terminal,
                "already": self.already, "started_at": self.started, "elapsed": int((self.finished_at or now) - self.started),
                "deadline_in": max(0, int(self.deadline - now)) if not self.terminal else 0,
                "qr": qr, "qr_seq": self.qr_seq, "qr_age": int(now - self.qr_issued_at) if self.qr_issued_at else None,
                "qr_refreshes": self.qr_refreshes,
                "error": self.error, "warnings": list(self.warnings), "account": dict(self.account),
                "checks": list(self.checks), "timeline": timeline, "events": list(self.events[-40:]),
                "notes": dict(self.notes),
            }


class LoginDriver:
    protocol = ""
    poll_interval = 2.0
    max_qr_refreshes = 8

    def precheck(self, task: LoginTask) -> None:
        raise NotImplementedError

    def start(self, task: LoginTask) -> None:
        raise NotImplementedError

    def poll(self, task: LoginTask) -> dict:
        raise NotImplementedError

    def refresh(self, task: LoginTask) -> None:
        raise NotImplementedError

    def click(self, task: LoginTask, x: float, y: float) -> None:
        from .protocols import Unsupported
        raise Unsupported("该协议端不支持点击操作")


class LoginManager:
    def __init__(self, driver_for: Callable[[str], LoginDriver], log_path: Path,
                 on_success: Callable[[LoginTask], None] | None = None, redact: Callable[[str], str] = lambda s: s,
                 timeout: int = DEFAULT_TIMEOUT, confirm_timeout: int = CONFIRM_TIMEOUT):
        self.driver_for = driver_for
        self.log_path = log_path
        self.on_success = on_success
        self.redact = redact
        self.timeout = timeout
        self.confirm_timeout = confirm_timeout
        self.lock = threading.RLock()
        self.tasks: dict[str, LoginTask] = {}
        self.generation: dict[str, int] = {}

    # -- logging --------------------------------------------------------
    def _write_log(self, row: dict) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            line = self.redact(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), **{k: v for k, v in row.items() if k != "ts"}}, ensure_ascii=False))
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # -- API ------------------------------------------------------------
    def current(self, slot: str) -> LoginTask | None:
        with self.lock:
            return self.tasks.get(slot)

    def request(self, slot: str, restart: bool = False, user: str = "") -> LoginTask:
        with self.lock:
            cur = self.tasks.get(slot)
            if cur and not cur.terminal:
                if not restart:
                    return cur
                self._cancel(cur, "重新申请，旧任务已取消")
            driver = self.driver_for(slot)
            gen = self.generation.get(slot, 0) + 1
            self.generation[slot] = gen
            task = LoginTask(slot, driver.protocol, gen, self.timeout, user)
            task._log = self._write_log
            self.tasks[slot] = task
        task.event("登录任务已创建（第 %d 次申请）" % gen)
        threading.Thread(target=self._run, args=(task, driver), daemon=True, name="login-%s" % slot).start()
        return task

    def _cancel(self, task: LoginTask, reason: str) -> None:
        if task.terminal:
            return
        task.error = make_error("UNKNOWN", task.protocol, task.state, "", reason) if False else None
        task.set_state("CANCELLED", reason)

    def cancel(self, slot: str, task_id: str = "", reason: str = "用户取消了登录申请") -> LoginTask | None:
        with self.lock:
            task = self.tasks.get(slot)
            if not task or (task_id and task.id != task_id):
                return task
            self._cancel(task, reason)
            return task

    def cancel_slot(self, slot: str, reason: str) -> None:
        self.cancel(slot, "", reason)

    def refresh(self, slot: str, task_id: str) -> LoginTask:
        task = self._live(slot, task_id)
        with task.lock:
            task.refresh_requested = True
        task.wake.set()
        return task

    def click(self, slot: str, task_id: str, x: float, y: float) -> LoginTask:
        task = self._live(slot, task_id)
        with task.lock:
            task.pending_clicks.append((float(x), float(y)))
            task.pending_clicks = task.pending_clicks[-3:]
        task.wake.set()
        return task

    def _live(self, slot: str, task_id: str) -> LoginTask:
        task = self.current(slot)
        if not task or task.id != task_id:
            raise ValueError("登录任务已更新，请使用最新的任务")
        if task.terminal:
            raise ValueError("登录任务已结束，请重新申请")
        return task

    def snapshot(self, slot: str, since_seq: int = 0) -> dict:
        task = self.current(slot)
        if not task:
            return {"state": "IDLE", "state_text": STATE_TEXT["IDLE"], "slot": slot, "terminal": True, "task_id": "", "timeline": [
                {"step": s, "label": label, "status": "todo", "at": None} for s, label in TIMELINE]}
        return task.to_dict(True, since_seq)

    # -- worker ---------------------------------------------------------
    def _run(self, task: LoginTask, driver: LoginDriver) -> None:
        try:
            driver.precheck(task)
            if task.terminal:
                return self._finish(task)
            driver.start(task)
            errors = 0
            while not task.terminal:
                now = time.time()
                if now >= task.deadline:
                    if task.state in ("SCANNED", "WAITING_CONFIRMATION"):
                        task.fail(make_error("CONFIRM_TIMEOUT", task.protocol, task.state, "", "登录任务超过 %d 秒未完成" % self.timeout))
                    else:
                        task.fail(make_error("QR_EXPIRED", task.protocol, task.state, "", "登录任务超过 %d 秒未完成扫码" % self.timeout))
                    break
                if task.scanned_at and task.state in ("SCANNED", "WAITING_CONFIRMATION") and now - task.scanned_at > self.confirm_timeout:
                    task.fail(make_error("CONFIRM_TIMEOUT", task.protocol, task.state, "", "扫码后 %d 秒内没有完成确认" % self.confirm_timeout))
                    break
                with task.lock:
                    want_refresh = task.refresh_requested
                    task.refresh_requested = False
                    clicks = list(task.pending_clicks)
                    task.pending_clicks.clear()
                try:
                    for x, y in clicks:
                        driver.click(task, x, y)
                    if want_refresh:
                        task.event("正在刷新二维码")
                        driver.refresh(task)
                    obs = driver.poll(task)
                    errors = 0
                except LoginAbort as e:
                    task.fail(e.error)
                    break
                except Exception as e:  # transient protocol problems
                    if getattr(e, "code", "") == "UNSUPPORTED":
                        task.warn(make_error("UNKNOWN", task.protocol, task.state, "UNSUPPORTED", str(e), "rule") | {"title": "不支持的操作"})
                        obs = {}
                    else:
                        errors += 1
                        task.event("协议端暂时无响应（%d/%d）：%s" % (errors, MAX_CONSECUTIVE_ERRORS, str(e)[:160]), "warn")
                        if errors >= MAX_CONSECUTIVE_ERRORS:
                            task.fail(make_error("PROTOCOL_UNREACHABLE", task.protocol, task.state, "", str(e)))
                            break
                        obs = {}
                self._apply(task, driver, obs)
                if task.terminal:
                    break
                task.wake.wait(driver.poll_interval)
                task.wake.clear()
        except LoginAbort as e:
            task.fail(e.error)
        except Exception as e:
            task.fail(make_error("UNKNOWN", task.protocol, task.state, "", "%s: %s" % (type(e).__name__, e)))
        self._finish(task)

    def _apply(self, task: LoginTask, driver: LoginDriver, obs: dict) -> None:
        if not obs:
            return
        if obs.get("account"):
            task.account.update({k: v for k, v in obs["account"].items() if v})
        if obs.get("qr"):
            task.set_qr(obs["qr"], obs.get("qr_reason", ""))
            if task.qr_refreshes > driver.max_qr_refreshes and not task.terminal:
                task.fail(make_error("QR_EXPIRED", task.protocol, task.state, "", "二维码已自动刷新 %d 次仍未完成扫码，已停止自动刷新" % task.qr_refreshes))
                return
        for w in obs.get("warnings") or []:
            task.warn(w)
        if obs.get("error"):
            task.fail(obs["error"])
            return
        if obs.get("expired"):
            if task.qr_refreshes >= driver.max_qr_refreshes:
                task.fail(make_error("QR_EXPIRED", task.protocol, task.state, obs.get("raw_code", ""), obs.get("raw_message", "二维码已过期")))
                return
            task.event("二维码已过期，正在自动获取新二维码", "warn")
            try:
                driver.refresh(task)
            except LoginAbort as e:
                task.fail(e.error)
                return
            except Exception as e:
                task.warn(make_error("QR_FETCH_FAILED", task.protocol, task.state, "", str(e)))
        state = obs.get("state")
        if state:
            task.set_state(state, obs.get("state_text", ""))

    def _finish(self, task: LoginTask) -> None:
        if task.state == "SUCCESS" and self.on_success:
            try:
                self.on_success(task)
            except Exception as e:
                task.checks.append({"id": "post_login", "title": "登录后检查", "ok": False, "detail": str(e)})
        task.event("任务结束：%s" % STATE_TEXT.get(task.state, task.state), "info" if task.state == "SUCCESS" else "warn")


# ---------------------------------------------------------------------------
# Protocol drivers
# ---------------------------------------------------------------------------

class NapCatLoginDriver(LoginDriver):
    protocol = "napcat"
    poll_interval = 1.5
    max_qr_refreshes = 8

    PHASES = {
        "waiting_qrcode": ("QR_READY", "等待手机扫码"),
        "qrcode_scanned": ("WAITING_CONFIRMATION", "已扫码，等待手机确认"),
        "initializing": ("WAITING_CONFIRMATION", "手机已确认，正在初始化 QQ"),
    }

    def __init__(self, adapter):
        self.adapter = adapter
        self.polls = 0

    def _status(self, slot: str, timeout: int = 6) -> dict:
        res = self.adapter.webui(slot, "/QQLogin/CheckLoginStatus", timeout=timeout)
        if int(res.get("code", -1)) != 0:
            raise RuntimeError(str(res.get("message") or "CheckLoginStatus 失败"))
        return res.get("data") or {}

    def _account(self, slot: str) -> dict:
        try:
            info = self.adapter.webui(slot, "/QQLogin/GetQQLoginInfo", timeout=5)
            d = info.get("data") or {} if int(info.get("code", -1)) == 0 else {}
            return {"uin": str(d.get("uin") or ""), "nickname": str(d.get("nick") or d.get("nickname") or "")}
        except Exception:
            return {}

    @staticmethod
    def _qr(url: str) -> dict:
        return {"kind": "url", "key": url, "url": url, "expires_hint": None,
                "note": "NapCat 不返回二维码有效期；过期由 NapCat 回调（ErrType=1 ErrCode=3）判定并自动换新码"}

    def precheck(self, task: LoginTask) -> None:
        slot = task.slot
        if not self.adapter.installed(slot):
            raise LoginAbort(make_error("PROTOCOL_UNREACHABLE", "napcat", "precheck", "", "NapCat 实例不存在"))
        if not self.adapter.docker.state(slot).get("running"):
            raise LoginAbort(make_error("PROTOCOL_UNREACHABLE", "napcat", "precheck", "", "NapCat 容器未运行，请先在协议端页面启动"))
        try:
            data = self._status(slot)
        except Exception as e:
            raise LoginAbort(make_error("PROTOCOL_UNREACHABLE", "napcat", "precheck", "", str(e)))
        task.baseline = {"loginError": str(data.get("loginError") or ""), "qrcodeurl": str(data.get("qrcodeurl") or "")}
        task.event("NapCat 运行中，登录阶段：%s" % (data.get("loginPhase") or "未知"))
        if data.get("isLogin"):
            task.already = True
            task.account = self._account(slot)
            task.set_state("SUCCESS", "QQ 已在线，无需重复登录")

    def start(self, task: LoginTask) -> None:
        slot = task.slot
        task.step("QR_FETCH")
        task.event("正在获取二维码")
        last = ""
        for attempt in range(3):
            if task.terminal:
                return
            url = ""
            try:
                data = self._status(slot)
                if data.get("isLogin"):
                    task.account = self._account(slot)
                    task.set_state("SUCCESS", "QQ 已登录")
                    return
                if data.get("loginPhase") != "reconnecting":
                    # Always ask for a fresh code: a cached URL may already be expired.
                    res = self.adapter.webui(slot, "/QQLogin/RefreshQRcode", timeout=15)
                    d = res.get("data") or {}
                    if int(res.get("code", -1)) == 0:
                        url = str(d.get("qrcodeurl") or "")
                        if d.get("restarting"):
                            last = "NapCat 正在重启登录服务"
                    else:
                        last = str(res.get("message") or "")
                        if "Logined" in last:
                            task.account = self._account(slot)
                            task.set_state("SUCCESS", "QQ 已登录")
                            return
                    if not url:
                        res = self.adapter.webui(slot, "/QQLogin/GetQQLoginQrcode", timeout=8)
                        if int(res.get("code", -1)) == 0:
                            url = str((res.get("data") or {}).get("qrcode") or "")
                        else:
                            last = str(res.get("message") or last)
                else:
                    last = "NapCat 登录服务正在重连（被踢下线后自动恢复中）"
            except Exception as e:
                last = str(e)
            if url:
                task.set_qr(self._qr(url), "二维码已就绪，请用手机 QQ 扫码")
                return
            task.event("第 %d 次获取二维码失败：%s" % (attempt + 1, last[:160]), "warn")
            if task.cancel_event.wait(3):
                return
        raise LoginAbort(make_error("QR_FETCH_FAILED", "napcat", "QR_FETCH", "", last or "NapCat 没有返回二维码"))

    def refresh(self, task: LoginTask) -> None:
        res = self.adapter.webui(task.slot, "/QQLogin/RefreshQRcode", timeout=15)
        if int(res.get("code", -1)) != 0:
            msg = str(res.get("message") or "")
            if "Logined" in msg:
                return
            err = parse_napcat_login_error(msg, "refresh")
            raise LoginAbort(make_error("QR_FETCH_FAILED", "napcat", "refresh", "", msg) if not err or err["code"] == "UNKNOWN" else err)
        url = str((res.get("data") or {}).get("qrcodeurl") or "")
        if url:
            task.set_qr(self._qr(url), "已获取新的二维码")

    def poll(self, task: LoginTask) -> dict:
        self.polls += 1
        slot = task.slot
        data = self._status(slot)
        obs: dict = {}
        if data.get("isLogin"):
            obs["state"] = "SUCCESS"
            obs["state_text"] = "登录成功"
            obs["account"] = self._account(slot)
            return obs
        phase = str(data.get("loginPhase") or "")
        task.notes["phase"] = phase
        if phase in self.PHASES:
            st, text = self.PHASES[phase]
            if phase == "qrcode_scanned" and task.state == "QR_READY":
                task.set_state("SCANNED", "二维码已被扫描")
            obs["state"] = st
            obs["state_text"] = text
        elif phase == "reconnecting":
            task.notes["reconnecting"] = True
        url = str(data.get("qrcodeurl") or "")
        if url and url != task.qr_key and phase in ("waiting_qrcode", "generating_qrcode", ""):
            obs["qr"] = self._qr(url)
            obs["qr_reason"] = "协议端返回了新的二维码（旧码已失效）"
            obs["state"] = "QR_READY"
        raw_err = str(data.get("loginError") or "")
        if raw_err and raw_err != task.baseline.get("loginError"):
            err = parse_napcat_login_error(raw_err, task.state)
            task.baseline["loginError"] = raw_err
            if err:
                if err["code"] == "QR_EXPIRED":
                    obs["expired"] = not obs.get("qr")
                    obs["raw_message"] = raw_err
                elif err["code"] in ("ALREADY_LOGGED_IN", "KICKED_OFFLINE"):
                    obs.setdefault("warnings", []).append(err)
                else:
                    obs["error"] = err
        if self.polls % 3 == 0 and not obs.get("error"):
            code, out = self.adapter.host.docker(["logs", "--since", str(int(task.started) - 2), slot], timeout=15)
            seen = task.notes.setdefault("log_errors", [])
            for err in parse_napcat_log(out, task.state):
                key = err.get("raw_message")
                if key in seen:
                    continue
                seen.append(key)
                if err["code"] == "QR_EXPIRED":
                    task.event("NapCat 报告二维码过期（ErrType=1 ErrCode=3），等待新二维码", "warn")
                    continue
                obs["error"] = err
                break
        return obs


class SnowLumaLoginDriver(LoginDriver):
    protocol = "snowluma"
    poll_interval = 2.5
    max_qr_refreshes = 10 ** 6  # screen frames, not codes – bounded by the task deadline instead

    def __init__(self, adapter):
        self.adapter = adapter
        self.polls = 0
        self.qq_bad = 0

    def precheck(self, task: LoginTask) -> None:
        slot = task.slot
        a = self.adapter
        if not a.installed(slot):
            raise LoginAbort(make_error("PROTOCOL_UNREACHABLE", "snowluma", "precheck", "", "该机器人尚未安装 SnowLuma"))
        if a.store.active(slot) != "snowluma":
            raise LoginAbort(make_error("PROTOCOL_UNREACHABLE", "snowluma", "precheck", "", "该机器人当前使用 NapCat，请先切换到 SnowLuma"))
        if not a.docker.state(a.container(slot)).get("running"):
            task.event("SnowLuma 未运行，正在启动")
            res = a.activate(slot)
            if not res.get("ok") or not a.docker.wait_running(a.container(slot), True, 60):
                raise LoginAbort(make_error("PROTOCOL_UNREACHABLE", "snowluma", "precheck", "", "SnowLuma 容器启动失败：%s" % res.get("output", "")[-300:]))
            time.sleep(4)
        st = a.get_login_status(slot)
        if st.get("online"):
            task.already = True
            task.account = {"uin": st.get("uin", ""), "nickname": st.get("nickname", "")}
            task.set_state("SUCCESS", "QQ 已在线，无需重复登录")
            return
        for _ in range(6):
            ok, why = a.ready(slot)
            if ok:
                break
            if task.cancel_event.wait(3):
                return
        else:
            sv = a.supervisor(slot)
            raise LoginAbort(make_error("CLIENT_ERROR", "snowluma", "precheck", "supervisor", "%s | %s" % (why, sv.get("raw", "")[-300:])))
        task.event("SnowLuma 与 QQ 客户端运行中")
        task.notes["login_mode"] = "screen"

    def _frame(self, task: LoginTask) -> dict | None:
        shot = self.adapter.capture_screen(task.slot)
        return {
            "kind": "image", "key": shot["sha"], "sha": shot["sha"], "png_base64": shot["png_base64"],
            "geometry": {"box": shot["box"], "scale": shot["scale"], "image": shot["image"], "screen": shot["screen"]},
            "blank": shot.get("blank", False), "expires_hint": None,
            "note": "SnowLuma 没有二维码接口：这是容器内 QQ 登录窗口的实时画面，二维码有效期与刷新由 QQ 客户端管理。",
        }

    def start(self, task: LoginTask) -> None:
        task.step("QR_FETCH")
        task.event("正在读取 QQ 登录窗口")
        last = ""
        for _ in range(4):
            try:
                frame = self._frame(task)
                if frame:
                    task.set_qr(frame, "QQ 登录窗口已显示，请用手机 QQ 扫描画面中的二维码")
                    if frame.get("blank"):
                        task.event("画面里还没有 QQ 窗口，QQ 客户端可能仍在启动", "warn")
                    return
            except Exception as e:
                last = str(e)
            if task.cancel_event.wait(3):
                return
        raise LoginAbort(make_error("QR_FETCH_FAILED", "snowluma", "QR_FETCH", "vnc", last))

    def refresh(self, task: LoginTask) -> None:
        # Not a fake success: SnowLuma has no QR API.  Grab a fresh frame instead.
        frame = self._frame(task)
        if frame:
            task.set_qr(frame, "画面已刷新")
        task.event("SnowLuma 没有刷新二维码接口；如果画面中二维码已失效，请直接点击画面里的二维码让 QQ 刷新", "warn")

    def click(self, task: LoginTask, x: float, y: float) -> None:
        from .rfb import map_click
        geo = (task.qr or {}).get("geometry") or {}
        sx, sy = map_click(x, y, geo)
        self.adapter.click_screen(task.slot, sx, sy)
        task.event("已在 QQ 窗口点击 (%d, %d)" % (sx, sy))
        time.sleep(0.6)

    def poll(self, task: LoginTask) -> dict:
        self.polls += 1
        slot = task.slot
        obs: dict = {}
        st = self.adapter.get_login_status(slot, quick=True)
        if st.get("online"):
            return {"state": "SUCCESS", "state_text": "登录成功", "account": {"uin": st.get("uin", ""), "nickname": st.get("nickname", "")}}
        logs = self.adapter.docker.logs(self.adapter.container(slot), 400, str(int(task.started) - 2))
        seen = task.notes.setdefault("log_seen", 0)
        events = parse_snowluma_log(logs, task.state)
        for ev in events[seen:]:
            if ev["kind"] == "awaiting":
                task.event("SnowLuma 已注入 QQ，等待扫码")
            elif ev["kind"] == "identity":
                obs["state"] = "WAITING_CONFIRMATION"
                obs["state_text"] = "已识别账号 %s，等待 QQ 就绪" % ev.get("uin", "")
                obs["account"] = {"uin": ev.get("uin", "")}
            elif ev["kind"] == "session_started":
                obs["state"] = "WAITING_CONFIRMATION"
                obs["state_text"] = "OneBot 会话已启动，正在确认"
                obs["account"] = {"uin": ev.get("uin", "")}
            elif ev.get("error"):
                obs.setdefault("warnings", []).append(ev["error"])
        task.notes["log_seen"] = len(events)
        if self.polls % 4 == 0:
            sv = self.adapter.supervisor(slot)
            qq = (sv.get("programs") or {}).get("qq")
            if qq and qq not in ("RUNNING", "STARTING"):
                self.qq_bad += 1
                if self.qq_bad >= 3:
                    obs["error"] = make_error("CLIENT_ERROR", "snowluma", task.state, "qq=%s" % qq, sv.get("raw", "")[-400:])
                    return obs
            else:
                self.qq_bad = 0
        if task.state not in ("WAITING_CONFIRMATION",):
            try:
                frame = self._frame(task)
                if frame and frame["key"] != task.qr_key:
                    obs["qr"] = frame
                    obs["qr_reason"] = "QQ 窗口画面已更新"
            except Exception as e:
                obs.setdefault("warnings", []).append(make_error("PROTOCOL_UNREACHABLE", "snowluma", task.state, "vnc", str(e)))
        return obs
