"""Protocol manager: overview, switching with rollback, exclusivity, diagnostics."""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .host import Host
from .login_state import LoginManager, LoginTask, NapCatLoginDriver, SnowLumaLoginDriver
from .protocols import (LABELS, NAPCAT, PROTOCOLS, SNOWLUMA, SNOWLUMA_LICENSE, AstrBotLink, DockerOps,
                        NapCatAdapter, ProtocolError, ProtocolStore, SnowLumaAdapter, backup_dirs,
                        display_name, now_text, restore_backup, valid_slot)


class ProtocolManager:
    def __init__(self, host: Host):
        self.host = host
        self.store = ProtocolStore(host)
        self.docker = DockerOps(host)
        self.astrbot = AstrBotLink(host, self.docker)
        self.adapters = {
            NAPCAT: NapCatAdapter(host, self.store, self.docker, self.astrbot),
            SNOWLUMA: SnowLumaAdapter(host, self.store, self.docker, self.astrbot),
        }
        self.switch_locks: dict[str, threading.Lock] = {}
        self.switch_guard = threading.Lock()
        self.logins = LoginManager(self._driver_for, host.install_prefix / "logs" / "login.log",
                                   on_success=self._after_login, redact=host.redact)
        self._reconcile_stop = threading.Event()

    # ------------------------------------------------------------------
    def adapter(self, proto: str):
        if proto not in self.adapters:
            raise ProtocolError("协议端不支持：%s" % proto)
        return self.adapters[proto]

    def slots(self) -> list[str]:
        return [str(r.get("name")) for r in (self.host.napcat_rows() or []) if r.get("name")]

    def _require_slot(self, slot: str) -> str:
        valid_slot(slot)
        if slot not in self.slots():
            raise ProtocolError("机器人不存在：%s" % slot)
        return slot

    def active(self, slot: str) -> str:
        return self.store.active(slot)

    def _driver_for(self, slot: str):
        proto = self.active(slot)
        if proto == SNOWLUMA:
            return SnowLumaLoginDriver(self.adapters[SNOWLUMA])
        return NapCatLoginDriver(self.adapters[NAPCAT])

    def _log_switch(self, row: dict) -> None:
        path = self.host.install_prefix / "logs" / "protocol-switch.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(self.host.redact(json.dumps({"time": now_text(), **row}, ensure_ascii=False)) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------------
    # overview
    # ------------------------------------------------------------------
    def _proto_card(self, slot: str, proto: str, quick: bool = True) -> dict:
        a = self.adapters[proto]
        st = a.get_status(slot)
        card = {"protocol": proto, "label": LABELS[proto], "installed": st.get("installed"), "exists": st.get("exists", False),
                "running": bool(st.get("running")), "status": st.get("status"), "container": a.container(slot),
                "restart_policy": st.get("restart_policy", ""), "image": st.get("image", ""), "version": "",
                "login": {"online": False, "phase": "stopped"}, "capabilities": a.capabilities}
        if st.get("installed"):
            try:
                card["version"] = a.get_version(slot)
            except Exception:
                card["version"] = ""
        if card["running"]:
            try:
                card["login"] = a.get_login_status(slot, quick=quick)
            except Exception as e:
                card["login"] = {"online": False, "phase": "unknown", "detail": str(e)[:200]}
        if proto == SNOWLUMA:
            inst = a.instance(slot) or {}
            card["ports"] = inst.get("ports") or {}
            card["digest"] = inst.get("digest", "")
            card["installed_at"] = inst.get("installed_at", "")
        return card

    def slot_overview(self, slot: str) -> dict:
        active = self.active(slot)
        meta = self.store.slot(slot)
        cards = {p: self._proto_card(slot, p) for p in PROTOCOLS}
        login = cards[active]["login"]
        task = self.logins.current(slot)
        return {
            "slot": slot, "display_name": display_name(slot), "active": active, "active_label": LABELS[active],
            "switching": bool(meta.get("switching")), "last_switch": (meta.get("history") or [])[-1:] or [],
            "last_login": meta.get("login") or {}, "napcat": cards[NAPCAT], "snowluma": cards[SNOWLUMA],
            "online": bool(login.get("online")), "uin": login.get("uin", "") or (meta.get("login") or {}).get("uin", ""),
            "nickname": login.get("nickname", "") or (meta.get("login") or {}).get("nickname", ""),
            "conflict": cards[NAPCAT]["running"] and cards[SNOWLUMA]["running"],
            "login_task": {"state": task.state, "task_id": task.id} if task else None,
            "astrbot_ws_url": self.astrbot.ws_url(slot),
        }

    def overview(self) -> dict:
        slots = self.slots()
        items: list[dict] = []
        if slots:
            with ThreadPoolExecutor(max_workers=min(8, len(slots))) as ex:
                futures = {s: ex.submit(self.slot_overview, s) for s in slots}
                for s in slots:
                    try:
                        items.append(futures[s].result())
                    except Exception as e:
                        items.append({"slot": s, "display_name": display_name(s), "active": self.active(s), "error": str(e)})
        sl = self.store.snowluma()
        astr = self.docker.state(self.host.astrbot_container)
        rows = self.docker.tcp_table(self.host.astrbot_container) if astr.get("running") else []
        for item in items:
            if "active" not in item or "error" in item:
                continue
            try:
                port = self.astrbot.ws_port(item["slot"])
                card = item[item["active"]]
                ips = set()
                st = self.docker.state(card["container"]) if card.get("running") else {}
                ips = {ip for ip in (st.get("ips") or {}).values() if ip}
                peers = {r["remote_ip"] for r in rows if r["local_port"] == port and r["state"] == "ESTABLISHED"}
                item["onebot"] = {"port": port, "listening": any(r["local_port"] == port and r["state"] == "LISTEN" for r in rows),
                                  "connected": bool(ips & peers)}
            except Exception as e:
                item["onebot"] = {"error": str(e)}
        return {
            "slots": items,
            "astrbot": {"container": self.host.astrbot_container, "running": bool(astr.get("running")), "status": astr.get("status")},
            "snowluma": {"image": sl.get("image"), "pinned_digest": sl.get("pinned_digest"), "consent": sl.get("consent"),
                         "license": SNOWLUMA_LICENSE, "installed": sorted((sl.get("instances") or {}).keys())},
            "summary": {
                "total": len(items),
                "napcat": sum(1 for i in items if i.get("active") == NAPCAT),
                "snowluma": sum(1 for i in items if i.get("active") == SNOWLUMA),
                "online": sum(1 for i in items if i.get("online")),
                "conflicts": sum(1 for i in items if i.get("conflict")),
                "connected": sum(1 for i in items if (i.get("onebot") or {}).get("connected")),
            },
            "generated_at": now_text(),
        }

    # ------------------------------------------------------------------
    # switching
    # ------------------------------------------------------------------
    def _lock(self, slot: str) -> threading.Lock:
        with self.switch_guard:
            return self.switch_locks.setdefault(slot, threading.Lock())

    def switch(self, slot: str, target: str, log=print, user: str = "") -> dict:
        self._require_slot(slot)
        if target not in PROTOCOLS:
            raise ProtocolError("目标协议端不支持：%s" % target)
        lock = self._lock(slot)
        if not lock.acquire(blocking=False):
            raise ProtocolError("%s 已有切换任务在执行" % display_name(slot))
        try:
            return self._switch(slot, target, log, user)
        finally:
            lock.release()

    def _switch(self, slot: str, target: str, log, user: str) -> dict:
        current = self.active(slot)
        src, dst = self.adapters[current], self.adapters[target]
        name = display_name(slot)
        warnings: list[str] = []
        log("① 检查当前协议端：%s 当前使用 %s" % (name, LABELS[current]))
        if target == current:
            if not self.docker.state(dst.container(slot)).get("running"):
                res = dst.activate(slot)
                log("%s 未运行，已启动：%s" % (LABELS[target], "成功" if res.get("ok") else "失败"))
            return {"ok": True, "slot": slot, "active": target, "changed": False, "message": "已经在使用 %s" % LABELS[target]}
        if not dst.installed(slot):
            raise ProtocolError("%s 尚未安装到 %s，请先安装" % (LABELS[target], name))
        busy = self.host.busy(slot)
        if busy:
            raise ProtocolError("③ 存在正在执行的关键操作，暂不能切换：%s" % busy)
        log("③ 没有正在执行的关键操作")
        self.logins.cancel_slot(slot, "切换协议端，已取消旧的登录任务")

        # ② snapshot both sides so a failed switch can be restored exactly
        snaps = {}
        for proto, a in ((current, src), (target, dst)):
            try:
                snaps[proto] = backup_dirs(self.host, slot, proto, a.config_dirs(slot), "pre-switch")
            except Exception as e:
                snaps[proto] = None
                warnings.append("备份 %s 配置失败：%s" % (LABELS[proto], e))
        log("② 已保存当前协议端配置：%s" % ", ".join(str(p) for p in snaps.values() if p))
        src_was_running = bool(self.docker.state(src.container(slot)).get("running"))
        self.store.update_slot(slot, switching=True, switch_target=target, switch_started=now_text())
        self._log_switch({"slot": slot, "from": current, "to": target, "event": "start", "user": user})

        def rollback(reason: str) -> dict:
            log("✗ 切换失败：%s —— 开始回滚到 %s" % (reason, LABELS[current]))
            try:
                dst.deactivate(slot)
            except Exception as e:
                log("停止 %s 时出错：%s" % (LABELS[target], e))
            self.docker.wait_running(dst.container(slot), False, 40)
            if snaps.get(target):
                try:
                    restore_backup(snaps[target], dst.config_dirs(slot), target)
                except Exception as e:
                    log("恢复 %s 配置失败：%s" % (LABELS[target], e))
            restored = True
            if src_was_running or current == NAPCAT:
                res = src.activate(slot)
                restored = bool(res.get("ok")) and self.docker.wait_running(src.container(slot), True, 60)
            self.store.update_slot(slot, active=current, switching=False, switch_target="")
            self.store.add_history(slot, {"from": current, "to": target, "ok": False, "reason": reason[:300], "rolled_back": restored, "user": user})
            self._log_switch({"slot": slot, "from": current, "to": target, "event": "rollback", "reason": reason, "restored": restored})
            msg = "切换失败，已回滚到 %s" % LABELS[current] if restored else "切换失败且回滚未能启动 %s，请到诊断页处理" % LABELS[current]
            log(msg)
            return {"ok": False, "slot": slot, "active": current, "rolled_back": restored, "message": msg, "reason": reason, "warnings": warnings}

        try:
            # ④ stop current – must be fully stopped before the target touches the account
            log("④ 停止 %s" % LABELS[current])
            src.deactivate(slot)
            if not self.docker.wait_running(src.container(slot), False, 60):
                # nothing has been changed on the target yet; just bring the source back
                src.activate(slot)
                self.store.update_slot(slot, switching=False, switch_target="")
                raise ProtocolError("%s 无法停止，已放弃切换" % LABELS[current])
            # ⑦ connection config for the target (before it starts)
            ws_url, token = self.astrbot.ws_url(slot), self.host.reverse_token
            changed = dst.apply_onebot(slot, ws_url, token)
            log("⑦ OneBot 反向 WebSocket → %s（配置%s）" % (ws_url, "已更新" if changed else "无需修改"))
            ok, why = dst.onebot_token_ok(slot)
            if not ok:
                return rollback("目标协议端 OneBot 配置校验失败：%s" % why)
            # ⑤ start target
            log("⑤ 启动 %s" % LABELS[target])
            res = dst.activate(slot)
            if not res.get("ok") or not self.docker.wait_running(dst.container(slot), True, 90):
                return rollback("%s 启动失败：%s" % (LABELS[target], (res.get("output") or "")[-300:]))
            ready, why = False, ""
            for _ in range(30):
                ready, why = dst.ready(slot)
                if ready:
                    break
                time.sleep(3)
            if not ready:
                return rollback("%s 启动后未就绪：%s" % (LABELS[target], why))
            log("%s 已就绪：%s" % (LABELS[target], why))
            # AstrBot side – platform id/port/token are per slot and do not change, so this
            # is normally a no-op and AstrBot (plugins, models, personas, data) is untouched.
            problem = self.astrbot.platform_problem(slot)
            if problem:
                log("AstrBot 平台配置需要修正：%s" % problem)
                self.astrbot.ensure_platform(log)
                problem = self.astrbot.platform_problem(slot)
                if problem:
                    warnings.append("AstrBot 平台配置仍有问题：%s" % problem)
            else:
                log("⑦ AstrBot 平台配置正确（无需重启 AstrBot）")
            # ⑥/⑧ OneBot / AstrBot connection – needs a logged-in QQ
            login = dst.get_login_status(slot)
            link = {}
            if login.get("online"):
                for _ in range(15):
                    link = self.astrbot.link(slot, dst.container(slot))
                    if link.get("connected"):
                        break
                    time.sleep(3)
                if link.get("connected"):
                    log("⑧ AstrBot 已与 %s 建立连接（QQ %s）" % (LABELS[target], login.get("uin")))
                else:
                    warnings.append("QQ 已登录但 AstrBot 连接未建立，请运行诊断")
                    log("⑧ QQ 已登录，但尚未检测到与 AstrBot 的连接")
            else:
                link = self.astrbot.link(slot)
                log("⑥ %s 尚未登录 QQ：登录后会自动连接 AstrBot（AstrBot 端口 %s %s）" % (LABELS[target], link.get("port"), "监听中" if link.get("listening") else "未监听"))
                warnings.append("%s 需要扫码登录" % LABELS[target])
            # ⑨ commit
            self.store.update_slot(slot, active=target, switching=False, switch_target="", switched_at=now_text())
            self.store.add_history(slot, {"from": current, "to": target, "ok": True, "user": user, "warnings": warnings[:5]})
            self._log_switch({"slot": slot, "from": current, "to": target, "event": "done", "warnings": warnings})
            log("⑨ 切换完成：%s 现在使用 %s" % (name, LABELS[target]))
            return {"ok": True, "slot": slot, "active": target, "changed": True, "needs_login": not login.get("online"),
                    "login": login, "link": link, "warnings": warnings, "snapshots": {k: str(v) for k, v in snaps.items() if v}}
        except ProtocolError:
            self.store.update_slot(slot, switching=False, switch_target="")
            raise
        except Exception as e:
            return rollback("%s: %s" % (type(e).__name__, e))

    # ------------------------------------------------------------------
    # exclusivity
    # ------------------------------------------------------------------
    def reconcile(self, log=None) -> list[dict]:
        """Make sure the inactive protocol end of every slot is stopped."""
        actions = []
        data = self.store.load()
        installed = set((data["snowluma"].get("instances") or {}).keys())
        for slot in self.slots():
            meta = data["slots"].get(slot) or {}
            if meta.get("switching"):
                started = meta.get("switch_started") or ""
                try:
                    stale = time.time() - time.mktime(time.strptime(started, "%Y-%m-%d %H:%M:%S")) > 1800
                except Exception:
                    stale = True
                if not stale or self._lock(slot).locked():
                    continue
                self.store.update_slot(slot, switching=False, switch_target="")
            active = meta.get("active") if meta.get("active") in PROTOCOLS else NAPCAT
            if active == NAPCAT and slot not in installed:
                continue  # legacy slot, SnowLuma never installed: nothing to enforce
            inactive = SNOWLUMA if active == NAPCAT else NAPCAT
            a = self.adapters[inactive]
            if not a.installed(slot):
                continue
            st = self.docker.state(a.container(slot))
            if st.get("running") or (inactive == NAPCAT and st.get("restart_policy") not in ("", "no")):
                try:
                    a.deactivate(slot)
                    row = {"slot": slot, "stopped": inactive, "active": active, "reason": "同一账号只能由一个协议端接管"}
                    actions.append(row)
                    self._log_switch({"event": "reconcile", **row})
                    if log:
                        log("已停止 %s 的 %s（当前协议端为 %s）" % (display_name(slot), LABELS[inactive], LABELS[active]))
                except Exception as e:
                    actions.append({"slot": slot, "error": str(e)})
        return actions

    def start_reconciler(self, interval: int = 60) -> None:
        def loop():
            time.sleep(15)
            while not self._reconcile_stop.is_set():
                try:
                    self.reconcile()
                except Exception:
                    pass
                self._reconcile_stop.wait(interval)
        threading.Thread(target=loop, daemon=True, name="protocol-reconcile").start()

    # ------------------------------------------------------------------
    # protocol actions
    # ------------------------------------------------------------------
    def action(self, slot: str, proto: str, action: str) -> dict:
        self._require_slot(slot)
        a = self.adapter(proto)
        active = self.active(slot)
        if action in ("start", "restart") and proto != active:
            raise ProtocolError("%s 当前使用 %s；同一账号不能同时由两个协议端接管，请用「切换」" % (display_name(slot), LABELS[active]))
        if self.store.slot(slot).get("switching"):
            raise ProtocolError("正在切换协议端，请稍候")
        if action == "start":
            return a.activate(slot)
        if action == "stop":
            self.logins.cancel_slot(slot, "协议端已停止")
            return a.stop(slot)
        if action == "restart":
            self.logins.cancel_slot(slot, "协议端重启，登录任务已取消")
            return a.restart(slot)
        raise ProtocolError("操作不支持：%s" % action)

    # ------------------------------------------------------------------
    # login hooks
    # ------------------------------------------------------------------
    def _after_login(self, task: LoginTask) -> None:
        slot, proto = task.slot, task.protocol
        a = self.adapters[proto]
        if not task.account.get("uin") or not task.account.get("nickname"):
            st = a.get_login_status(slot)
            task.account.update({k: v for k, v in {"uin": st.get("uin"), "nickname": st.get("nickname")}.items() if v})
        task.checks.append({"id": "account", "title": "识别 QQ 账号", "ok": bool(task.account.get("uin")),
                            "detail": "%s %s" % (task.account.get("nickname", ""), task.account.get("uin", "")) if task.account.get("uin") else "协议端未返回账号"})
        self.store.update_slot(slot, login={"uin": task.account.get("uin", ""), "nickname": task.account.get("nickname", ""),
                                            "protocol": proto, "at": now_text(), "already": task.already})
        cb = self.host.extra.get("on_login_success")
        if cb:
            try:
                cb(slot, proto)
            except Exception:
                pass
        ok, why = a.onebot_token_ok(slot)
        task.checks.append({"id": "onebot", "title": "OneBot 配置", "ok": ok, "detail": why})
        link = {}
        for _ in range(10):
            link = self.astrbot.link(slot, a.container(slot))
            if link.get("connected"):
                break
            time.sleep(3)
        task.checks.append({"id": "astrbot_listen", "title": "AstrBot 监听", "ok": bool(link.get("listening")),
                            "detail": "端口 %s %s" % (link.get("port"), "监听中" if link.get("listening") else "未监听")})
        task.checks.append({"id": "astrbot_link", "title": "AstrBot 连接", "ok": bool(link.get("connected")),
                            "detail": "已建立反向 WebSocket" if link.get("connected") else "暂未检测到连接（可在诊断页复查）"})
        task.event("登录后检查完成")

    # ------------------------------------------------------------------
    # diagnostics
    # ------------------------------------------------------------------
    def diagnose(self, slot: str) -> dict:
        self._require_slot(slot)
        active = self.active(slot)
        a = self.adapters[active]
        other = self.adapters[SNOWLUMA if active == NAPCAT else NAPCAT]
        checks: list[dict] = []

        def add(cid, title, ok, detail, suggestion=""):
            checks.append({"id": cid, "title": title, "ok": ok, "detail": detail, "suggestion": suggestion if ok is False else ""})
            return ok

        name = a.container(slot)
        st = self.docker.state(name)
        running = add("protocol_running", "1. 协议端是否运行", bool(st.get("running")),
                      "%s（%s）状态：%s" % (LABELS[active], name, st.get("status")), "在「协议端」页启动 %s" % LABELS[active])
        if other.installed(slot):
            ost = self.docker.state(other.container(slot))
            add("exclusive", "账号独占", not ost.get("running"),
                "%s %s" % (LABELS[other.kind], "也在运行（会抢占同一账号）" if ost.get("running") else "已停止"),
                "面板会自动停止非当前协议端；也可手动停止 %s" % LABELS[other.kind])
        if running:
            ready, why = a.ready(slot)
            add("protocol_ready", "协议端服务就绪", ready, why, "重启协议端；持续失败请查看协议端日志")
        login = a.get_login_status(slot) if running else {"online": False, "phase": "stopped"}
        add("qq_online", "2. QQ 是否在线", bool(login.get("online")),
            ("已登录 %s %s" % (login.get("nickname", ""), login.get("uin", ""))) if login.get("online") else "未登录（阶段：%s）" % (login.get("phase") or "未知"),
            "到「登录」页申请登录")
        # 3. OneBot listener
        if active == SNOWLUMA:
            if login.get("online"):
                ok, res = a.onebot_call(slot, "get_status")
                add("onebot_port", "3. OneBot 端口是否监听", ok, "HTTP API %s" % ("可用" if ok else "不可达：%s" % str(res)[:120]), "重启 SnowLuma")
            else:
                add("onebot_port", "3. OneBot 端口是否监听", None, "SnowLuma 在 QQ 登录后才创建 OneBot 实例，当前跳过")
        else:
            rows = self.docker.tcp_table(name) if running else []
            listening = sorted({r["local_port"] for r in rows if r["state"] == "LISTEN" and r["local_port"] in (3000, 3001, 6099)})
            add("onebot_port", "3. OneBot / WebUI 端口是否监听", 6099 in listening if running else False,
                "容器内监听端口：%s" % (", ".join(map(str, listening)) or "无"), "重启 NapCat")
        link = self.astrbot.link(slot, name)
        add("ws_connected", "4. WebSocket 是否连接", bool(link.get("connected")),
            "AstrBot:%s 的连接来源 %s；协议端 IP %s" % (link.get("port"), ", ".join(link.get("peers") or []) or "无", ", ".join(link.get("peer_ips") or []) or "无"),
            "QQ 未登录时不会连接；已登录仍未连接请运行修复")
        ok, why = a.onebot_token_ok(slot)
        add("token", "5. Token 是否正确", ok, why, "在协议端页点击「修复」重写连接配置")
        problem = self.astrbot.platform_problem(slot)
        add("astrbot_platform", "6. AstrBot 平台配置", not problem, problem or "aiocqhttp 反向 WS，端口 %s" % link.get("port"), "在 AstrBot 页执行「一键配置」")
        add("astrbot_listen", "6. AstrBot 是否在监听", bool(link.get("listening")),
            "AstrBot %s，端口 %s %s" % ("运行中" if link.get("astrbot_running") else "未运行", link.get("port"), "监听中" if link.get("listening") else "未监听"),
            "启动或重启 AstrBot")
        net = self.host.network
        astr_nets = self.docker.state(self.host.astrbot_container).get("networks") or []
        add("network", "7. Docker 网络是否正常", net in astr_nets and net in (st.get("networks") or []),
            "%s：AstrBot %s，%s %s" % (net, "已加入" if net in astr_nets else "未加入", LABELS[active], "已加入" if net in (st.get("networks") or []) else "未加入"),
            "在协议端页点击「修复」或 AstrBot 页「一键配置」")
        failed = [c for c in checks if c["ok"] is False]
        return {"slot": slot, "display_name": display_name(slot), "protocol": active, "label": LABELS[active], "checks": checks,
                "ok": not failed, "summary": "全部正常" if not failed else "发现 %d 个问题：%s" % (len(failed), "、".join(c["title"] for c in failed)),
                "generated_at": now_text()}

    def diagnose_text(self, report: dict) -> str:
        lines = ["奶龙一键诊断 · %s（%s）· %s" % (report["display_name"], report["label"], report["generated_at"]), ""]
        for c in report["checks"]:
            mark = "✔" if c["ok"] else ("—" if c["ok"] is None else "✘")
            lines.append("%s %s：%s" % (mark, c["title"], c["detail"]))
            if c.get("suggestion"):
                lines.append("    建议：%s" % c["suggestion"])
        lines += ["", "结论：%s" % report["summary"]]
        return "\n".join(lines)


def tail_lines(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    from collections import deque
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return "".join(deque(f, maxlen=max(1, min(lines, 5000))))

