# 私有仓库一键部署说明

仓库改成私有后，普通的 `raw.githubusercontent.com` 链接不能匿名访问，需要使用 GitHub Token。

## 推荐命令

在全新的 Debian / Ubuntu 服务器上执行：

```bash
read -rsp "请输入 GitHub Token: " GITHUB_TOKEN
echo
export GITHUB_TOKEN
bash <(curl -fsSL -H "Authorization: Bearer ${GITHUB_TOKEN}" https://raw.githubusercontent.com/Ceiity/linyu/main/install.sh)
unset GITHUB_TOKEN
```

## 全自动模式

如果你想跳过面板向导，直接部署 AstrBot + 1 个 NapCat：

```bash
read -rsp "请输入 GitHub Token: " GITHUB_TOKEN
echo
export GITHUB_TOKEN
ASTRBOT_DEPLOY_MODE=full NAPCAT_COUNT=1 bash <(curl -fsSL -H "Authorization: Bearer ${GITHUB_TOKEN}" https://raw.githubusercontent.com/Ceiity/linyu/main/install.sh)
unset GITHUB_TOKEN
```

## Token 权限

GitHub Token 只需要能读取这个私有仓库：

- Fine-grained token：选择仓库 `Ceiity/linyu`，权限给 `Contents: Read-only`
- Classic token：勾选 `repo`

## 注意

- 不要把 Token 发给别人。
- 不要把带 Token 的命令写进公开文档、QQ群、微信群。
- 推荐使用上面的 `read -rsp` 方式输入 Token，这样终端不会直接显示 Token。

