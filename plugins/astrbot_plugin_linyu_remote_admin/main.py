from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import time
from pathlib import Path
from urllib import request as urlrequest

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

TRIGGER_APPLY_LOGIN = "\u7533\u8bf7\u767b\u5f55"
DEFAULT_BOT_SELF_ID = "2141945863"
DEFAULT_OWNER_ID = "3179806299"


@register(
    "astrbot_plugin_linyu_remote_admin",
    "linyu",
    "\u53d1\u9001\u7533\u8bf7\u767b\u5f55\uff0c\u81ea\u52a8\u7533\u8bf7\u4e00\u4e2a NapCat \u626b\u7801\u673a\u5668\u4eba\u3002",
    "1.0.2",
    "https://github.com/Ceiity/linyu",
)
class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.cooldowns: dict[str, float] = {}

    def _cfg(self, key: str, default=None):
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    @staticmethod
    def _as_str_set(value) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            return {value.strip()} if value.strip() else set()
        try:
            return {str(x).strip() for x in value if str(x).strip()}
        except Exception:
            return set()

    @staticmethod
    def _sender_id(event: AstrMessageEvent) -> str:
        try:
            return str(event.get_sender_id())
        except Exception:
            try:
                return str(event.message_obj.sender.user_id)
            except Exception:
                return ""

    @staticmethod
    def _group_id(event: AstrMessageEvent) -> str:
        try:
            return str(getattr(event.message_obj, "group_id", "") or "")
        except Exception:
            return ""

    @staticmethod
    def _self_id(event: AstrMessageEvent) -> str:
        probes = []
        try:
            probes.append(event.get_self_id())
        except Exception:
            pass
        for attr in ("self_id", "bot_id", "account_id"):
            try:
                probes.append(getattr(event, attr, ""))
            except Exception:
                pass
        try:
            msg = event.message_obj
            for attr in ("self_id", "bot_id", "account_id"):
                probes.append(getattr(msg, attr, ""))
            raw = getattr(msg, "raw_message", None) or getattr(msg, "raw", None) or {}
            if isinstance(raw, dict):
                for key in ("self_id", "bot_id"):
                    probes.append(raw.get(key, ""))
        except Exception:
            pass
        for item in probes:
            text = str(item or "").strip()
            if text and text.lower() != "none":
                return text
        return ""

    def _allowed(self, event: AstrMessageEvent) -> tuple[bool, str]:
        sender = self._sender_id(event)
        group = self._group_id(event)
        self_id = self._self_id(event)
        allowed_bots = self._as_str_set(self._cfg("bot_self_ids", [DEFAULT_BOT_SELF_ID]))
        owners = self._as_str_set(self._cfg("owner_ids", [DEFAULT_OWNER_ID]))
        groups = self._as_str_set(self._cfg("allowed_groups", []))
        if allowed_bots and self_id not in allowed_bots:
            return False, ""
        if not owners:
            return False, "\u8fd8\u6ca1\u6709\u914d\u7f6e\u4e3b\u4eba QQ\u3002\u8bf7\u5148\u5728\u63d2\u4ef6\u914d\u7f6e\u91cc\u586b\u5199 owner_ids\u3002"
        if sender not in owners:
            return False, "\u4f60\u6ca1\u6709\u6743\u9650\u7533\u8bf7\u767b\u5f55\u3002"
        if groups and group and group not in groups:
            return False, "\u5f53\u524d\u7fa4\u6ca1\u6709\u542f\u7528\u7533\u8bf7\u767b\u5f55\u6743\u9650\u3002"
        return True, ""

    def _cooldown_ok(self, sender: str) -> tuple[bool, int]:
        seconds = int(self._cfg("cooldown_seconds", 300) or 300)
        now_ts = time.time()
        last = self.cooldowns.get(sender, 0)
        left = int(seconds - (now_ts - last))
        if left > 0:
            return False, left
        self.cooldowns[sender] = now_ts
        return True, 0

    def _post_json_sync(self, path: str, payload: dict) -> dict:
        base = str(self._cfg("server_url", "http://127.0.0.1:7070")).rstrip("/")
        token = str(self._cfg("remote_token", "") or "")
        if not token:
            raise RuntimeError("\u63d2\u4ef6\u6ca1\u6709\u914d\u7f6e remote_token\u3002")
        raw = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            base + path,
            data=raw,
            method="POST",
            headers={"Content-Type": "application/json", "X-Remote-Token": token},
        )
        with urlrequest.urlopen(req, timeout=180) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        if not data.get("ok"):
            raise RuntimeError(str(data.get("message") or data.get("code") or "remote api failed"))
        return data.get("data") or {}

    async def _create_login(self, event: AstrMessageEvent) -> dict:
        payload = {
            "requester": self._sender_id(event),
            "group_id": self._group_id(event),
            "bot_self_id": self._self_id(event),
            "source": "astrbot_plugin_linyu_remote_admin",
        }
        return await asyncio.to_thread(self._post_json_sync, "/api/remote/napcat/create-login", payload)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        triggers = self._as_str_set(self._cfg("triggers", [TRIGGER_APPLY_LOGIN]))
        if text not in triggers:
            return
        allowed, reason = self._allowed(event)
        if not allowed:
            if reason:
                yield event.plain_result(reason)
            return
        sender = self._sender_id(event)
        ok, left = self._cooldown_ok(sender)
        if not ok:
            yield event.plain_result(f"\u7533\u8bf7\u592a\u9891\u7e41\u5566\uff0c\u8bf7 {left} \u79d2\u540e\u518d\u8bd5\u3002")
            return
        yield event.plain_result("\u6b63\u5728\u7533\u8bf7\u626b\u7801\u767b\u5f55\u4e8c\u7ef4\u7801\uff0c\u8bf7\u7a0d\u7b49\u2026\u2026")
        try:
            data = await self._create_login(event)
        except Exception as e:
            logger.exception("NapCat login QR request failed")
            yield event.plain_result(f"\u7533\u8bf7\u5931\u8d25\uff1a{e}")
            return
        if data.get("already_login"):
            who = data.get("login_name") or data.get("login_uin") or "\u672a\u77e5 QQ"
            extra = f"\uff08{data.get('login_uin')}\uff09" if data.get("login_name") and data.get("login_uin") else ""
            yield event.plain_result(f"{data.get('display_name') or data.get('name') or '\u673a\u5668\u4eba'} \u5df2\u7ecf\u767b\u5f55\uff1a{who}{extra}\uff0c\u4e0d\u9700\u8981\u91cd\u590d\u626b\u7801\u3002")
            return
        png = str(data.get("qrcode_png_base64") or "")
        name = data.get("display_name") or data.get("name") or "\u673a\u5668\u4eba"
        if not png:
            yield event.plain_result(f"{name} \u4e8c\u7ef4\u7801\u6682\u65f6\u6ca1\u6709\u751f\u6210\uff0c\u8bf7\u7a0d\u540e\u518d\u7533\u8bf7\u3002")
            return
        try:
            path = Path(tempfile.gettempdir()) / f"linyu-napcat-login-{int(time.time())}.png"
            path.write_bytes(base64.b64decode(png))
            yield event.image_result(str(path))
            if data.get("recovered"):
                yield event.plain_result(f"\u68c0\u6d4b\u5230 {name} \u5047\u5728\u7ebf\uff0c\u5df2\u81ea\u52a8\u91cd\u542f\u5e76\u751f\u6210\u65b0\u4e8c\u7ef4\u7801\u3002")
            else:
                yield event.plain_result(f"{name} \u4e8c\u7ef4\u7801\u5df2\u751f\u6210\uff0c\u8bf7\u626b\u7801\u767b\u5f55\u3002")
        except Exception:
            logger.exception("QR image send failed")
            yield event.plain_result(f"{name} \u4e8c\u7ef4\u7801\u56fe\u7247\u53d1\u9001\u5931\u8d25\uff0c\u8bf7\u6253\u5f00 Web \u9762\u677f\u626b\u7801\u3002")

    async def terminate(self):
        self.cooldowns.clear()
