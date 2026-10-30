# 部署与构建文档

## 服务器端做了什么

App 通过 SSH 执行 `installer/nailong_installer.py`（以 root/sudo 运行，仅用 Python 标准库）：

| 步骤 | 说明 |
| --- | --- |
| 上传 | 安装包 `bundle.tar.gz` 经 SFTP 上传到 `/tmp`，`sha256sum -c` 校验与 App 内记录一致后解压到 `/opt/nailong/installer` |
| detect | 系统/版本/架构、root、systemd；Docker、Compose、Python、Git、curl、wget、tar、unzip、apt；CPU/内存/磁盘；DNS 与 HTTPS 可达性；UFW/firewalld；sshd 是否允许转发；容器、网络、数据卷、监听端口；已有 AstrBot / NapCat / Agent |
| deps | 只安装缺失的 curl、tar、gnupg、ca-certificates |
| fail2ban | 防 SSH 暴力破解：从系统官方源安装 `fail2ban`，写入 `/etc/fail2ban/jail.d/nailong-sshd.local`（实际 SSH 端口、10 分钟内失败 5 次封禁 1 小时、systemd 日志后端）。**已有 Fail2Ban 且已保护 SSH 时只保留不改**；用户在报告页关闭开关则跳过；失败只给警告，不中断部署 |
| docker | 删除冲突的发行版旧包 → 下载 Docker 官方 GPG 密钥并**校验指纹 `9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88`** → 配置 APT 源 → 安装 docker-ce、containerd.io、buildx、compose 插件 → `systemctl enable --now docker` |
| images | 对每个加速器与官方源测速（DNS、TLS、清单摘要、架构），按 `仓库@sha256:摘要` 拉取，失败退避重试并切换来源，最后打成固定标签 |
| astrbot | `/opt/nailong/astrbot/data` 持久化，WebUI 只绑定 `127.0.0.1:<自动端口>`，网络 `nailong_net` |
| napcat | `/opt/nailong/napcat/{config,ntqq}` 持久化，预写 WebUI Token 与 OneBot 反向 WS 配置，WebUI 只绑定 `127.0.0.1` |
| onebot | 已有 aiocqhttp 平台则复用不改；否则停 AstrBot → 备份 `cmd_config.json` → 追加平台（随机 Token）→ 启动，校验 6199 端口 |
| agent | 复制源码，临时容器内 `pip install --require-hashes`，Agent 以 host 网络只监听 `127.0.0.1:<自动端口>`，只读根文件系统、no-new-privileges |
| verify | 容器运行、Agent 健康检查、确认奶龙管理的容器没有公网端口 |

部署以独立后台任务运行（有 systemd 时用 `systemd-run --unit nailong-deploy`，否则 `setsid`），日志写入 `/opt/nailong/run/deploy.log`；
App 用 `deploy-poll --offset N` 增量读取，SSH 断线后重连并从上次位置继续。安装器忽略 SIGHUP，只有明确“取消”（`cancel` → SIGTERM）才会停止。

所有步骤幂等：重复执行会跳过已完成的部分，因此“继续部署”是安全的。状态保存在 `/opt/nailong/state.json`（0600）。

目录：

```
/opt/nailong/
├── installer/         安装器（每次与 App 版本同步）
├── astrbot/data       AstrBot 数据（新部署时）
├── napcat/            NapCat 配置与 QQ 数据（新部署时）
├── agent/{app,deps,data}
├── backups/           备份
├── cache/             测速缓存
└── state.json
```

已有服务的数据目录保持原位置不变，Agent 以挂载方式访问。

## 手动排查

```bash
sudo python3 /opt/nailong/installer/nailong_installer.py detect   # 环境报告
docker logs nailong-agent --tail 100                              # Agent 日志
curl -s http://127.0.0.1:18180/healthz                            # Agent 健康检查（端口见 state.json）
```

## 卸载 Agent（不影响 AstrBot / NapCat）

```bash
docker rm -f nailong-agent
sudo rm -rf /opt/nailong/agent
# 删除 App 公钥：~/.ssh/authorized_keys 中以 " nailong:<设备ID>" 结尾的行
```

## 构建 APK

需要 Flutter 3.47+、Android SDK、JDK 17+。

```bash
cd nailong
python3 tool/fetch_wheels.py            # 下载并校验 Agent 离线依赖（SHA-256 对照 requirements.lock）
python3 tool/bundle_server.py          # 打包安装器 + Agent + 离线依赖，生成 app/assets/server/bundle.{tar.gz,json}
cd app
flutter pub get
flutter analyze
flutter build apk --release --split-per-abi
# 产物：build/app/outputs/flutter-apk/app-arm64-v8a-release.apk
```

正式签名：在 `app/android/key.properties` 写 `storeFile/storePassword/keyAlias/keyPassword`。
CI：`.github/workflows/nailong.yml` 会运行 Agent/安装器测试、Flutter 分析并构建 APK。

## 测试

```bash
# Agent 与安装器单元测试
cd nailong/agent && pip install -r requirements.lock pytest httpx && pytest
cd ../installer && pytest tests

# 端到端（需要一台可 SSH 的全新 Ubuntu 测试机）
cd ../app
E2E_HOST=1.2.3.4 E2E_PORT=22 E2E_USER=root E2E_PASS=... E2E_FP=SHA256:... flutter test test/e2e_server_test.dart
```
