# astrbot_plugin_linyu_remote_admin

Trigger command: `\u7533\u8bf7\u767b\u5f55`.

Runtime behavior:

- Only QQ user `3179806299` can request login.
- Only bot self account `2141945863` responds.
- The plugin sends only the QR image and does not expose the QQ login URL in chat.
- It reuses idle NapCat instances first; it creates a new one only when no idle slot exists.


Owner commands:

- `\u767b\u5f55\u5f00\u542f`: allow everyone to use `\u7533\u8bf7\u767b\u5f55`.
- `\u767b\u5f55\u5173\u95ed`: only owner can use `\u7533\u8bf7\u767b\u5f55`.
- `\u65e0\u9700@\u65e0\u9700\u524d\u7f00` (also accepts `\u65e0\u9700at\u65e0\u9700\u524d\u7f00`): apply AstrBot group-chat no-mention/no-prefix wake settings.
- `\u5220\u9664\u673a\u5668\u4eba napcat-1`: delete one NapCat instance from QQ, keeping the data directory by default.

Owner is `3179806299` by default. Bot self account is restricted to `2141945863`.


Login success notice:

After the QR image is sent, the plugin polls login status for about 3 minutes. If the QQ account logs in successfully, it sends the QQ avatar and a success message with nickname and QQ number.

Avatar URL format:

`http://q.qlogo.cn/headimg_dl?dst_uin=<QQ>&spec=640&img_type=jpg`

QR refresh behavior:

- `qr_retry_seconds` defaults to 60 seconds. If the first QR code expires or was not scanned in time, the user can send the trigger again after 60 seconds to get a fresh QR code.
- The panel remote API still has server-side rate limiting to prevent abuse.

Remote API used by the no-prefix owner command:

`POST /api/remote/astrbot/no-prefix`

The request must include a valid `X-Remote-Token`, configured owner QQ as `requester`, and configured managed bot QQ as `bot_self_id`. Public-login users cannot call this endpoint.

Public login access is now controlled by the panel as the security source of truth. Owner commands call:

`POST /api/remote/login/public-access`

Remote API authentication accepts the token only from the `X-Remote-Token` header. Tokens in JSON bodies are rejected.

Remote API used by the delete owner command:

`POST /api/remote/napcat/delete`

Only configured owners can call it through the plugin.
