# 奶龙 QQ Bot Manager · Next Generation 2.0

面板版本 `3.0.0`，NG 模块版本 `2.0.0`。本文是本次升级的完整说明：现状分析、新架构、SnowLuma 集成、协议端切换、统一扫码登录、错误码、部署 / 升级 / 排障，以及测试结果。

---

## 1. 第一阶段：现有项目分析

### 1.1 当前架构

```
浏览器 ──HTTPS/HTTP──▶ 奶龙面板 (panel/backend/app.py, ThreadingHTTPServer, systemd 或 Docker)
                          │  调用 bash lib/*.sh（白名单动作）与 docker CLI
                          ▼
                 Docker 网络 astrbot_network
     ┌──────────────┬───────────────────────────┐
     │ astrbot      │ napcat01 … napcatNN       │
     │ soulter/     │ mlikiowa/napcat-docker    │
     │ astrbot      │ WebUI :6099 (公网映射)     │
     │ 6185 WebUI   │ 3000/3001 仅 127.0.0.1     │
     │ 6199+N-1 反向 WS 服务端 ◀── OneBot v11 反向 WS 客户端 ws://astrbot:<port>/ws
     └──────────────┴───────────────────────────┘
```

* **AstrBot**：`lib/astrbot.sh` 生成 `/opt/astrbot/compose/astrbot/docker-compose.yml`；数据在 `/opt/astrbot/data`。`sync_astrbot_platforms` 按 `napcat_index.tsv` 为每个实例写一个 `aiocqhttp` 平台（`id=napcatNN`，反向 WS 端口 `6199+N-1`，统一 Token）。
* **NapCat**：`lib/napcat.sh` 为每个实例生成 `/opt/astrbot/napcat/napcatNN/{config,ntqq,logs,plugins}` 与独立 compose；索引 `/opt/astrbot/napcat_index.tsv`，端口分配 `/opt/astrbot/ports.json`。
* **OneBot 通信**：只有一种——NapCat 作为 *反向 WebSocket 客户端* 连接 AstrBot（AstrBot 的 aiocqhttp 是反向 WS 服务端）。地址使用 Docker 服务名 `astrbot`，不是 `127.0.0.1`。
* **登录**：面板通过 NapCat WebUI（`/api/auth/login` → Credential → `/api/QQLogin/*`）取二维码 URL，前端用 `vendor/qrcode.js` 绘制；`napcat-watchdog.sh` 定时检测掉线并重启 NapCat；QQ 群内「申请登录」由 AstrBot 插件 `astrbot_plugin_nailong_remote_admin` 调用 `/api/remote/napcat/*`。
* **UI**：`panel/static/{index.html,app.js,style.css,motion.js}`，FlClash 风格（圆角卡片、液态玻璃 Dock、手机底部 Tab）。
* **部署**：`install.sh` → `scripts/install-core.sh` → `scripts/panel.sh setup`（systemd 面板），之后在面板里「初始化部署」。没有远程 SSH 部署功能，“SSH 一键部署”指用户 SSH 登录服务器执行一行安装命令。

### 1.2 需要修改的文件

| 文件 | 改动 |
| --- | --- |
| `panel/backend/nailong_ng/*`（新增） | 协议端适配层、SnowLuma、切换 / 回滚、登录状态机、错误码、诊断、VNC、SSH |
| `panel/backend/app.py` | 挂载 `/api/ng/*`；旧接口加协议端保护；Token 脱敏；日志脱敏规则；CPU / 网络速率；Docker 总览；启动一致性守护 |
| `panel/static/nextgen.{js,css}`（新增）、`app.js`、`index.html` | 协议端 / 登录中心 / 诊断 / Docker / 远程部署页，日志中心与仪表盘增强 |
| `lib/common.sh`、`lib/ops.sh`、`lib/backup.sh`、`lib/napcat.sh`、`lib/config.sh` | `slot_protocol`；启动 / 更新 / 健康检查只针对当前协议端；备份包含 SnowLuma 与 `protocols.json`；端口预留包含 noVNC / VNC |
| `scripts/napcat-watchdog.sh` | 跳过使用 SnowLuma 的账号（否则会把停用的 NapCat 拉起来抢号） |
| `scripts/panel.sh`、`panel/requirements.txt` | `paramiko`（SSH 远程部署，可选） |

### 1.3 兼容性风险及处理

| 风险 | 处理 |
| --- | --- |
| NapCat compose 是 `restart: always`，手动 `docker stop` 后在 Docker / 服务器重启时会被拉起，与 SnowLuma 同时登录同一账号 | 停用 NapCat 时同时 `docker update --restart=no`；启用时恢复 `always`。已在真实 dockerd 重启下验证（见 §8） |
| `start_all` / `restart_all` / `update_napcat` / 恢复备份会 `compose up` 所有 NapCat | 改为只启动每个账号的当前协议端（`all_compose_files`），停止 / 卸载使用 `every_compose_file` |
| 掉线守护把“NapCat 未运行”当异常并重启 | 守护跳过 `active=snowluma` 的账号 |
| 机器人池“清理空闲”会把 SnowLuma 账号的 NapCat 当空闲删除 | 机器人池对这类账号显示「SnowLuma 接管」，不再计为空闲；删除机器人前要求先卸载 SnowLuma |
| QQ 群「申请登录」只会走 NapCat 接口 | 远程登录只在 `active=napcat` 的账号中分配 |
| 旧安装没有 `protocols.json` | 缺省即 `napcat`，旧行为完全不变；一致性守护对从未安装 SnowLuma 的账号不做任何动作 |
| AstrBot 平台 ID / 端口 / Token 按账号固定 | 切换协议端不改 AstrBot 配置，不重启 AstrBot；插件、模型、人格、知识库、聊天记录不受影响 |

---

## 2. 新架构

```
奶龙管理面板
├── AstrBot（实例 / 插件 / 配置 / 日志：沿用原页面）
├── QQ 协议端（协议端页）
│   ├── NapCat    ─┐  ProtocolAdapter
│   ├── SnowLuma  ─┘
│   └── 协议端切换（备份 → 停止 → 配置 OneBot → 启动 → 校验 → 提交 / 回滚）
├── 登录管理（登录中心）：统一状态机、二维码生命周期、错误码、登录日志
├── Docker 管理：容器（含 CPU / 内存 / 网络）、镜像、网络成员
├── 诊断：7 项检查 + 可下载报告
└── 系统设置：SSH 远程部署、备份恢复、更新、安全（原有 + 新增）
```

AstrBot、NapCat、SnowLuma 各自独立容器，通过 OneBot v11 反向 WebSocket 通信，从不合并进程。

### 2.1 账号（slot）与协议端

* 账号沿用 `napcatNN` 作为内部 ID（AstrBot 平台 ID 也是它），界面显示为「机器人N」。
* 每个账号在 `/opt/astrbot/protocols.json` 中记录 `active`（`napcat` / `snowluma`）、切换历史、最近登录信息。
* NapCat 容器名 `napcatNN`；SnowLuma 容器名 `snowlumaNN`，目录 `/opt/astrbot/snowluma/snowlumaNN/`。两者数据、登录态、配置完全独立。
* 不同账号可以使用不同协议端（A→NapCat，B→SnowLuma，C→NapCat）。

### 2.2 协议端统一接口（`nailong_ng/protocols.py`）

| 方法 | NapCat | SnowLuma |
| --- | --- | --- |
| `install()` | 不支持（在「机器人」页新增实例，沿用 `lib/napcat.sh`） | ✔ 官方镜像 + 独立目录 + OneBot 配置，**不自动启动** |
| `start/stop/restart()` | ✔ | ✔（只允许当前协议端启动） |
| `activate/deactivate()` | ✔ 同时切换重启策略 | ✔（`unless-stopped`，手动停止后重启不自启） |
| `get_status()` / `get_version()` | ✔ 版本取自 NapCat 启动日志 | ✔ 版本取自镜像标签 / `package.json` |
| `get_login_status()` | ✔ WebUI `CheckLoginStatus` / `GetQQLoginInfo` | ✔ OneBot `get_login_info`（SnowLuma 登录后才创建 OneBot 实例） |
| `request_login()` / `get_qrcode()` | ✔ `RefreshQRcode` / `GetQQLoginQrcode` | **没有二维码接口**：读取容器内 QQ 登录窗口画面（x11vnc），点击画面可操作 QQ 窗口 |
| `refresh_qrcode()` | ✔ | 不支持（明确返回）；可点击画面里的二维码让 QQ 刷新 |
| `cancel_login()` | 协议端无此接口；面板停止本次登录任务 | 同左 |
| `get_logs()` | ✔ docker logs（脱敏） | ✔ |
| `get_config()` / `apply_onebot()` | ✔ `config/onebot11*.json` | ✔ `data/config/onebot.json` + `onebot_<uin>.json` |
| `update()` | ✔ 备份配置 → pull → 当前协议端才重建 | ✔ 同左，并核对镜像摘要 |
| `repair()` | ✔ 重写反向 WS、接入网络 | ✔ 重写 compose / OneBot、接入网络 |
| `uninstall()` | 不支持（在「机器人」页删除） | ✔ 默认保留数据；当前协议端禁止卸载 |

不支持的操作抛出 `Unsupported`（接口返回 `code=UNSUPPORTED`），从不伪造成功。

### 2.3 OneBot 连接方式

| 方式 | NapCat | SnowLuma | AstrBot aiocqhttp |
| --- | --- | --- | --- |
| 正向 WebSocket | ✔ `websocketServers` | ✔ `wsServers`（3001） | ✘（不支持连接出去） |
| 反向 WebSocket | ✔ `websocketClients` | ✔ `wsClients` | ✔ 服务端 |
| HTTP API | ✔ `httpServers` | ✔ `httpServers`（3000） | ✘ |
| HTTP 事件上报 | ✔ `httpClients` | ✔ `httpClients` | ✘ |

因此两种协议端都使用 **反向 WebSocket**：`ws://<AstrBot 容器名>:<账号端口>/ws`，Token 为部署 Token（`Authorization: Bearer`）。地址由 AstrBot 容器名（`.env` 的 `ASTRBOT_CONTAINER`）与 `ports.json` 中的 `astrbot_ws` 端口生成，不写死；面板自身访问协议端时按「面板在宿主机 → `127.0.0.1:<映射端口>`」「面板在 Docker → `<容器名>:<内部端口>`」自动选择。SnowLuma 的 HTTP API（3000）只映射到 `127.0.0.1`，供面板查询登录状态。

---

## 3. SnowLuma 集成

依据：官方仓库 `SnowLuma/SnowLuma`（v2.3.4）、`SnowLuma/SnowLuma.Docker.Framework`、官方文档 Docker 部署 / 配置参考 / 对接机器人 / 排障。

* **镜像**：只拉取官方 `motricseven7/snowluma`（可在协议端页改为固定 tag，并填写 `sha256:` 校验值；不一致拒绝安装 / 更新）。Docker Hub 失败时依次尝试官方文档列出的 `docker.1ms.run/`、`docker.xuanyuan.me/`、`docker.m.daocloud.io/` 前缀。面板**不复制、不修改、不重新打包** SnowLuma 的任何文件或专有原生组件。
* **compose**：由官方模板改写——每账号独立容器 / 目录（bind mount 到 `/opt/astrbot/snowluma/snowlumaNN/{data,qq-config,qq-data}`）、端口只监听 `127.0.0.1`（WebUI 5099、noVNC 6081、VNC 5900、OneBot HTTP 3000）、加入 `astrbot_network`。保留官方要求的 `SYS_PTRACE`、`seccomp=unconfined`、`shm_size: 1gb`、`ulimits`；不能加 `no-new-privileges`（镜像依赖 `setcap cap_sys_ptrace` 的 node）。
* **远程桌面密码**：安装时生成随机 `VNC_PASSWD` 写入 `.env`（0600），只供面板读取 QQ 登录窗口画面。
* **安装前检测**：CPU 架构、系统、Docker、Compose、可用内存、磁盘、`ptrace_scope`、镜像仓库网络、许可确认。
* **许可**：首次使用必须在面板中阅读并勾选确认 LICENSE / EULA（记录时间与账号）。**注意 EULA 1.1 第 5.4 条**：把专有组件并入第三方安装包或 Docker 镜像、**通过自动化脚本部署**、或任何商业用途，需事先取得著作权人书面授权。由面板代为拉取并启动官方镜像属于自动化部署，使用者需自行取得授权或自行承担合规责任。SnowLuma WebUI 内的协议同意流程（`/api/agreements`）面板不会代为同意。
* **安装后不自动启动**：同一账号同一时间只能由一个协议端接管，需在协议端页「切换到 SnowLuma」。
* **更新 / 修复 / 卸载 / 日志**：协议端页卡片「更新」「修复」「卸载」「日志」。更新前自动备份配置到 `/opt/astrbot/backups/protocol/<账号>/`。

---

## 4. 协议端切换

流程（`ProtocolManager.switch`，以任务形式执行，日志实时显示）：

1. 检查当前协议端与目标是否已安装；
2. 备份两侧协议端配置（tar.gz）；
3. 检查没有正在执行的关键任务（部署、增删实例、更新、恢复、同账号的其他协议端任务）；取消该账号的旧登录任务；
4. 停止当前协议端（NapCat 同时关闭重启策略）并确认已停止——**在目标启动之前**，保证不会两端同时占用账号；
5. 写入目标协议端的 OneBot 反向 WS 配置并校验；
6. 启动目标协议端，等待容器运行与服务就绪；
7. 校验 AstrBot 平台配置（ID / 端口 / Token），只在确有问题时调用原有的幂等同步；
8. 若目标端 QQ 已在线，检查 AstrBot 是否已建立连接；未登录则提示扫码；
9. 提交 `protocols.json`，记录历史。

任一步骤失败：停止目标端、恢复目标端配置备份、重新启用原协议端并确认运行，`active` 保持原值——不会出现两端都不可用或两端同时运行。

**一致性守护**：面板启动 15 秒后及之后每 60 秒检查一次，发现非当前协议端在运行（或 NapCat 重启策略未关闭）立即停止并记录到 `logs/protocol-switch.log`；从未安装 SnowLuma 的旧账号不受影响。

---

## 5. 统一扫码登录

### 5.1 状态机

`IDLE → REQUESTING → QR_READY → SCANNED → WAITING_CONFIRMATION → SUCCESS`，失败终态 `EXPIRED / REJECTED / FAILED / CANCELLED`。

* 每账号同一时间只有一个登录任务；「申请登录」返回正在进行的任务，「重新申请」取消旧任务并递增 generation。
* 二维码带递增 `seq` 和 `task_id`；前端丢弃旧任务 / 旧 seq 的响应，旧二维码不会覆盖新二维码；二维码未变化时服务端只返回 `unchanged`。
* 有界：任务总时限 600 秒；扫码后 180 秒未确认 → `CONFIRM_TIMEOUT`；NapCat 自动换码最多 8 次；协议端连续 5 次无响应 → 失败。不会无限重试。
* 二维码过期由协议端判定，不按固定周期刷新：NapCat 的 `onQRCodeSessionFailed(1, 3)` 会自行换新码，面板跟随新 URL 更新。
* 已在线则直接返回「QQ 已在线，无需重复登录」。
* 切换协议端、停止 / 重启协议端会取消该账号的登录任务。
* 登录成功后：识别账号、记录登录时间、检查 OneBot 配置、AstrBot 监听与连接，更新面板状态；登录弹窗自动变为成功卡片。
* 所有事件写入 `/opt/astrbot/logs/login.log`（已脱敏），在日志中心「登录日志」查看。

### 5.2 NapCat 与 SnowLuma 的区别

| | NapCat | SnowLuma |
| --- | --- | --- |
| 二维码来源 | WebUI 接口返回的二维码 URL，面板本地绘制 | 容器内 QQ 登录窗口的实时画面（x11vnc，面板直连，用户无需进入容器或打开 noVNC） |
| 已扫码 / 等待确认 | `loginPhase=qrcode_scanned / initializing` | 无扫码事件；日志 `login identity discovered` → 等待确认 |
| 成功判定 | `isLogin=true`（且 Core 在线） | OneBot `get_login_info` 返回 `user_id` |
| 过期 / 拒绝 | 由 NapCat 回调和错误消息给出 | 只显示在 QQ 窗口里，SnowLuma 不回传；画面实时可见 |

所有登录都通过协议端正式支持的方式完成：扫码与确认始终在用户手机 QQ 上进行，不绕过任何安全验证、设备验证或用户确认。

### 5.3 错误码对照（`nailong_ng/login_codes.py`）

| 归一化码 | 状态 | 说明 | 原始来源（已核对源码） |
| --- | --- | --- | --- |
| `QR_FETCH_FAILED` | FAILED | 二维码获取失败 | NapCat `QRCode Get Error`、`QRCode Refresh Error: 二维码刷新超时…`；SnowLuma 远程桌面不可读 |
| `QR_EXPIRED` | EXPIRED | 二维码已过期 | NapCat `ErrType=1 ErrCode=3`、`二维码已过期，请刷新`；面板任务超时 / 换码次数上限 |
| `QR_INVALID` | FAILED | 二维码无效 | 预留（未发现协议端返回） |
| `USER_REJECTED` | REJECTED | 用户拒绝登录 | Tencent `message` 含「拒绝」 |
| `USER_CANCELLED` | REJECTED | 手机端取消登录 | Tencent `message` 含「取消」 |
| `CONFIRM_TIMEOUT` | FAILED | 登录确认超时 | 面板：扫码后 180 秒未确认 |
| `NEED_VERIFY` | FAILED | 账号需要进一步验证 | NapCat `140022008`（需要验证码） |
| `DEVICE_VERIFY` | FAILED | 设备安全验证 | NapCat `140022010`（新设备需要扫码验证） |
| `ENV_ABNORMAL` | FAILED | 登录环境异常 | NapCat `140022011`（异常设备需要验证） |
| `NETWORK_ERROR` | FAILED | 网络连接失败 | Tencent `message` 含网络类关键词 |
| `PROTOCOL_UNREACHABLE` | FAILED | 协议端无响应 | 容器未运行 / WebUI 不可达 / 连续 5 次无响应 |
| `CLIENT_ERROR` | FAILED | QQ 客户端异常 | SnowLuma `load failed`、`auto-load failed`、`QQ runtime unavailable`、`initial connection timed out`；supervisor `qq` 非 RUNNING |
| `LOGIN_DENIED` | REJECTED | 登录请求被拒绝 | 预留给明确的服务端拒绝 |
| `ACCOUNT_RESTRICTED` | FAILED | 账号暂时无法登录 | Tencent `message` 含冻结 / 封禁 / 限制 / 暂时无法登录 |
| `KICKED_OFFLINE` | FAILED | 账号被迫下线 | NapCat KickedOffLine 提示（如「当前账号已在其它设备登录」） |
| `ACCOUNT_OFFLINE` | FAILED | 账号已离线 | SnowLuma `session closed: UIN=…` |
| `ALREADY_LOGGED_IN` | SUCCESS | 已登录 | NapCat `当前账号(…)已登录,无法重复登录` |
| `UNKNOWN` | FAILED | 服务端返回未知错误 | 其他一切：原始码与原文完整保留 |

每个错误都保留：原始错误码、原始消息、发生时间、协议端、所处登录阶段，以及分类依据（`code` / `message` / `log` / `default`）。按消息文本分类只决定显示类别，原始 `serverErrorCode` 始终保留；未知码不臆造含义。

---

## 6. 安全

* SSH 密码 AES-256-GCM 加密（密钥 `/opt/astrbot/.secret.key`，0600），接口永不返回密码；SSH 主机指纹首次连接后固定，变化即拒绝。
* OneBot / 反向 WS Token 在界面与接口中脱敏；AstrBot 页「显示」需再次输入面板密码，并写审计日志。
* 日志统一脱敏：URL token、`accessToken`、`Authorization`、`VNC_PASSWD`、远程桌面 / WebUI 临时密码、NapCat `WebUi Token` 等。
* SnowLuma 所有端口只绑定 `127.0.0.1`；不新增任何公网管理端口。
* 危险操作二次确认：切换（`SWITCH`）、停止 / 重启协议端、卸载 SnowLuma（输入账号 ID，删除数据需开启危险操作）、远程部署（`DEPLOY`）、删除服务器。
* 登录任务有超时；防重复启动（只允许当前协议端启动）与重复登录（单任务）；协议端数据目录按账号隔离。
* 保留原有安全设计（签名 Cookie、同源校验、登录限速、白名单动作、审计日志）。

---

## 7. 部署 / 升级 / 排障

### 7.1 全新部署

本机：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Ceiity/linyu/main/install.sh)
```

打开面板 → 仪表盘「初始化部署」→「协议端」页选择协议端 →「登录中心」扫码。

远程：面板「远程部署」→ 添加服务器（IP / SSH 端口 / 用户名 / 密码）→「检测环境」→「一键部署」。远端会执行同一安装脚本（非 root 自动使用 sudo），完成后任务日志给出远程面板地址与初始密码。

使用 SnowLuma：协议端页 →「SnowLuma 许可」阅读并确认 → 账号卡片「安装 SnowLuma」（环境检测 → 拉取官方镜像 → 创建容器但不启动）→「切换到 SnowLuma」→ 登录中心扫码。

### 7.2 从 2.x 升级

重新执行一键安装命令即可（脚本会 `git fetch` 最新代码并重启面板，不会重新部署或清空容器 / 数据）：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Ceiity/linyu/main/install.sh)
```

`update.sh` / 面板「更新中心」只更新镜像，不更新面板代码。

* 不需要数据库迁移：新增状态文件 `protocols.json`、`ssh_servers.json`、`.secret.key`、`logs/login.log`、`logs/protocol-switch.log` 首次使用时自动创建；缺省所有账号保持 NapCat。
* 面板依赖新增可选的 `paramiko`（`scripts/panel.sh setup` 会自动安装 `python3-paramiko`），缺失时只有远程部署不可用。
* 升级后 NapCat、AstrBot 的容器、数据、端口、Token 均不变。

### 7.3 故障排查

| 现象 | 处理 |
| --- | --- |
| 登录中心一直「正在申请」后失败 `QR_FETCH_FAILED` | NapCat 登录服务连不上腾讯服务器（日志「登录服务已断开」）：检查服务器出网；重启协议端后重试 |
| `PROTOCOL_UNREACHABLE` | 协议端容器未运行或正在重启：协议端页启动 / 重启 |
| SnowLuma 画面空白 | QQ 客户端仍在启动；稍候刷新。持续空白：诊断页看「协议端服务就绪」，或查看 SnowLuma 日志 |
| SnowLuma `CLIENT_ERROR`（注入失败） | 确认容器带 `SYS_PTRACE`、`seccomp=unconfined`；宿主 `ptrace_scope` 不能为 3；不要删除数据目录 |
| 已登录但诊断「WebSocket 未连接」 | 协议端页「修复」重写反向 WS；检查诊断中的 Token 与 Docker 网络项 |
| 两个协议端同时运行（冲突） | 点击协议端页「一致性检查」，或等待 60 秒自动处理 |
| 切换失败 | 任务日志会写明失败步骤并自动回滚；原协议端未恢复时按日志提示在协议端页手动启动 |
| Docker Hub 429 / 拉取超时 | 在服务器配置镜像加速；SnowLuma 会自动尝试官方文档列出的加速前缀 |
| SnowLuma 升级后要求重新扫码 | 官方说明：容器重建可能更换设备指纹；不要删除数据目录 |

诊断页可一键检查：协议端运行、QQ 在线、OneBot 端口、WebSocket 连接、Token、AstrBot 平台与监听、Docker 网络，并可下载文本报告。

---

## 8. 测试结果

### 8.1 自动化测试（`python3 -m unittest discover -s tests`，`bash scripts/validate.sh`）

60 项全部通过，含新增 34 项（`tests/test_ng.py`）：

* 错误码：NapCat 过期字符串、`登录失败: [...]` 保留 `serverErrorCode`、`140022008/010/011`、未知码保留原文、拒绝分类、`ErrType/ErrCode` 日志解析、SnowLuma 日志事件。
* VNC：内置 RFB 3.8 + VNC 认证测试服务器——认证、整帧读取、窗口裁剪、点击坐标映射、错误密码。
* 登录状态机：完整时间线、单任务 / 重新申请 generation、二维码 seq 与 unchanged、自动换码上限 → EXPIRED、拒绝、总超时与确认超时、预检失败、连续错误上限、旧任务操作被拒绝。
* 协议端：SnowLuma OneBot 配置与 compose（仅 127.0.0.1、权限、`.env` 0600）、NapCat→SnowLuma→NapCat 双向切换（重启策略、AstrBot 未被重启 / 修改）、目标启动失败回滚、启动阶段异常回滚、就绪失败回滚、禁止启动非当前协议端、一致性守护、并发切换拒绝、关键任务阻止切换、`/proc/net/tcp` 连接识别、诊断报告。
* SSH：密码加密 / 不落明文 / 文件权限、输入校验、环境评估。
* `shellcheck -S error`、`pyflakes`、`node --check`、`docker compose config` 通过。

### 8.2 真实环境验证（本次开发容器内的 Docker 29.9.2）

| 验收项 | 结果 |
| --- | --- |
| 1 原有 NapCat 正常运行 | ✔ 面板「初始化部署」真实部署 `mlikiowa/napcat-docker`，容器运行、WebUI 正常 |
| 2 原有 AstrBot 正常运行 | ✔ `soulter/astrbot` 运行，`aiocqhttp(napcat01)` 加载，端口 6199 监听 |
| 6 NapCat 扫码登录 | ◑ 登录任务、状态机、时间线、错误卡片已用真实 NapCat 走通；本环境无法连接腾讯服务器，NapCat 报「登录服务已断开」，任务正确结束为 `QR_FETCH_FAILED`（3 次重试后停止，未无限重试）。真实出二维码需在可访问 QQ 的服务器上验证 |
| 3/4/5 SnowLuma 部署、登录、连接 AstrBot | ✘ 未在真实环境运行：启动官方镜像即构成接受 SnowLuma EULA，必须由你本人确认，开发过程不能代为同意。相关逻辑由单元测试覆盖（含 VNC 协议），需在你的服务器上确认许可后实测 |
| 10/11/17 双向切换与回滚 | ◑ 单元测试覆盖；真实 Docker 上验证了 NapCat 停用（重启策略 no）/ 启用（always） |
| 12 切换后插件不丢失 | ✔ 切换流程不修改 AstrBot 配置、不重启 AstrBot（单元测试断言） |
| 13 多账号互不影响 | ✔ 目录、容器、端口、配置、登录任务按账号隔离（设计 + 测试） |
| 14/15 Docker / 服务器重启后恢复 | ✔ 真实重启 dockerd：AstrBot 自动恢复；已停用的 NapCat 保持停止，不会与另一协议端抢号；配置文件均在 |
| 16 登录失败不无限重试 | ✔ 真实 NapCat 上 3 次获取失败即终止；单元测试覆盖换码上限与连续错误上限 |
| 7/8/9 过期、拒绝、取消 | ✔ 单元测试；拒绝 / 过期的原始码来自 NapCat 源码 |
| 浏览器 | ✔ Playwright（1440×960、390×844）打开全部新页面，无 JS 错误；申请登录 → 失败错误卡片、许可弹窗交互正常 |

---

## 9. 接口（`/api/ng/*`，均需登录，POST 需同源）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/ng/info` | NG 版本与协议端能力 |
| GET | `/api/ng/protocols` | 全部账号、两个协议端状态、OneBot 连接、汇总 |
| GET | `/api/ng/protocols/slot?slot=` | 单账号 |
| GET | `/api/ng/protocols/config?slot=&protocol=` | OneBot 配置（Token 脱敏） |
| POST | `/api/ng/protocols/action` | `{slot, protocol, action: start/stop/restart, confirm}` |
| POST | `/api/ng/protocols/switch` | `{slot, target, confirm:"SWITCH"}` → 任务 |
| GET | `/api/ng/snowluma/preflight` | 环境检测 + 许可信息 |
| POST | `/api/ng/snowluma/consent` | `{confirm:"我已阅读并同意"}` |
| POST | `/api/ng/snowluma/image` | `{image, pinned_digest}` |
| POST | `/api/ng/snowluma/{install,update,repair,uninstall}` | → 任务（卸载需 `confirm=<slot>`） |
| POST | `/api/ng/napcat/{repair,update}` | → 任务 |
| GET | `/api/ng/login?slot=&since_seq=` | 登录任务快照（含二维码 / 画面、时间线、错误） |
| POST | `/api/ng/login` | `{slot, action: request/restart/cancel/refresh/click, task_id, x, y}` |
| GET | `/api/ng/login/codes` | 错误码对照表 |
| GET | `/api/ng/diagnose?slot=&format=text` | 诊断（JSON / 文本下载） |
| GET | `/api/ng/logs?source=&lines=&since=&download=1` | 统一日志（容器、`login`、`switch`、`onebot`、`watchdog`） |
| GET | `/api/ng/log-sources` | 日志来源列表 |
| GET | `/api/ng/docker` | 容器 / 资源 / 镜像 / 网络 |
| POST | `/api/ng/reconcile` | 立即执行一致性检查 |
| POST | `/api/ng/secret/reveal` | `{what:"reverse_token", password}` |
| GET/POST | `/api/ng/ssh`、`/api/ng/ssh/{save,delete,detect,deploy}` | SSH 服务器管理与远程部署 |
