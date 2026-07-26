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


@register(
    "astrbot_plugin_linyu_remote_admin",
    "linyu",
    "在 QQ 中发送“登录”，自动创建 NapCat 机器人并返回扫码二维码。",
    "1.0.0",
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

    def _allowed(self, event: AstrMessageEvent) -> tuple[bool, str]:
        sender = self._sender_id(event)
        group = self._group_id(event)
        owners = self._as_str_set(self._cfg("owner_ids", []))
        groups = self._as_str_set(self._cfg("allowed_groups", []))
        if not owners:
            return False, "还没有配置主人 QQ。请先在插件配置里填写 owner_ids，避免陌生人创建机器人。"
        if sender not in owners:
            return False, "你没有权限创建机器人。"
        if groups and group and group not in groups:
            return False, "当前群没有启用创建机器人权限。"
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
            raise RuntimeError("插件没有配置 remote_token。")
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
            raise RuntimeError(str(data.get("message") or data.get("code") or "远程接口调用失败"))
        return data.get("data") or {}

    async def _create_login(self, event: AstrMessageEvent) -> dict:
        payload = {
            "requester": self._sender_id(event),
            "group_id": self._group_id(event),
            "source": "astrbot_plugin_linyu_remote_admin",
        }
        return await asyncio.to_thread(self._post_json_sync, "/api/remote/napcat/create-login", payload)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        triggers = self._as_str_set(self._cfg("triggers", ["登录", "扫码登录", "创建机器人", "机器人登录"]))
        if text not in triggers:
            return
        allowed, reason = self._allowed(event)
        if not allowed:
            yield event.plain_result(reason)
            return
        sender = self._sender_id(event)
        ok, left = self._cooldown_ok(sender)
        if not ok:
            yield event.plain_result(f"创建太频繁啦，请 {left} 秒后再试。")
            return
        yield event.plain_result("正在创建机器人并生成扫码二维码，请稍等……")
        try:
            data = await self._create_login(event)
        except Exception as e:
            logger.exception("创建 NapCat 扫码登录失败")
            yield event.plain_result(f"创建失败：{e}")
            return
        if data.get("already_login"):
            who = data.get("login_name") or data.get("login_uin") or "未知 QQ"
            extra = f"（{data.get('login_uin')}）" if data.get("login_name") and data.get("login_uin") else ""
            yield event.plain_result(f"{data.get('display_name') or data.get('name') or '机器人'} 已经登录：{who}{extra}，不需要重复扫码。")
            return
        png = str(data.get("qrcode_png_base64") or "")
        if png:
            path = Path(tempfile.gettempdir()) / f"linyu-napcat-login-{int(time.time())}.png"
            path.write_bytes(base64.b64decode(png))
            yield event.image_result(str(path))
        qrcode_url = str(data.get("qrcode_url") or "")
        name = data.get("display_name") or data.get("name") or "机器人"
        if qrcode_url:
            action = "复用空闲机器人" if data.get("reused") else "新建机器人"
            yield event.plain_result(f"{action}：{name} 扫码登录二维码已生成。如果图片没有显示，请复制链接到浏览器打开：\n{qrcode_url}")
        else:
            yield event.plain_result(f"{name} 已创建，但没有拿到二维码链接，请稍后再试。")

    async def terminate(self):
        self.cooldowns.clear()
