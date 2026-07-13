# AstrBot-Deploy

AstrBot-Deploy is a production-oriented Docker deployment project for AstrBot + NapCat. A fresh Debian/Ubuntu server can install Docker, generate Compose files, allocate ports, create a shared Docker network, deploy AstrBot, deploy any number of NapCat instances, run health checks, and save credentials automatically.

## Official sources used

- AstrBot official Docker documentation: `soulter/astrbot:latest`, WebUI port `6185`, optional OneBot/NapCat WebSocket port `6199`, data directory `/AstrBot/data`.
- AstrBot official GitHub `compose.yml`.
- NapCat-Docker official GitHub: `mlikiowa/napcat-docker:latest`, WebUI `6099`, config directory `/app/napcat/config`, QQ data `/app/.config/QQ`, `MODE=astrbot`.
- NapCat config docs: `webui.json` contains the WebUI token; `onebot11.json` supports WebSocket client reverse connections.

## Install

```bash
bash <(curl -fsSL https://example.com/install.sh)
```

If you host this repository yourself, point the bootstrapper to your repository:

```bash
ASTRBOT_DEPLOY_REPO=https://github.com/yourname/AstrBot-Deploy.git bash <(curl -fsSL https://example.com/install.sh)
```

Local run:

```bash
sudo bash install.sh
```

The installer asks for the NapCat count. Input `20` creates `napcat01` through `napcat20`; every instance has its own directory, container, config, logs, data and Compose file.

## Layout

| Path | Purpose |
| --- | --- |
| `/opt/astrbot/data` | AstrBot data |
| `/opt/astrbot/napcat/napcatXX` | NapCat instance directories |
| `/opt/astrbot/compose/astrbot/docker-compose.yml` | AstrBot Compose file |
| `/opt/astrbot/napcat/napcatXX/docker-compose.yml` | NapCat Compose file |
| `/opt/astrbot/backups` | Backups |
| `/opt/astrbot/logs` | Installer logs |
| `/opt/astrbot/deploy_info.txt` | URLs, ports, password and tokens |
| `/opt/astrbot/.env` | Deployment state |

## Manage

```bash
sudo bash /opt/astrbot/AstrBot-Deploy/manager.sh
```

The menu includes deployment info, AstrBot update, NapCat update, update all, add/delete NapCat, logs, container status, Docker status, system status, ports, network, restart, stop, start, backup, restore, health check, one-click upgrade and uninstall.

## Upgrade

```bash
sudo bash /opt/astrbot/AstrBot-Deploy/update.sh
```

The updater pulls current images and recreates containers while keeping mounted data and configs.

## Backup

```bash
sudo bash /opt/astrbot/AstrBot-Deploy/backup.sh
```

Archives are saved as `/opt/astrbot/backups/astrbot_backup_YYYYmmdd_HHMMSS.tar.gz`.

## Restore

```bash
sudo bash /opt/astrbot/AstrBot-Deploy/restore.sh /opt/astrbot/backups/astrbot_backup_YYYYmmdd_HHMMSS.tar.gz
```

## Uninstall

```bash
sudo bash /opt/astrbot/AstrBot-Deploy/uninstall.sh
```

Uninstall supports keeping data or deleting all data, plus optional image cleanup.

## Credentials

After deployment the terminal and `/opt/astrbot/deploy_info.txt` show:

- AstrBot URL
- AstrBot username: `astrbot`
- AstrBot initial random password parsed from official logs/data when available
- NapCat WebUI URLs and generated tokens

AstrBot token: the currently reviewed official documentation does not expose a stable first-run automatic token retrieval API. This project does not fake it and keeps `get_astrbot_token` as a clean extension point.

## Network and WebSocket

All containers join `astrbot_network`. Each NapCat writes `onebot11.json` for reverse WebSocket client connection:

```text
ws://astrbot:6199/ws
```

## FAQ

### Port conflicts

Ports are auto-selected from official defaults upward and recorded in `deploy_info.txt`.

### View AstrBot password

```bash
sudo cat /opt/astrbot/deploy_info.txt
```

### View NapCat token

```bash
sudo cat /opt/astrbot/deploy_info.txt
sudo cat /opt/astrbot/napcat/napcat01/config/webui.json
```

### Troubleshooting

```bash
sudo docker logs astrbot --tail 200
sudo docker logs napcat01 --tail 200
sudo bash /opt/astrbot/AstrBot-Deploy/scripts/doctor.sh
```

### Mainland China image mirror

AstrBot official docs mention DaoCloud as an alternative image source:

```bash
ASTRBOT_IMAGE=m.daocloud.io/docker.io/soulter/astrbot:latest sudo bash install.sh
```

## Development

All shell files use:

```bash
set -Eeuo pipefail
```

Run checks:

```bash
bash -n install.sh manager.sh update.sh backup.sh restore.sh uninstall.sh scripts/*.sh lib/*.sh
bash scripts/validate.sh
```
