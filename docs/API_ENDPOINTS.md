# AstrBot-Deploy Web 面板接口文档

本文档按当前后端入口 `panel/backend/app.py` 的实际路由整理。

- 面板基础地址：`http://<host>:7070`
- 普通 API 返回格式：`{ ok, data, message, code, time, version }`
- 统计口径：只统计 `/api/...` 后端接口，不把 `/`、`/assets/...` 静态资源和 `/files/...` 公开文件链接算入 API。
- 当前共 **64 个 API 入口**：
  - `GET`：34 个
  - `POST`：29 个
  - `DELETE`：1 个
  - 另有 1 个 `GET /api/logs/stream` 是 SSE 长连接接口，已计入 GET。

## 鉴权说明

| 类型 | 说明 |
|---|---|
| 公开接口 | 不需要登录，主要用于健康检查、登录挑战、登录。 |
| 面板登录接口 | 需要浏览器 Session Cookie。绝大多数管理接口属于这一类。 |
| Remote Token 接口 | 给 QQ 远程管理插件调用，使用远程 Token 校验。 |
| 文件 Token 接口 | 给外部/插件上传、读取、删除文件用，使用文件中心 API Token 和 scope 控制。 |
| CSRF 保护 | 已登录 Session 的 `POST/DELETE` 管理接口会校验同源请求。 |

---

## 1. 公开与登录接口

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/api/health` | 公开 | 健康检查，返回面板是否在线。 |
| GET | `/api/login/challenge` | 公开 | 获取登录加密挑战，前端用于 RSA/AES 加密登录。 |
| POST | `/api/login` | 公开 | 面板登录，成功后写入 Session Cookie。 |

---

## 2. 当前用户与总览

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/api/me` | 登录 | 检查当前登录状态，返回脱敏配置。 |
| GET | `/api/dashboard` | 登录 | 仪表盘总览数据：AstrBot、NapCat、系统状态等。 |
| GET | `/api/device/info` | 登录 | 获取服务器/设备信息。 |
| POST | `/api/device/report` | 登录 | 上报客户端设备信息，便于面板识别访问设备。 |

---

## 3. AstrBot 管理接口

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/api/astrbot` | 登录 | 获取 AstrBot 主服务状态、端口、配置等。 |
| POST | `/api/astrbot/action` | 登录 | 执行 AstrBot 操作，例如启动、停止、重启。 |
| POST | `/api/astrbot/no-prefix` | 登录 | 创建任务，应用群聊免 @ / 免前缀唤醒配置。 |
| GET | `/api/plugins/astrbot` | 登录 | 获取 AstrBot 插件列表。 |
| POST | `/api/plugins/install` | 登录 | 从上传文件安装 AstrBot 插件。 |
| GET | `/api/config/astrbot` | 登录 | 读取 AstrBot JSON 配置。 |
| POST | `/api/config/astrbot` | 登录 | 保存 AstrBot JSON 配置。 |

---

## 4. NapCat / 机器人实例接口

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/api/napcat` | 登录 | 获取 NapCat 多实例列表。 |
| GET | `/api/napcat/pool` | 登录 | 获取机器人池视图，包括在线、空闲、异常、分配状态。 |
| GET | `/api/napcat/open` | 登录 | 生成/跳转 NapCat WebUI 打开地址。 |
| POST | `/api/napcat/action` | 登录 | 创建、启动、停止、重启、删除 NapCat 实例。 |
| POST | `/api/napcat/pool/cleanup` | 登录 | 清理空闲机器人实例。 |
| POST | `/api/napcat/qq-login` | 登录 | QQ 扫码登录相关操作：获取二维码、刷新、查询状态。 |

---

## 5. QQ 远程管理插件接口

这些接口主要由 `plugins/astrbot_plugin_linyu_remote_admin` 调用。

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| POST | `/api/remote/napcat/create-login` | Remote Token | 远程申请机器人并返回扫码登录信息。 |
| POST | `/api/remote/napcat/create` | Remote Token | 远程创建 NapCat 机器人实例。 |
| POST | `/api/remote/napcat/delete` | Remote Token | 远程删除指定 NapCat 机器人实例，默认保留数据目录。 |
| POST | `/api/remote/napcat/login-status` | Remote Token | 远程查询扫码登录/实例分配状态。 |
| POST | `/api/remote/astrbot/no-prefix` | Remote Token | 远程触发 AstrBot 免 @ / 免前缀配置。 |
| POST | `/api/remote/login/public-access` | Remote Token | 远程开关公开登录入口能力。 |
| POST | `/api/linyu-remote/sync` | 登录 | 从面板同步 QQ 远程登录插件配置。 |

---

## 6. 任务接口

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/api/tasks` | 登录 | 获取最近任务列表。 |
| GET | `/api/tasks/{id}` | 登录 | 获取单个任务详情、进度和日志。 |

常见会创建任务的接口：部署、备份、恢复、更新、NapCat 操作、连接修复、插件安装、免 @ 配置等。

---

## 7. 日志接口

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/api/logs` | 登录 | 拉取指定目标的最近日志。 |
| GET | `/api/logs/stream` | 登录 | SSE 实时日志流，支持关键字过滤。 |

常用查询参数：

| 参数 | 说明 |
|---|---|
| `target` | 日志目标，例如 `astrbot`、`deploy`、`panel` 或某个 NapCat 实例。 |
| `keyword` | 关键字过滤。 |

---

## 8. 文件中心接口

文件中心有两套路由：一套是新的 ID 化文件中心，一套是兼容旧 UI 的路径式接口。

### 8.1 新文件中心接口

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/api/files` | 登录或文件 Token `files:read` | 文件列表、统计、存储信息。 |
| GET | `/api/files/storage` | 登录或文件 Token `files:read` | 获取文件中心存储信息。 |
| GET | `/api/files/statistics` | 登录或文件 Token `files:read` | 获取文件统计信息。 |
| GET | `/api/files/tokens` | 登录 | 查看文件 API Token 列表。 |
| POST | `/api/files/tokens` | 登录 | 创建、重置、禁用、删除文件 API Token。 |
| POST | `/api/files/upload` | 登录或文件 Token `files:upload` | 上传文件到文件中心。 |
| GET | `/api/files/{id}` | 登录或文件 Token `files:read` | 获取单个文件元信息。 |
| GET | `/api/files/{id}/download` | 登录或文件 Token `files:read` | 下载单个文件。 |
| GET | `/api/files/{id}/url` | 登录或文件 Token `files:read` | 获取文件公开访问 URL。 |
| GET | `/api/files/{id}/preview` | 登录或文件 Token `files:read` | 获取文件预览内容。 |
| POST | `/api/files/{id}/delete` | 登录或文件 Token `files:delete` | 删除单个文件。 |
| DELETE | `/api/files/{id}` | 登录或文件 Token `files:delete` | 删除单个文件。 |

### 8.2 兼容路径式文件接口

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/api/files/view` | 登录 | 按路径预览上传目录内文件。 |
| GET | `/api/files/download` | 登录 | 按路径下载上传目录内文件。 |
| POST | `/api/files/delete` | 登录 | 按路径删除上传目录内文件。 |
| POST | `/api/files/apply` | 登录 | 将上传文件应用为 AstrBot 配置或插件。 |

### 8.3 公开文件链接

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/files/{public_token}` | 公开链接 | 公开访问文件中心生成的文件链接。不计入 63 个 `/api` 接口。 |

---

## 9. 服务器文件浏览接口

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/api/server-files` | 登录 | 浏览服务器允许范围内的文件列表。 |
| GET | `/api/server-files/view` | 登录 | 预览服务器文件。 |
| GET | `/api/server-files/download` | 登录 | 下载服务器文件。 |

---

## 10. 部署、备份、更新接口

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| POST | `/api/deploy/start` | 登录 | 开始一键部署任务。 |
| GET | `/api/backups` | 登录 | 获取备份列表。 |
| GET | `/api/backups/download` | 登录 | 下载备份文件。 |
| POST | `/api/backup/create` | 登录 | 创建完整备份任务。 |
| POST | `/api/backup/restore` | 登录 | 恢复备份任务，需要危险操作开关和确认词。 |
| POST | `/api/update` | 登录 | 更新 AstrBot、NapCat 或全部组件。 |

---

## 11. 系统设置、安全与维护接口

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/api/settings` | 登录 | 获取面板设置。 |
| POST | `/api/settings` | 登录 | 保存面板设置，并同步远程插件配置。 |
| POST | `/api/account/password` | 登录 | 修改面板登录密码。 |
| GET | `/api/https/status` | 登录 | 获取 HTTPS/证书状态。 |
| POST | `/api/https/setup` | 登录 | 配置 HTTPS 证书。 |
| GET | `/api/watchdog/status` | 登录 | 获取 NapCat watchdog 状态。 |
| POST | `/api/watchdog/restart` | 登录 | 重启 watchdog。 |
| POST | `/api/connection/repair` | 登录 | 一键修复 AstrBot 与 NapCat 连接配置。 |

---

## 12. 静态页面入口

这些不是 API，但也是后端实际处理的 HTTP 入口：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/` | 返回面板前端 `index.html`。 |
| GET | `/assets/...` | 返回前端 JS、CSS、图片等静态资源。 |
| GET | `/files/...` | 文件中心公开文件链接。 |

---

## 13. 总数复核

| 分组 | 数量 |
|---|---:|
| 公开与登录 | 3 |
| 当前用户与总览 | 4 |
| AstrBot 管理 | 7 |
| NapCat / 机器人实例 | 6 |
| QQ 远程管理插件 | 7 |
| 任务 | 2 |
| 日志 | 2 |
| 文件中心新接口 | 12 |
| 文件中心兼容接口 | 4 |
| 服务器文件浏览 | 3 |
| 部署、备份、更新 | 6 |
| 系统设置、安全与维护 | 8 |
| **合计** | **64** |

> 注：如果按“后端 HTTP 入口”而不是“API 接口”统计，再加上 `/`、`/assets/...`、`/files/...` 这 3 类非 API 入口，总入口类型是 67 类。

