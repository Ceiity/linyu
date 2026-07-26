# 淋雨远程机器人管理插件

这个插件用于把 `AstrBot-Deploy` 的 Web 面板能力接入 QQ：主人在群聊或私聊里直接发送“登录”，插件会调用 Web 面板远程 API，自动创建一个 NapCat 实例，并把 QQ 登录二维码发回聊天窗口。

## 配置

插件安装后，在 AstrBot 插件配置页填写：

- `server_url`：Web 面板地址，例如 `http://172.17.0.1:7070`
- `remote_token`：`/opt/astrbot/panel_config.json` 中的 `remote_api_token`
- `owner_ids`：允许创建机器人的 QQ 号，必须填写
- `allowed_groups`：允许使用的群号，留空表示不限制群
- `triggers`：触发词，默认支持“登录”“扫码登录”“创建机器人”“机器人登录”

## 使用

在允许的 QQ 号里发送：

```text
登录
```

插件会回复“正在创建”，随后发送二维码图片。已登录的机器人不会重复要求扫码。
