# AstrBot-Deploy

## 项目简介

AstrBot-Deploy 是一个面向中文用户的 AstrBot + NapCat Docker 一键部署项目。

在一台全新的 Debian / Ubuntu 服务器上，用户只需要执行一条命令，就可以自动完成 Docker 安装、AstrBot 部署、NapCat 多实例部署、端口分配、Docker Network 配置、健康检查和登录信息保存。

项目地址：https://github.com/Ceiity/linyu

## 一键安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Ceiity/linyu/main/install.sh)
```

默认流程是“面板优先”：

1. 自动安装 Docker、Docker Compose、Git、Curl 等依赖。
2. 自动创建安装目录和 Docker Network。
3. 自动启动 Web 控制台。
4. 用户打开网页，在仪表盘里填写 NapCat 数量和连接 Token。
5. 点击“开始自动部署”，面板异步完成 AstrBot + NapCat 部署。

这样小白用户不用在终端里回答一堆问题。

如果你仍然想使用旧版终端全自动部署，可以执行：

```bash
ASTRBOT_DEPLOY_MODE=full NAPCAT_COUNT=1 bash <(curl -fsSL https://raw.githubusercontent.com/Ceiity/linyu/main/install.sh)
```

如果 GitHub Raw 访问较慢，可以先克隆仓库后本地安装：

```bash
git clone https://github.com/Ceiity/linyu.git AstrBot-Deploy
cd AstrBot-Deploy
sudo bash install.sh
```

## 功能特性

- 自动检测 root 权限
- 自动检测 Debian / Ubuntu 系统
- 自动检测 CPU 架构
- 自动检测网络
- 自动安装 Docker 和 Docker Compose
- 自动安装 Git、Curl、Wget 等依赖
- 自动创建 Docker Network
- 自动部署 AstrBot
- 支持任意数量 NapCat 实例
- 每个 NapCat 独立容器、独立配置、独立日志、独立数据
- 自动分配可用端口，避免端口冲突
- 自动生成 NapCat WebUI Token
- 自动生成企业级 Web 控制台，支持电脑、平板、手机
- 自动生成部署信息文件
- 支持备份、恢复、更新、卸载
- 提供中文管理菜单

## 官方依据

本项目默认配置以官方文档和官方仓库为准：

- AstrBot 官方 Docker 镜像：`soulter/astrbot:latest`
- AstrBot WebUI 端口：`6185`
- AstrBot OneBot / NapCat WebSocket 端口：`6199`
- AstrBot 数据目录：`/AstrBot/data`
- NapCat Docker 镜像：`mlikiowa/napcat-docker:latest`
- NapCat WebUI 端口：`6099`
- NapCat 配置目录：`/app/napcat/config`
- NapCat QQ 数据目录：`/app/.config/QQ`
- NapCat 支持 `MODE=astrbot`

## NapCat 多实例

安装时会询问 NapCat 数量，例如输入 `20` 会自动创建：

```text
napcat01
napcat02
...
napcat20
```

每个实例都会生成独立目录和独立 Compose 文件。

## 企业级 Web 控制台

安装完成后会自动启用中文 Web 控制台，界面按高级 SaaS 管理后台设计，手机、电脑、平板都可以直接打开使用。

控制台能力：

- 仪表盘：AstrBot、NapCat、Docker、CPU、内存、磁盘、端口、最近操作
- AstrBot 管理：启动、停止、重启、查看 WebUI、账号、密码、Token、日志
- NapCat 管理：实例列表、新增、删除、启动、停止、重启、批量重启
- 日志中心：部署日志、容器日志、关键词过滤、错误高亮
- 文件中心：拖拽上传、多文件上传、JSON 校验、预览、下载、删除、应用配置
- 备份恢复：一键备份、备份列表、下载备份、恢复备份
- 更新中心：更新 AstrBot、更新 NapCat、更新全部
- 系统设置：安装目录、Docker 网络、默认 Token、账号密码、上传目录、危险操作
- HTTPS：支持 Nginx + Certbot + Let's Encrypt 自动申请证书
- 查看所有 NapCat WebUI 地址和 Token
- 一键新增 NapCat，输入几个就创建几个

控制台地址、账号和首次密码会写入：

```bash
/opt/astrbot/deploy_info.txt
```

也可以在服务器执行：

```bash
cd /opt/astrbot/AstrBot-Deploy
bash scripts/panel.sh setup
```

重新生成或启动 Web 控制台。

## HTTPS / Let's Encrypt

如果你有自己的域名，可以在 Web 控制台的「系统设置」里配置 HTTPS。

前提：

- 域名 A 记录已经解析到服务器公网 IP。
- 云服务器安全组开放 `80` 和 `443`。
- 服务器本机没有其它服务占用 Nginx 的 `80/443`。

也可以命令行执行：

```bash
cd /opt/astrbot/AstrBot-Deploy
HTTPS_DOMAIN=panel.example.com HTTPS_EMAIL=admin@example.com bash scripts/https.sh
```

脚本会自动安装 Nginx、Certbot，配置反向代理到 Web 控制台，并申请 Let's Encrypt 证书。

详细说明见：

```bash
panel/README.md
```

## 目录说明

| 路径 | 说明 |
| --- | --- |
| `/opt/astrbot/data` | AstrBot 数据目录 |
| `/opt/astrbot/napcat/napcatXX` | NapCat 实例目录 |
| `/opt/astrbot/compose/astrbot/docker-compose.yml` | AstrBot Compose 文件 |
| `/opt/astrbot/napcat/napcatXX/docker-compose.yml` | NapCat Compose 文件 |
| `/opt/astrbot/backups` | 备份目录 |
| `/opt/astrbot/logs` | 脚本日志目录 |
| `/opt/astrbot/deploy_info.txt` | 部署信息、端口、密码和 Token |
| `/opt/astrbot/.env` | 部署状态、端口、镜像和 Docker 网络信息 |
| `/opt/astrbot/panel_config.json` | Web 控制台账号、密码哈希、上传目录等配置 |
| `/opt/astrbot/uploads` | Web 控制台默认上传目录 |
| `/opt/astrbot/logs/panel-audit.log` | Web 控制台审计日志 |

## 管理菜单

```bash
sudo bash /opt/astrbot/AstrBot-Deploy/manager.sh
```

支持查看部署信息、更新、新增 NapCat、删除 NapCat、查看日志、重启、停止、启动、备份、恢复、健康检查和卸载。

## 备份与恢复

```bash
sudo bash /opt/astrbot/AstrBot-Deploy/backup.sh
sudo bash /opt/astrbot/AstrBot-Deploy/restore.sh /opt/astrbot/backups/astrbot_backup_YYYYmmdd_HHMMSS.tar.gz
```

## 卸载

```bash
sudo bash /opt/astrbot/AstrBot-Deploy/uninstall.sh
```

卸载时可选择保留数据或完全删除数据。

## 登录信息

部署完成后，终端会显示 AstrBot 地址、用户名、初始随机密码和 NapCat WebUI Token，同时写入：

```text
/opt/astrbot/deploy_info.txt
```

AstrBot Token：当前已查阅的官方文档没有公开稳定的首次自动获取 Token 接口，本项目不会伪造 Token，仅保留扩展接口。

## WebSocket 配置

所有容器加入同一个 Docker Network：`astrbot_network`。NapCat 默认使用反向 WebSocket 连接：

```text
ws://astrbot:6199/ws
```

## 常见问题

### 端口冲突怎么办？

脚本会自动从官方默认端口开始查找可用端口，不会固定写死。

### 如何查看密码？

```bash
sudo cat /opt/astrbot/deploy_info.txt
```

### 如何查看日志？

```bash
sudo docker logs astrbot --tail 200
sudo docker logs napcat01 --tail 200
```

## 开发检查

```bash
bash -n install.sh manager.sh update.sh backup.sh restore.sh uninstall.sh scripts/*.sh lib/*.sh
bash scripts/validate.sh
```

## 许可证

MIT License

## Web 面板新增能力

- AstrBot 插件上传：进入「文件中心」上传 `.zip` 插件包，上传完成后点击「安装为 AstrBot 插件」，面板会自动解压到 `/opt/astrbot/data/plugins` 并重启 AstrBot 让插件生效。
- 插件列表：进入「AstrBot」页面可查看当前插件目录和已安装插件。
- NapCat 掉线自动守护：安装面板时会自动启用 `astrbot-napcat-watchdog.service`，检测到机器人容器停止、QQ 被踢下线、登录过期、二维码过期等日志关键词时，会自动重启对应机器人容器。
- 系统设置：可调整 AstrBot 插件目录，并可手动启动或重启掉线自动守护。
- NapCat 扫码登录入口：机器人列表每个实例旁边都有「扫码登录」按钮，点击后会在面板弹窗内打开对应 NapCat WebUI，并自动带入 Token；如果浏览器限制内嵌页面，也可以点「新窗口打开扫码登录」。
