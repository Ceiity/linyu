# 淋雨 · 手机端

AstrBot-Deploy Web 面板的 Flutter 客户端（Android / iOS），界面风格参考 [FlClash](https://github.com/chen08209/FlClash)：Material 3、卡片式仪表盘、底部导航、主题色 / 深色 / 纯黑 / 跟随壁纸取色。

## 使用

1. 打开 App，输入服务器 IP（如 `1.2.3.4`）。
   - 只填 IP：自动探测 `7070`，占用时顺延 `7071-7079`。
   - 也支持 `IP:端口`、`http://IP:端口`、`https://域名`。
2. 输入面板账号密码登录（见服务器 `/opt/astrbot/deploy_info.txt`）。
3. 多台服务器会保存在首页，点一下直接进入。

服务器安全组需放行面板端口（默认 `7070`）。

## 功能

| 页面 | 内容 |
| --- | --- |
| 仪表盘 | AstrBot / 机器人 / Docker / 负载、资源趋势图、CPU 内存磁盘、网络、最近操作、容器列表；右下角按钮启停 AstrBot；未部署时显示一键部署向导 |
| 机器人 | 机器人池卡片（已登录 / 空闲 / 待扫码 / 需处理 / 已停止筛选）、扫码登录 QQ、启动 / 停止 / 重启 / 删除、新增、重启全部、清理空闲、一键配置连接 |
| 日志 | AstrBot、部署脚本、面板审计、各机器人日志，实时刷新、关键词过滤、错误高亮 |
| 工具 | AstrBot 详情与免 @ 配置、任务记录、备份恢复、更新中心、面板设置、修改密码、主题、切换服务器 |

## 安全

- 登录与网页一致：先取 `/api/login/challenge`，用 RSA-OAEP(SHA-256) 包裹 AES-256-GCM 密钥加密账号密码。
- 会话 Token 存在系统安全存储（Android Keystore / iOS Keychain），只以 Cookie 发送给该服务器。
- 面板为 HTTP 时流量明文，建议在「系统设置」配置 HTTPS 后用 `https://域名` 连接。

## 构建

```bash
cd mobile
flutter pub get
flutter test
flutter build apk --release --split-per-abi   # 产物在 build/app/outputs/flutter-apk/
```

正式签名：在 `android/key.properties` 写入 `storeFile`、`storePassword`、`keyAlias`、`keyPassword`（已在 .gitignore），否则使用 debug 签名。

GitHub Actions（`.github/workflows/mobile.yml`）在改动 `mobile/` 时自动构建 APK；推送 `app-v*` 标签会发布到 Release。配置仓库 Secrets `ANDROID_KEYSTORE_BASE64`、`ANDROID_KEYSTORE_PASSWORD`、`ANDROID_KEY_ALIAS`、`ANDROID_KEY_PASSWORD` 后使用正式签名。

联调真实面板：

```bash
PANEL_URL=http://127.0.0.1:7070 PANEL_USER=linyu PANEL_PASS=xxx flutter test test/panel_live_test.dart
```
