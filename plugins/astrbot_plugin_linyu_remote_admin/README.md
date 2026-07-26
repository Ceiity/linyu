# astrbot_plugin_linyu_remote_admin

Trigger command: `\u7533\u8bf7\u767b\u5f55`.

Runtime behavior:

- Only QQ user `3179806299` can request login.
- Only bot self account `2141945863` responds.
- The plugin sends only the QR image and does not expose the QQ login URL in chat.
- It reuses idle NapCat instances first; it creates a new one only when no idle slot exists.
