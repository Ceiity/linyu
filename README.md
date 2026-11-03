# 奶龙 · AstrBot-Deploy

## 项目简介

奶龙（AstrBot-Deploy）是一个面向中文用户的 AstrBot + NapCat Docker 一键部署项目，自带「奶龙控制台」Web 面板。

在一台全新的 Debian / Ubuntu 服务器上，用户只需要执行一条命令，就可以自动完成 Docker 安装、AstrBot 部署、NapCat 多实例部署、端口分配、Docker Network 配置、健康检查和登录信息保存。

项目地址：https://github.com/Ceiity/linyu

## 一键安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Ceiity/linyu/main/install.sh)
```

默认流程是“面板优先”：

1. 自动安装 Docker、Docker Compose、Git、Curl、Fail2Ban 等依赖。
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
- 自动安装 Docker 和 Docker Compose；优先安装 v2（兼容 Docker CE 的 `docker-compose-plugin` 与 Ubuntu 的 `docker-compose-v2`），只有 v2 不可用时才回退独立版
- 自动安装 Git、Curl、Wget 等依赖
- 自动创建 Docker Network
- 自动部署 AstrBot，并映射 `8686:8686`（TCP）
- 部署 AstrBot 时自动为已有 UFW / 运行中的 firewalld 添加 TCP 8686 放行规则，不启用原本关闭的防火墙
- 支持任意数量 NapCat 实例
- 每个 NapCat 独立容器、独立配置、独立日志、独立数据
- 自动分配可用端口，避免端口冲突
- 自动生成 NapCat WebUI Token
- 自动生成企业级 Web 控制台，支持电脑、平板、手机
- 自动生成部署信息文件
- 支持备份、恢复、更新、卸载
- 提供中文管理菜单

## 在线镜像源发现与自动优选

一键安装自动加载项目维护的在线候选清单 `config/mirrors.json`（APT、PyPI、GitHub、Docker）；
Docker 还会从 [dongyubin/DockerHub 的有效源表格](https://github.com/dongyubin/DockerHub)补充候选，忽略已失效段落及明确标注需登录、会员或仅内网的条目。
不是扫描所有网站，也不保证任何公益源永久可用。下载清单失败自动保留缓存、本地清单和内置候选。

- 从实际部署服务器发起响应耗时测试（不是持续下载带宽测试），官方源也参与选择。
- 默认每类最多 32 个候选、8 个并发；单次测速 6 秒超时。在线清单最多 1 MiB，24 小时缓存。
- Docker `/v2/` 除了检查 200 / 401，还要求 Registry V2 协议响应头，避免误选返回网页的失效代理。
- 按响应耗时保留前三个 Docker 加速源；镜像名不改，由 Docker 自身处理镜像源与官方回退。接口探测成功不代表该源一定缓存了 AstrBot / NapCat，最终以实际拉取结果为准。
- 配置相同时不重启 Docker；配置变化前生成带时间的备份，原子写入并回读验证；验证或重启失败时自动还原。JSON 已损坏时保留原文件，不覆盖。
- 无论自动发现成功与否，都保留 `NAILONG_MIRROR=off` 和手动指定源的开关。
- 首次引导克隆仍使用内置 GitHub 路由，下载完整项目后才运行在线清单发现；私有仓库引导不向公共代理发送 Token。

可选环境变量（普通一键安装无需填写）：

| 变量 | 默认值 / 用途 |
| --- | --- |
| `MIRROR_DISCOVERY` | `auto`；`off` 只使用本地和内置候选 |
| `MIRROR_CATALOG_URLS` | 本仓库 main 的 `config/mirrors.json` Raw URL；可用空格/逗号指定最多 3 个兼容 HTTPS JSON 清单 |
| `DOCKER_MIRROR_LIST_URL` | dongyubin/DockerHub main 的 README Raw URL；空值关闭此额外来源 |
| `MIRROR_CACHE_TTL` | `86400` 秒 |
| `MIRROR_DISCOVERY_TIMEOUT` | `4` 秒，限制在 1–15 秒 |
| `MIRROR_MAX_CANDIDATES` | `32`，最多 64 |
| `MIRROR_CONCURRENCY` | `8`，最多 16 |
| `MIRROR_PROBE_TIMEOUT` | `6` 秒 |
| `APT_MIRROR` / `PIP_INDEX_URL` / `GH_PROXY` / `DOCKER_MIRRORS` | 手动设置时优先，不自动替换所指定类别 |

离线清单也在 `config/mirrors.json`，版本字段为 `"version": 1`，四类候选为 HTTPS URL 数组。
自动下载的内容只解析为数据，不作为脚本执行。候选不接受账号密码、IP 字面量或内网域名。

Docker 配置备份形如 `/etc/docker/daemon.json.nailong-日期时间-编号.bak`，部署日志记录本次备份路径。
手动还原：`cp -a /日志中的具体备份路径 /etc/docker/daemon.json && systemctl restart docker`。
若日志中 snapshot 为 `-`，表示原本没有该文件，撤回时删除此次新建的 `/etc/docker/daemon.json` 后重启 Docker。

## AstrBot TCP 8686

终端全自动部署和网页「初始化部署」都会在生成的
`/opt/astrbot/compose/astrbot/docker-compose.yml` 中加入 `"8686:8686"`，
然后使用 Compose `up -d` 应用配置；原有 `/AstrBot/data` 挂载保持不变。
已有 UFW 会执行 `ufw allow 8686/tcp`；运行中的 firewalld 会添加永久和运行时规则。
重复部署不会重复添加端口映射，规则配置失败会在部署日志中明确提示。
没有 UFW / 运行中的 firewalld 时只记录日志，不安装或启用新防火墙，也不改动其它防火墙规则。
8686 是固定映射，不会自动换端口；容器内服务仍需实际监听 `0.0.0.0:8686`。
云安全组不由本脚本修改；按本项目部署约定，雨云控制台的规则由用户自行管理。
仅更新镜像不会重写旧 Compose；旧部署需要重新生成部署配置后才会增加此映射。

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
- 一键配置连接：自动同步 AstrBot 免 @ / 免前缀、速率限制、NapCat 反向 WebSocket、Token 和 Docker 网络，并重启需要刷新的服务
- NapCat 删除后再次新增会优先复用空出来的编号和端口，例如删除 `napcat02` 后新增会重新创建 `napcat02`
- Web 控制台支持浏览器会话缓存，切换页面不会反复闪烁刷新；点击“刷新”按钮才强制刷新最新状态
- 主题支持“跟随系统 / 浅色 / 深色”，手机端打开侧边栏后可在左下角切换
- 登录响应不再返回 session token，敏感会话只通过 HttpOnly Cookie 保存
- 登录响应、`/api/me`、`/api/settings` 不再返回面板真实用户名，避免被抓包后辅助爆破
- `/api/me`、`/api/settings`、任务日志、NapCat 列表会自动脱敏用户名、密码、哈希、密钥和 Token
- 登录爆破防护：同一 IP 10 分钟内连续失败 5 次后锁定 30 分钟，返回 `429 RATE_LIMIT`
- 登录校验使用统一错误提示，并对错误用户名执行虚拟密码哈希校验，减少通过响应时间枚举用户名的风险

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

如果机器人部署完成后群聊暂时不响应，或 NapCat 网络连接需要“重新开关”才生效，可以在 Web 控制台点击：

```text
AstrBot 页面 -> 一键配置
或
机器人管理页面 -> 一键配置
```

也可以在服务器终端执行：

```bash
sudo bash /opt/astrbot/AstrBot-Deploy/scripts/onekey-config.sh
```

该操作会自动应用：

- 群聊免 @、免前缀唤醒
- `wake_prefix=[""]`
- `provider_settings.wake_prefix=""`
- `platform_settings.reply_prefix=""`
- 消息速率限制时间：`0`
- 消息速率限制计数：`9999999999`
- NapCat 反向 WebSocket Token
- Docker Network 自动连接
- AstrBot 与 NapCat 必要重启

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


## 项目商标

Web 控制台内置“奶龙” SVG 商标，文件位置：`panel/static/nailong-robot.svg`。它会自动用于登录页、侧边栏品牌区和浏览器图标，造型是一只圆滚滚的黄色小龙，深色圆角底，适合浅色/深色模式和手机端显示。

## v2.6.0 更新说明（扫码登录修复、安装加速）

**扫码登录（对照 NapCat 官方源码重写）**
- 修复获取二维码总是「服务器内部错误」：服务器缺少 Python 二维码库、NapCat 容器刚启动还没生成二维码、WebUI 端口暂时连不上、密钥不匹配或登录限速时，原来都会变成 500。现在二维码由浏览器直接绘制（内置 MIT 协议的 qrcode-generator），不再依赖服务器装库；NapCat 还没生成二维码时会主动让它生成并等待；其余情况都显示具体原因。
- 按 NapCat 的登录阶段显示：等待扫码 → 已扫码，请在手机上确认 → 手机已确认，正在启动 QQ → 登录成功。
- 手机上点了取消会提示「手机上取消了登录，已换新二维码」；被腾讯拒绝时显示原因和错误码（如「当前网络环境不安全（错误码 140022013）」）；二维码过期由 NapCat 判定并提示刷新；NapCat 正在重连登录服务时显示等待。
- NapCat 自动换新二维码时页面同步更新，不用手动刷新。
- QQ 群「申请登录」插件同样会回复「已扫码，请在手机上确认」以及失败原因和错误码。

**一键安装加速（自动测速）**
- apt、Docker 镜像、PyPI、GitHub 每一类下载源都会同时测速官方源和国内镜像（阿里云、清华、中科大、腾讯云、华为云，Docker Hub 加速站，GitHub 加速代理），自动选最快的；海外服务器官方源更快时保持不变。
- apt 源只在新镜像明显更快时才替换，原文件备份为 `*.nailong.bak`；Docker 只在 Docker Hub 直连慢或不通时写入 `registry-mirrors`（保留 daemon.json 原有配置）；Docker 官方安装脚本在国内走阿里云源。
- 安装引导脚本按测速结果选择 GitHub 直连或加速代理，并浅克隆（`--depth 1`），不再卡在 57%。
- 面板 Python 依赖优先用系统包（python3-qrcode / python3-pil / python3-cryptography），装不上再用测速后的 PyPI 镜像。
- 镜像拉取超时由 120 秒放宽到 600 秒。
- 环境变量：`NAILONG_MIRROR=off` 关闭全部换源；`APT_MIRROR`、`PIP_INDEX_URL`、`GH_PROXY`、`DOCKER_MIRRORS` 可手动指定。

**其他**
- 电脑大屏放大幅度调小：1600px 起 4%，1880px 起 8%，2300px 起 12%，3000px 起 20%。

## v2.5.4 更新说明（大屏放大）

- 电脑大屏整体放大：窗口宽 1600px 起放大 8%，1880px 起 15%，2300px 起 25%，3000px 起 40%（文字、按钮、卡片、图标等比放大）。只对鼠标操作的屏幕生效，手机和平板保持原样。
- 放大后侧栏高度、选中指示条、弹窗位置都按比例校正，不会出现滚动条或错位。

## v2.5.3 更新说明（电脑宽屏）

- 修复电脑宽屏（1920 / 2560 等）内容只占左侧、右侧大片留白：内容随窗口铺满，两侧边距随屏幕宽度在 32–56px 之间自适应，标题栏与内容对齐；机器人卡片自动增加列数，系统设置在宽屏下两组并排，标签和输入框不会隔开整个屏幕。
- 容器日志不再显示 `[32m` 之类的乱码：ANSI 颜色转成真正的颜色（时间绿色、INFO 加粗、错误红色），浅色 / 深色都可读。
- AstrBot 页按钮「免@免前缀」改为「免 @ · 免前缀」。
- 系统设置里的数字项（最大上传、守护间隔等）去掉浏览器自带的方框上下箭头，改为圆角「− 数值 +」步进器，点按即标记未保存。

## v2.5.2 更新说明（扫码登录）

- 扫码窗口只保留一个「刷新二维码」按钮，去掉 WebUI 链接、关闭叉和取消按钮（点空白处或 Esc 关闭）。
- 顶部三步进度：获取二维码 → 手机确认 → 登录成功，当前步骤高亮。
- 状态清晰：加载骨架 → 显示二维码（呼吸点「等待扫码」）→ 过期或获取失败时二维码模糊并提示，刷新按钮轻跳提醒 → 刷新中模糊+转圈。
- 登录成功动效：二维码收缩淡出，绿色圆弹出，对勾描绘，外圈扩散，标题和 QQ 昵称/号码依次浮现，约 1.9 秒后自动关闭并刷新列表。
- 轮询改为上一次请求结束后 2 秒再查，不再叠加请求；关闭或重新打开窗口后旧轮询不会再写入；二维码约 110 秒自动判为过期。状态查询不再每次写审计日志。

## v2.5.1 更新说明（实时刷新修复）

- 修复上传文件后要等好几秒（最长 2 分钟缓存）才显示：上传完成立即插入列表并刷新统计，同名文件可连续重复上传，显示上传百分比与「服务器保存中」。
- 删除文件即时从列表移除，失败自动恢复；批量删除改为并行。手机端文件行新增「更多」面板（预览 / 复制外链 / 下载 / 删除），之前手机上无法单个删除或下载。
- 修复删除机器人后卡片先消失又「复活」几秒：过期的后台请求不再覆盖新数据，删除中的机器人不会被重新画出来。
- 修复创建 / 删除机器人时关掉进度弹窗后列表不再更新：任务完成后无论弹窗是否打开都会自动刷新当前页面并提示结果，失败自动打开日志。
- 创建机器人时列表里出现「创建中」占位卡片，显示实时进度；机器人页和机器人池只在数据变化时局部更新，不再每 1.8 秒整页重绘导致按钮点不中。
- 启动 / 停止 / 重启单个机器人不再锁住全局，其他机器人可同时操作；按钮里抛出的错误现在都会弹出提示，不会静默失败。

## v2.5.0 更新说明（公网地区、机器人卡片、iOS 适配）

- 仪表盘状态卡改为显示「公网地区」（省份 · 城市 + 国家代码 + 运营商），由服务器公网 IP 自动定位，不再在页面上显示公网 IP。定位在后台进行，不拖慢仪表盘；查询失败 10 分钟后重试，内网地址直接跳过。
- 机器人页重做：顶部数量步进器（− 1 +）+ 创建按钮，常用操作排成一行；机器人改为电脑与手机通用的卡片网格，统一 16px 内边距与 12/14px 间距，每张卡片含编号头像、状态、恢复状态、端口，底部「扫码登录 / WebUI / 更多」。后台刷新时不再重置已选的新增数量。
- 机器人池重做：总数 + 分布条 + 五态图例（已登录 / 待扫码 / 空闲 / 需处理 / 已停止），下方沿用同一套机器人卡片，显示登录账号或申请人与剩余占用时间。
- iOS Safari 适配：手机输入框统一 16px，避免点输入框时页面被放大；悬停效果只在有鼠标的设备上生效，触屏点按后不再残留高亮；新增主屏幕图标（apple-touch-icon）、全屏 Web App 与状态栏配置，地址栏颜色与页面背景一致。

## v2.4.0 更新说明（细节打磨）

- 提示消息改为顶部堆叠通知：从上方落下，可左右滑动关闭，错误为红色；相同内容不重复弹出，手机最多同时 2 条、电脑 4 条。
- 确认类对话框改为 iOS 风格弹窗：宽 348、圆角 34，从 1.2 倍收缩落定，只淡出；底部两个并排胶囊按钮，危险操作为红字。
- 手机端机器人卡片只保留「扫码登录」和「更多」，其余操作（打开 WebUI、启动、重启、停止、日志、删除）放进底部操作面板。
- 系统设置改为分组列表：基础 / 掉线自动恢复 / QQ 远程登录 / 外观与安全，开关类设置直接用开关，底部悬浮玻璃保存条并提示未保存修改。
- 侧栏选中条改为「尺蠖式」伸缩动画，行高与选中底色对齐 FlClash。
- 空状态带图标，骨架屏节奏放慢，卡片标题采用苹果字号体系。

## v2.3.0 更新说明（液态玻璃与动效）

- 手机底部导航改为液态玻璃浮动条：按下时选中的镜片抬起并放大下方图标，按住可左右滑动，镜片跟手并随速度果冻形变，经过的图标逐个染色，松手按惯性吸附到目标页并带回弹；触点有光晕，越界有橡皮筋阻尼。
- 全局弹性按压：按钮、可点卡片、列表项按下时膨胀、随手指轻微拉扯，松开回弹。
- 开关按住时滑块放大越出轨道，拨动途中拉伸；主题模式改为 M3 Expressive 连体按钮组，选中项变为整颗胶囊。
- 页面动效：底部标签之间淡入并让卡片依次浮现，「工具」里的子页面从右侧推入、返回时从左侧滑回。
- 配色与形状对齐 FlClash：默认主题色改为 iOS 蓝 `#007AFF`（仍可在设置里改），暖色中性底色，卡片三层柔和阴影，圆角 32/34，支持的浏览器使用超椭圆圆角。
- 修复：确认框关闭后立刻弹出的下一个对话框会被吞掉并可能锁住页面滚动；退出登录后后台仍每隔几秒轮询接口；登录页按回车不能提交、可重复点击提交；对话框不能用 Esc 或点击空白处关闭；卡片内复制按钮在灰色块里变形。

## v2.2.0 更新说明（新界面）

- 控制台界面整体重做，参考 FlClash 的 Material 3 风格：浅灰侧栏 + 胶囊高亮、大号页面标题、圆角卡片网格、分段按钮、开关、迷你折线图，深色模式为暖色调。
- 仪表盘重新排版：状态卡（公网 IP、Docker、机器人运行数，右侧圆齿形按钮直接启停 AstrBot）、CPU 负载 / 内存实时曲线（后端每 10 秒采样，打开即有最近 5 分钟数据）、主题模式分段切换、「掉线自动恢复」「QQ 远程登录」一键开关、内网 IP、机器人运行率波浪进度条、服务状态、磁盘占用、容器 / 最近操作 / 端口占用标签页、机器人列表。
- 手机端按 FlClash 手机版重做：大标题 + 圆形按钮顶栏、4 栏底部导航（仪表盘 / 机器人 / 机器人池 / 工具），其余页面收进「工具」页，子页面顶栏带返回键；仪表盘的 CPU / 内存合并为「资源占用」卡，两个开关卡带花瓣形图标；对话框从底部弹出。平板宽度自动收起为图标侧栏。
- 样式表重写，体积从 115KB 降到 62KB，`!important` 从 900 多处降到 27 处。
- 修复：自动刷新时整页反复淡入闪烁、日志页下拉框初始为空、首次打开登录页误报「登录已失效」、备份列表分隔符乱码、最近操作记录显示成一整段 JSON。

## v2.1.0 更新说明（淋雨 → 奶龙）

- 品牌统一改名为「奶龙」：控制台标题、Logo、QQ 远程登录插件（`astrbot_plugin_nailong_remote_admin`）。
- 平滑升级：面板启动时自动把 `panel_config.json` 里的 `linyu_remote_*` 配置迁移为 `nailong_remote_*`，并把已安装的旧插件 `astrbot_plugin_linyu_remote_admin` 替换为新插件（会重启一次 AstrBot）。旧环境变量 `LINYU_REMOTE_*` 仍然兼容。
- 新安装的面板默认账号为 `nailong`；已有面板账号不变。
- 兼容 Python 3.13（Debian 13 / Ubuntu 25.04）：移除已被删除的 `cgi` 模块，上传改为流式写盘，不再整文件读进内存。
- 性能：面板配置按文件变化缓存，不再每次请求重复计算密码哈希；日志实时推送多人共享同一次读取。
- 下载：备份、文件中心、服务器文件下载改为流式传输，支持断点续传（Range）。
- 安全：Nginx 反代后登录限流按真实 IP 计算，不再出现一个人输错密码把所有人锁住；伪造的 `X-Forwarded-For` 不再被信任；NapCat 内部 OneBot WS/HTTP 端口只绑定 `127.0.0.1`。
- 稳定性：配置文件、登录分配表加锁；机器人创建/删除串行执行，避免端口和索引冲突；任务列表和缓存有上限。
- 机器人池在线状态改为通过 NapCat WebUI 判断，结果更准确。
- 修复若干乱码提示和错误文案；安装完成提示的面板账号与实际一致。
- 新增 GitHub Actions：Python 3.12 / 3.13 下跑语法检查、pyflakes、单元测试和安全回归测试。

## 企业级维护能力

### 动态 HTTPS / 反向代理地址

Web 控制台不会写死 IP、域名或 localhost。后端会根据当前请求自动识别访问地址，优先使用标准代理头：

- `Host`
- `Forwarded`
- `X-Forwarded-Proto`
- `X-Forwarded-Host`
- `X-Forwarded-Port`
- `X-Forwarded-Ssl`
- `CF-Visitor`

因此同一套代码可以同时兼容 IP 访问、域名访问、HTTP、HTTPS、Nginx、Caddy 和 Cloudflare Proxy。用户后续绑定域名后，通常无需修改代码。

### NapCat 自动恢复

`astrbot-napcat-watchdog.service` 是统一调度的后台守护服务，用于检测所有 NapCat 机器人实例，不会为每个机器人创建一个死循环线程。

综合检测内容包括：

- Docker 容器状态
- NapCat WebUI 可达性
- NapCat WebUI 登录状态 API
- QQ 是否在线
- 最近日志中的踢下线、二维码过期、登录过期等异常关键词

连续异常达到阈值后，守护服务会自动重启对应 NapCat 容器，等待恢复并请求新的二维码。默认 10 分钟最多恢复 3 次，超过次数会暂停自动恢复并在日志和面板中提示需要人工处理。

可在「系统设置」中配置：

- 是否开启自动恢复
- 检测间隔：30 / 60 / 120 / 300 秒或自定义
- 连续异常次数
- 最大恢复次数
- 恢复统计窗口
- 恢复等待时间

### 统一端口管理

新增统一端口状态文件：

```bash
/opt/astrbot/ports.json
```

创建机器人时会综合检查系统监听端口、Docker 已映射端口、NapCat 索引文件和端口状态文件，自动分配 WebUI、HTTP、WebSocket、AstrBot 反向 WebSocket 相关端口。删除机器人后端口会自动释放，避免机器人越来越多时端口管理混乱。

### 实时日志

日志中心使用 SSE 长连接实时推送新增日志，支持自动滚动、暂停滚动、关键词过滤、错误高亮、断线重连和全屏查看，不再依赖疯狂轮询。


## QQ 内创建扫码机器人

项目内置 AstrBot 插件：`plugins/astrbot_plugin_nailong_remote_admin`。

部署时会自动复制到 AstrBot 插件目录。配置好主人 QQ 后，你可以在 QQ 私聊或群聊里直接发送：

```text
登录
```

插件会调用 Web 面板远程 API，自动创建一个 NapCat 机器人，并把扫码登录二维码发回聊天窗口。

安全设计：

- Web 面板远程 API 使用独立 `remote_api_token` 鉴权，不使用网页登录态。
- 插件默认必须配置 `owner_ids`，没有配置主人 QQ 时不会允许陌生人创建机器人。
- 一键部署会自动安装并启用 Fail2Ban，默认开启 `sshd` jail：10 分钟内 SSH 失败 5 次封禁 1 小时。
- 远程创建接口有速率限制，防止被刷实例。
- 面板 API 不会把 NapCat Token 暴露给网页列表或普通登录响应。

插件配置文件位置：

```bash
/opt/astrbot/data/config/astrbot_plugin_nailong_remote_admin_config.json
```

如果 AstrBot 在 Docker 容器里运行，`server_url` 不要写 `127.0.0.1`，建议写宿主机内网地址，例如：

```text
http://服务器内网IP:7070
```
