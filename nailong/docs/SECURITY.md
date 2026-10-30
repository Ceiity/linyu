# 安全设计

| 要求 | 实现 |
| --- | --- |
| SSH 主机身份验证 | 首次连接显示 SHA256 指纹由用户确认；之后严格比对，不一致直接拒绝并提示中间人风险。没有“跳过校验”选项 |
| 凭据 | SSH 密码只在内存中用于部署，经 stdin 传给 sudo，不出现在命令行和日志；用户勾选后才用 Android Keystore 保存 |
| 部署期间的暂存 | 为了 App 被系统回收后能自动接上进度，部署开始时把连接信息（含 SSH 密码/私钥）用 Android Keystore 加密暂存；部署结束（成功、失败、放弃）立即删除，超过 12 小时自动作废；SharedPreferences 里不含任何密码 |
| 长期访问 | 每台设备独立 Ed25519 密钥，服务器 authorized_keys 为 `restrict,port-forwarding,permitopen="127.0.0.1:<Agent端口>",command="echo nailong-tunnel-only"`：不能执行命令、不能开 PTY、只能转发到 Agent |
| 传输加密 | App ↔ 服务器全部走 SSH（隧道内 HTTP / WebSocket）。Android 仅允许对 `127.0.0.1`（本地隧道入口）使用明文 |
| 防暴力破解 / 撞库 | 部署时默认安装 Fail2Ban 保护 SSH：10 分钟内失败 5 次封禁该 IP 1 小时；可在部署前关闭；已有的 Fail2Ban 配置不会被改动；撤销：删除 `/etc/fail2ban/jail.d/nailong-sshd.local` 后 `fail2ban-client reload` |
| 不开放公网端口 | Agent、AstrBot WebUI、NapCat WebUI 都只绑定 127.0.0.1；验证步骤会检查奶龙管理的容器没有公网端口 |
| Agent 认证 | 一次性配对码（10 分钟，仅存哈希，失败 5 次锁定 10 分钟）→ 设备令牌（32 字节随机，仅存哈希，30 天过期，自动/手动轮换，可撤销） |
| 最小权限 | Agent 无任意命令接口；Docker 操作仅限 AstrBot / NapCat 的启动、停止、重启；只读根文件系统、no-new-privileges |
| 命令注入 | 安装器全部使用参数列表调用子进程；App 传给服务器的用户名、公钥、设备 ID、端口都经白名单正则校验，服务器端再校验一次 |
| 路径穿越 | 备份/插件 ZIP 拒绝绝对路径、`..`、链接与设备文件；恢复只写入登记的根目录内 |
| 上传校验 | 插件只收 ZIP（魔数 + 结构 + 大小上限）；备份必须带 manifest 且逐文件 SHA-256 匹配 |
| 日志脱敏 | 安装器与 Agent 都会替换已知密钥（WebUI Token、OneBot Token、jwt_secret）以及 token/password/Bearer/JWT 模式 |
| 下载完整性（内置国内镜像也不能篡改） | 安装包 SHA-256；Docker 软件源 GPG 指纹；镜像按摘要拉取；Agent 依赖 `--require-hashes`；GitHub 插件固定到提交 SHA，可强制 SHA-256 |
| 危险操作 | 停止服务、删除、卸载需确认；恢复备份需输入文件名；撤销本机授权有额外提示 |
| 已有数据 | 已有容器只读接管；修改 AstrBot 配置前先停服务并备份，保留文件原有编码（BOM） |

AstrBot 管理：Agent 从 AstrBot 数据目录读取 `dashboard.jwt_secret`，签发 10 分钟有效的 JWT 调用 AstrBot 官方接口，不保存也不需要 AstrBot 密码。

已知限制：Agent 需要挂载 docker.sock 才能管理容器，等同于宿主机 root 权限，因此 Agent 只监听本机、无任意命令接口、所有请求都需设备令牌。
