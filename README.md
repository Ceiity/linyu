# AstrBot-Deploy

## 项目简介

AstrBot-Deploy 是一个面向中文用户的 AstrBot + NapCat Docker 一键部署项目。

在一台全新的 Debian / Ubuntu 服务器上，用户只需要执行一条命令，就可以自动完成 Docker 安装、AstrBot 部署、NapCat 多实例部署、端口分配、Docker Network 配置、健康检查和登录信息保存。

项目地址：https://github.com/Ceiity/linyu

## 一键安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Ceiity/linyu/main/install.sh)
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
| `/opt/astrbot/.env` | 部署状态文件 |

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
