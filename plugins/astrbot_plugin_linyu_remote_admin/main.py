from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import time
from pathlib import Path
from urllib import request as urlrequest

from astrbot.api import AstrBotConfig, logger, message_components as Comp
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

TRIGGER_APPLY_LOGIN = "\u7533\u8bf7\u767b\u5f55"
DEFAULT_BOT_SELF_ID = "2141945863"
DEFAULT_OWNER_ID = "3179806299"
CMD_LOGIN_OPEN = "\u767b\u5f55\u5f00\u542f"
CMD_LOGIN_CLOSE = "\u767b\u5f55\u5173\u95ed"
CMD_CREATE_BOT = "\u521b\u5efa\u673a\u5668\u4eba"
CMD_NO_PREFIX_ALIASES = {
    "\u65e0\u9700@\u65e0\u9700\u524d\u7f00",
    "\u65e0\u9700at\u65e0\u9700\u524d\u7f00",
    "\u65e0\u9700at\u65e0\u9700\u524d\u6233",
    "\u514d@\u514d\u524d\u7f00",
    "\u514dat\u514d\u524d\u7f00",
}


@register(
    "astrbot_plugin_linyu_remote_admin",
    "linyu",
    "\u53d1\u9001\u7533\u8bf7\u767b\u5f55\uff0c\u81ea\u52a8\u7533\u8bf7\u4e00\u4e2a NapCat \u626b\u7801\u673a\u5668\u4eba\u3002",
    "1.0.9",
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

    def _state_path(self) -> Path:
        return Path(__file__).resolve().parent / "linyu_remote_admin_state.json"

    def _public_login_enabled(self) -> bool:
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8"))
            return bool(data.get("public_login_enabled", False))
        except Exception:
            return False

    def _set_public_login_enabled(self, enabled: bool) -> None:
        path = self._state_path()
        payload = {"public_login_enabled": bool(enabled), "updated_at": int(time.time())}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        sender = self._sender_id(event)
        owners = self._as_str_set(self._cfg("owner_ids", [DEFAULT_OWNER_ID]))
        return bool(owners) and sender in owners

    def _is_managed_bot(self, event: AstrMessageEvent) -> bool:
        self_id = self._self_id(event)
        allowed_bots = self._as_str_set(self._cfg("bot_self_ids", [DEFAULT_BOT_SELF_ID]))
        return bool(allowed_bots) and self_id in allowed_bots

    def _target_allowed(self, event: AstrMessageEvent) -> bool:
        if self._cfg("enabled", True) is False:
            return False
        if not self._is_managed_bot(event):
            return False
        groups = self._as_str_set(self._cfg("allowed_groups", []))
        group = self._group_id(event)
        if groups and group not in groups:
            return False
        return True

    def _hard_allowed(self, event: AstrMessageEvent) -> bool:
        """Owner-only commands: create bot and toggle public login."""
        return self._target_allowed(event) and self._is_owner(event)

    def _allowed(self, event: AstrMessageEvent) -> tuple[bool, str]:
        if self._cfg("enabled", True) is False:
            return False, "\u8fdc\u7a0b\u7533\u8bf7\u767b\u5f55\u5df2\u5173\u95ed\u3002"
        if not self._target_allowed(event):
            return False, ""
        owners = self._as_str_set(self._cfg("owner_ids", [DEFAULT_OWNER_ID]))
        if not owners:
            return False, "\u8fd8\u6ca1\u6709\u914d\u7f6e\u4e3b\u4eba QQ\u3002\u8bf7\u5148\u5728\u63d2\u4ef6\u914d\u7f6e\u91cc\u586b\u5199 owner_ids\u3002"
        if self._is_owner(event):
            return True, ""
        if self._public_login_enabled():
            return True, ""
        return False, ""

    def _cooldown_ok(self, sender: str) -> tuple[bool, int]:
        seconds = int(self._cfg("qr_retry_seconds", 60) or 60)
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
            "allow_create": self._is_owner(event),
            "public_login_enabled": self._public_login_enabled(),
        }
        return await asyncio.to_thread(self._post_json_sync, "/api/remote/napcat/create-login", payload)

    async def _login_status(self, event: AstrMessageEvent, name: str) -> dict:
        payload = {
            "name": name,
            "requester": self._sender_id(event),
            "group_id": self._group_id(event),
            "bot_self_id": self._self_id(event),
            "public_login_enabled": self._public_login_enabled(),
        }
        return await asyncio.to_thread(self._post_json_sync, "/api/remote/napcat/login-status", payload)

    async def _create_instances(self, event: AstrMessageEvent, count: int) -> dict:
        payload = {
            "requester": self._sender_id(event),
            "group_id": self._group_id(event),
            "bot_self_id": self._self_id(event),
            "source": "astrbot_plugin_linyu_remote_admin",
            "count": count,
        }
        return await asyncio.to_thread(self._post_json_sync, "/api/remote/napcat/create", payload)

    async def _apply_no_prefix(self, event: AstrMessageEvent) -> dict:
        payload = {
            "requester": self._sender_id(event),
            "group_id": self._group_id(event),
            "bot_self_id": self._self_id(event),
            "source": "astrbot_plugin_linyu_remote_admin",
        }
        return await asyncio.to_thread(self._post_json_sync, "/api/remote/astrbot/no-prefix", payload)

    async def _wait_login_success(self, event: AstrMessageEvent, name: str, timeout_seconds: int = 180, interval_seconds: int = 5) -> dict | None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            await asyncio.sleep(interval_seconds)
            try:
                data = await self._login_status(event, name)
                if data.get("already_login"):
                    return data
            except Exception:
                logger.exception("NapCat login status poll failed")
        return None

    @staticmethod
    def _avatar_url(qq: str) -> str:
        return f"http://q.qlogo.cn/headimg_dl?dst_uin={qq}&spec=640&img_type=jpg"

    @staticmethod
    def _download_avatar_sync(qq: str) -> str:
        url = Main._avatar_url(qq)
        req = urlrequest.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlrequest.urlopen(req, timeout=12) as resp:
            data = resp.read()
        path = Path(tempfile.gettempdir()) / f"linyu-qq-avatar-{qq}-{int(time.time())}.jpg"
        path.write_bytes(data)
        return str(path)

    async def _download_avatar(self, qq: str) -> str:
        return await asyncio.to_thread(self._download_avatar_sync, qq)

    @staticmethod
    def _image_text_result(event: AstrMessageEvent, image_path: str, text: str):
        return event.chain_result([Comp.Image.fromFileSystem(image_path), Comp.Plain(text)])

    @staticmethod
    def _login_success_text(data: dict, prefix: str = "\u767b\u5f55\u6210\u529f") -> str:
        login_name = str(data.get("login_name") or "")
        login_uin = str(data.get("login_uin") or "")
        who = login_name or login_uin or "\u672a\u77e5 QQ"
        extra = f"\uff08{login_uin}\uff09" if login_name and login_uin else ""
        server = data.get("server") if isinstance(data.get("server"), dict) else {}
        system = str(server.get("system") or "\u672a\u77e5")
        location = str(server.get("login_location") or server.get("public_ip") or server.get("panel_url") or "\u672a\u77e5")
        return f"{prefix}\nQQ\uff1a{who}{extra}\n\u670d\u52a1\u5668\uff1a{system}\n\u767b\u5f55\u5730\u70b9\uff1a{location}"

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        normalized = "".join(text.split()).lower()
        no_prefix_command = normalized in CMD_NO_PREFIX_ALIASES
        triggers = self._as_str_set(self._cfg("triggers", [TRIGGER_APPLY_LOGIN]))
        owner_command = text.startswith(CMD_CREATE_BOT) or text in {CMD_LOGIN_OPEN, CMD_LOGIN_CLOSE} or no_prefix_command
        if owner_command and not self._hard_allowed(event):
            return
        if no_prefix_command:
            yield event.plain_result("\u6b63\u5728\u5e94\u7528 AstrBot \u7fa4\u804a\u65e0\u9700 @ / \u65e0\u9700\u524d\u7f00\u914d\u7f6e\u2026\u2026")
            try:
                task = await self._apply_no_prefix(event)
                yield event.plain_result(
                    "\u914d\u7f6e\u4efb\u52a1\u5df2\u63d0\u4ea4\uff0c\u5b8c\u6210\u540e AstrBot \u4f1a\u81ea\u52a8\u5e94\u7528\u65b0\u8bbe\u7f6e\u3002\n"
                    f"\u4efb\u52a1 ID\uff1a{task.get('id', '')}"
                )
            except Exception as e:
                logger.exception("AstrBot no-prefix command failed")
                yield event.plain_result(f"\u5e94\u7528\u5931\u8d25\uff1a{e}")
            return
        if text.startswith(CMD_CREATE_BOT):
            parts = text.split()
            count = 1
            if len(parts) >= 2:
                try:
                    count = int(parts[1])
                except Exception:
                    count = 1
            count = max(1, min(count, 20))
            yield event.plain_result(f"\u6b63\u5728\u521b\u5efa\u673a\u5668\u4eba x{count}\uff0c\u8bf7\u7a0d\u7b49\u2026\u2026")
            try:
                task = await self._create_instances(event, count)
                yield event.plain_result(
                    f"\u521b\u5efa\u4efb\u52a1\u5df2\u63d0\u4ea4\uff1a{task.get('title', 'NapCat')}\n"
                    f"\u4efb\u52a1 ID\uff1a{task.get('id', '')}\n"
                    "\u53ef\u5728 Web \u9762\u677f\u7684\u4efb\u52a1\u8fdb\u5ea6\u91cc\u67e5\u770b\u3002"
                )
            except Exception as e:
                logger.exception("NapCat create command failed")
                yield event.plain_result(f"\u521b\u5efa\u5931\u8d25\uff1a{e}")
            return

        if text in {CMD_LOGIN_OPEN, CMD_LOGIN_CLOSE}:
            enabled = text == CMD_LOGIN_OPEN
            self._set_public_login_enabled(enabled)
            if enabled:
                yield event.plain_result("\u5df2\u5f00\u542f\u5168\u5458\u7533\u8bf7\u767b\u5f55\uff0c\u6240\u6709\u7528\u6237\u90fd\u53ef\u4ee5\u5411\u6302\u673a\u5668\u4eba\u53f7\u53d1\u9001\u201c\u7533\u8bf7\u767b\u5f55\u201d\u83b7\u53d6\u4e8c\u7ef4\u7801\u3002")
            else:
                yield event.plain_result("\u5df2\u5173\u95ed\u5168\u5458\u7533\u8bf7\u767b\u5f55\u6743\u9650\uff0c\u73b0\u5728\u53ea\u6709\u4e3b\u4eba\u53ef\u4ee5\u7533\u8bf7\u3002")
            return
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
            msg = str(e)
            if "NO_IDLE_NAPCAT" in msg:
                yield event.plain_result("\u5f53\u524d\u6ca1\u6709\u7a7a\u95f2\u673a\u5668\u4eba\u53ef\u7528\uff0c\u8bf7\u8054\u7cfb\u4e3b\u4eba\u5728\u9762\u677f\u91cc\u521b\u5efa\u673a\u5668\u4eba\uff0c\u6216\u7531\u4e3b\u4eba\u53d1\u9001\u201c\u7533\u8bf7\u767b\u5f55\u201d\u81ea\u52a8\u521b\u5efa\u3002")
            else:
                yield event.plain_result(f"\u7533\u8bf7\u5931\u8d25\uff1a{e}")
            return
        if data.get("already_login"):
            msg = self._login_success_text(data, "\u5df2\u7ecf\u767b\u5f55")
            if data.get("login_uin"):
                try:
                    avatar = await self._download_avatar(str(data.get("login_uin")))
                    yield self._image_text_result(event, avatar, msg + "\n\u4e0d\u9700\u8981\u91cd\u590d\u626b\u7801\u3002")
                    return
                except Exception:
                    logger.exception("QQ avatar send failed")
            yield event.plain_result(msg + "\n\u4e0d\u9700\u8981\u91cd\u590d\u626b\u7801\u3002")
            return
        png = str(data.get("qrcode_png_base64") or "")
        name = data.get("display_name") or data.get("name") or "\u673a\u5668\u4eba"
        if not png:
            yield event.plain_result("\u4e8c\u7ef4\u7801\u6682\u65f6\u6ca1\u6709\u751f\u6210\uff0c\u8bf7\u7a0d\u540e\u518d\u7533\u8bf7\u3002")
            return
        try:
            path = Path(tempfile.gettempdir()) / f"linyu-napcat-login-{int(time.time())}.png"
            path.write_bytes(base64.b64decode(png))
            yield event.image_result(str(path))
            if data.get("recovered"):
                yield event.plain_result("\u68c0\u6d4b\u5230\u767b\u5f55\u72b6\u6001\u5f02\u5e38\uff0c\u5df2\u81ea\u52a8\u91cd\u542f\u5e76\u751f\u6210\u65b0\u4e8c\u7ef4\u7801\u3002")
            else:
                yield event.plain_result("\u4e8c\u7ef4\u7801\u5df2\u751f\u6210\uff0c\u8bf7\u626b\u7801\u767b\u5f55\u3002")
            status = await self._wait_login_success(event, str(data.get("container") or data.get("name") or ""), timeout_seconds=180, interval_seconds=5)
            if status:
                login_uin = str(status.get("login_uin") or "")
                msg = self._login_success_text(status, "\u767b\u5f55\u6210\u529f")
                if login_uin:
                    try:
                        avatar = await self._download_avatar(login_uin)
                        yield self._image_text_result(event, avatar, msg)
                        return
                    except Exception:
                        logger.exception("QQ avatar send failed")
                yield event.plain_result(msg)
        except Exception:
            logger.exception("QR image send failed")
            yield event.plain_result("\u4e8c\u7ef4\u7801\u56fe\u7247\u53d1\u9001\u5931\u8d25\uff0c\u8bf7\u6253\u5f00 Web \u9762\u677f\u626b\u7801\u3002")

    async def terminate(self):
        self.cooldowns.clear()
