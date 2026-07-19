# AstrBot-Deploy Web 控制台

这是 AstrBot-Deploy 的企业级 Web 管理面板，默认中文界面，目标是让用户像使用宝塔面板一样管理 AstrBot 与 NapCat。

## 功能

- 初始化部署向导：网页里填写 NapCat 数量和连接 Token，一键异步部署 AstrBot + NapCat。
- 仪表盘：AstrBot、NapCat、Docker、CPU、内存、磁盘、端口、最近操作。
- AstrBot 管理：启动、停止、重启、查看地址、账号、密码、Token、日志。
- NapCat 管理：实例列表、端口、Token、状态、新增、删除、启动、停止、重启、批量重启。
- 日志中心：AstrBot 日志、NapCat 日志、部署脚本日志、面板审计日志、关键词过滤、错误高亮。
- 文件中心：拖拽多文件上传、JSON 校验、列表、下载、删除、预览、格式化 JSON、应用为 AstrBot 配置。
- 备份恢复：一键备份、备份列表、下载、恢复指定备份。
- 更新中心：更新 AstrBot 镜像、NapCat 镜像、全部更新、异步任务进度。
- 系统设置：安装目录、Docker 网络名、默认 Token、登录账号密码、上传目录、危险操作、公网地址、主题色。

## 响应式适配

已按以下宽度设计：

- 桌面端：1920px、1440px、1366px，左侧固定导航 + 顶部状态栏 + 多列卡片。
- 平板端：768px、820px、1024px，左侧导航自动收为图标栏，两列卡片，表格横向滚动。
- 手机端：360px、375px、390px、414px、430px，底部 Tab、单列卡片、表格转卡片、弹窗底部吸附、触控按钮不低于 44px。

## systemd 启动

```bash
cd /opt/astrbot/AstrBot-Deploy
bash scripts/panel.sh setup
```

一键安装脚本默认也是先启动本面板：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Ceiity/linyu/main/install.sh)
```

打开面板后，在仪表盘点击“初始化部署向导”即可继续部署 AstrBot 和 NapCat。

查看状态：

```bash
bash scripts/panel.sh status
```

查看首次密码：

```bash
bash scripts/panel.sh password
```

配置文件：

```bash
/opt/astrbot/panel_config.json
```

## Docker 启动

```bash
cd /opt/astrbot/AstrBot-Deploy/panel
docker compose up -d --build
```

## 开发启动

```bash
cd /opt/astrbot/AstrBot-Deploy
python3 panel/backend/app.py --host 0.0.0.0 --port 7070
```

## 安全设计

- 首次启动自动生成账号密码并写入 `/opt/astrbot/panel_config.json`。
- 登录后使用签名 session cookie。
- 后端只暴露白名单动作，不允许前端传任意 shell 命令。
- 删除实例、删除文件、恢复备份等危险操作需要二次确认。
- 危险操作还需要在系统设置里开启。
- 所有操作写入 `/opt/astrbot/logs/panel-audit.log`。
- API 返回结构统一为 `ok/data/message/code/time/version`。
