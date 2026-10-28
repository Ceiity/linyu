# nailong

奶龙 AstrBot Manager

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Learn Flutter](https://docs.flutter.dev/get-started/learn-flutter)
- [Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Flutter learning resources](https://docs.flutter.dev/reference/learning-resources)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.

## 界面

| 欢迎 | 检测报告 | 部署中 | 首页 | QQ 登录 | 插件 | 日志 |
| --- | --- | --- | --- | --- | --- | --- |
| ![](app/test/goldens/01_welcome.png) | ![](app/test/goldens/02_report_fresh.png) | ![](app/test/goldens/04_deploying.png) | ![](app/test/goldens/06_dashboard.png) | ![](app/test/goldens/08_qq.png) | ![](app/test/goldens/09_plugins.png) | ![](app/test/goldens/10_logs.png) |

截图由 `SCREENSHOTS=1 flutter test test/screenshot_test.dart --update-goldens` 用真实页面代码生成。

## 测试情况

- Agent 单元/接口测试 11 项，安装器单元测试 15 项（部署决策 A–E、authorized_keys 注入防护、GPG 指纹等）。
- 端到端：用 App 的 Dart 代码通过真实 SSH，把一台**没有 Docker 的全新 Ubuntu 24.04（systemd）**从零部署完成（约 3 分钟），
  完成配对后验证：App 密钥无法执行命令、无法转发到其它端口；隧道内总览、插件、日志、WebSocket、备份/校验/下载均正常。
- 接管：在已有用户自行部署的 AstrBot + NapCat（自定义 OneBot Token）上运行，配置文件 SHA-256 前后一致、容器未重建、Token 未改。
