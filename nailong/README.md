# 奶龙 · Nailong AstrBot Manager

FlClash 风格的 Android 应用：填写服务器 SSH 信息，一键部署并管理 AstrBot + NapCat。

```
nailong/
├── app/          Flutter Android 应用（包名 com.nailong.astrbot）
├── installer/    服务器安装器（Python 标准库，App 通过 SSH 上传并校验后运行）
├── agent/        奶龙管理 Agent（Python FastAPI，仅监听 127.0.0.1）
├── tool/         打包脚本（把安装器 + Agent 打进 App 资源并生成 SHA-256）
└── docs/         部署文档、使用文档、安全设计
```

- [使用文档](docs/USAGE.md)
- [部署文档](docs/DEPLOY.md)（含构建 APK）
- [安全设计](docs/SECURITY.md)

## 工作原理

```
手机 App ──SSH(密码，仅首次)──▶ 服务器
   │  1. 核对主机指纹 → 上传安装包（SHA-256 校验）→ 环境检测 → 用户确认
   │  2. 安装 Docker（官方源 + GPG 指纹）→ 按摘要拉取镜像 → 部署 AstrBot / NapCat
   │  3. 配置 OneBot v11（随机 Token）→ 部署 Agent（127.0.0.1）→ 一次性配对码
   │  4. 生成本机 Ed25519 密钥，写入受限 authorized_keys（只能转发到 Agent 端口，不能执行命令）
   ▼
以后：App ──SSH(本机密钥)──隧道──▶ 127.0.0.1:Agent ──▶ Docker / AstrBot / NapCat
```

## 固定版本

| 组件 | 版本 | 摘要 |
| --- | --- | --- |
| AstrBot | `soulter/astrbot:v4.29.3` | `sha256:c93a6d19…` |
| NapCat | `mlikiowa/napcat-docker:v4.18.41` | `sha256:b101b896…` |
| Agent 运行时 | `python:3.12-slim-bookworm` | `sha256:62ed8e07…` |

完整摘要见 `installer/nailong_installer.py` 中的 `IMAGES`。升级版本时同时更新标签与摘要。
