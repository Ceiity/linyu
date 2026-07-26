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

Owner is `3179806299` by default. Bot self account is restricted to `2141945863`.


Login success notice:

After the QR image is sent, the plugin polls login status for about 3 minutes. If the QQ account logs in successfully, it sends the QQ avatar and a success message with nickname and QQ number.

Avatar URL format:

`http://q.qlogo.cn/headimg_dl?dst_uin=<QQ>&spec=640&img_type=jpg`

QR refresh behavior:

- `qr_retry_seconds` defaults to 60 seconds. If the first QR code expires or was not scanned in time, the user can send the trigger again after 60 seconds to get a fresh QR code.
- The panel remote API still has server-side rate limiting to prevent abuse.
