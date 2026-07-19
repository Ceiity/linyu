#!/usr/bin/env python3
"""AstrBot-Deploy Web 管理控制台。"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shlex
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


STATE_FILE = Path("/opt/astrbot/.env")
PROJECT_DIR = Path("/opt/astrbot/AstrBot-Deploy")
COMMAND_LOCK = threading.Lock()


def load_state(path: Path = STATE_FILE) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        data[key] = unquote_state_value(value)
    return data


def unquote_state_value(value: str) -> str:
    if value.startswith("$'") and value.endswith("'"):
        value = value[2:-1]
        return bytes(value, "utf-8").decode("unicode_escape")
    try:
        parts = shlex.split("x=" + value, posix=True)
        if parts and parts[0].startswith("x="):
            return parts[0][2:]
    except ValueError:
        pass
    return value.strip("'\"")


def run(cmd: str, timeout: int = 120) -> tuple[int, str]:
    env = os.environ.copy()
    env["LC_ALL"] = "C.UTF-8"
    env["LANG"] = "C.UTF-8"
    proc = subprocess.run(
        ["bash", "-lc", cmd],
        cwd=str(PROJECT_DIR),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout[-20000:]


def manager_cmd(script: str, timeout: int = 900) -> tuple[int, str]:
    cmd = f"set -Eeuo pipefail; cd {shlex.quote(str(PROJECT_DIR))}; source lib/ops.sh; load_state; {script}"
    with COMMAND_LOCK:
        return run(cmd, timeout=timeout)


def docker_status() -> str:
    code, out = run("docker ps -a --format 'table {{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}'", timeout=30)
    return out if code == 0 else out


def read_text(path: Path, max_chars: int = 20000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/><title>AstrBot 控制中心</title>
<style>
:root{color-scheme:light dark;--bg:#f5f7fb;--ink:#111827;--muted:#6b7280;--card:rgba(255,255,255,.72);--card2:rgba(255,255,255,.9);--line:rgba(17,24,39,.10);--shadow:0 24px 80px rgba(15,23,42,.14);--blue:#007aff;--green:#34c759;--orange:#ff9f0a;--red:#ff3b30;--purple:#af52de}@media(prefers-color-scheme:dark){:root{--bg:#05070b;--ink:#f5f5f7;--muted:#a1a1aa;--card:rgba(28,28,30,.64);--card2:rgba(44,44,46,.88);--line:rgba(255,255,255,.12);--shadow:0 24px 90px rgba(0,0,0,.55)}}*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}body{margin:0;min-height:100vh;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI","Microsoft YaHei",sans-serif;color:var(--ink);background:radial-gradient(circle at 8% -8%,rgba(0,122,255,.36),transparent 32%),radial-gradient(circle at 90% 0%,rgba(175,82,222,.26),transparent 30%),radial-gradient(circle at 55% 105%,rgba(52,199,89,.18),transparent 30%),linear-gradient(180deg,var(--bg),var(--bg));padding:max(18px,env(safe-area-inset-top)) max(14px,env(safe-area-inset-right)) max(28px,env(safe-area-inset-bottom)) max(14px,env(safe-area-inset-left))}.shell{max-width:1240px;margin:0 auto}.nav{display:flex;align-items:center;justify-content:space-between;gap:14px;margin:8px 0 18px}.brand{display:flex;align-items:center;gap:12px}.logo{width:46px;height:46px;border-radius:15px;background:linear-gradient(135deg,#007aff,#af52de);box-shadow:0 16px 40px rgba(0,122,255,.32);display:grid;place-items:center;color:white;font-size:24px;font-weight:900}.brand b{font-size:18px}.brand span{display:block;color:var(--muted);font-size:12px;margin-top:2px}.chip{border:1px solid var(--line);background:var(--card);backdrop-filter:blur(28px);border-radius:999px;padding:10px 14px;font-weight:800;box-shadow:0 10px 32px rgba(0,0,0,.06);white-space:nowrap}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--orange);margin-right:7px;box-shadow:0 0 0 5px rgba(255,159,10,.14)}.dot.ok{background:var(--green);box-shadow:0 0 0 5px rgba(52,199,89,.14)}.dot.bad{background:var(--red);box-shadow:0 0 0 5px rgba(255,59,48,.14)}.hero{position:relative;overflow:hidden;border:1px solid var(--line);background:linear-gradient(135deg,rgba(255,255,255,.82),rgba(255,255,255,.46));backdrop-filter:blur(34px);border-radius:36px;padding:28px;box-shadow:var(--shadow);margin-bottom:16px}.hero:after{content:"";position:absolute;right:-80px;top:-90px;width:280px;height:280px;border-radius:50%;background:linear-gradient(135deg,rgba(0,122,255,.28),rgba(175,82,222,.20))}@media(prefers-color-scheme:dark){.hero{background:linear-gradient(135deg,rgba(44,44,46,.82),rgba(28,28,30,.52))}}.hero h1{position:relative;margin:0;font-size:clamp(34px,7vw,76px);letter-spacing:-.065em;line-height:.92;max-width:820px}.hero p{position:relative;color:var(--muted);font-size:clamp(15px,2vw,18px);max-width:720px;margin:14px 0 0;line-height:1.65}.heroActions{position:relative;display:flex;gap:10px;flex-wrap:wrap;margin-top:20px}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}.card{grid-column:span 12;border:1px solid var(--line);background:var(--card);backdrop-filter:blur(30px);border-radius:30px;padding:20px;box-shadow:var(--shadow)}@media(min-width:760px){.span3{grid-column:span 3}.span4{grid-column:span 4}.span5{grid-column:span 5}.span6{grid-column:span 6}.span7{grid-column:span 7}.span8{grid-column:span 8}}.kpi{min-height:142px;display:flex;flex-direction:column;justify-content:space-between}.icon{width:42px;height:42px;border-radius:15px;display:grid;place-items:center;color:white;font-size:21px;box-shadow:0 12px 26px rgba(0,0,0,.13)}.blue{background:linear-gradient(135deg,#007aff,#5ac8fa)}.green{background:linear-gradient(135deg,#30d158,#34c759)}.purple{background:linear-gradient(135deg,#af52de,#5856d6)}.orange{background:linear-gradient(135deg,#ff9f0a,#ffcc00)}.kpi label,.label{color:var(--muted);font-size:13px}.kpi strong{font-size:28px;letter-spacing:-.04em}.title{font-weight:900;font-size:20px;letter-spacing:-.03em;margin:0 0 12px}.sub{color:var(--muted);line-height:1.55}.stat{display:flex;justify-content:space-between;gap:12px;padding:12px 0;border-bottom:1px solid var(--line)}.stat:last-child{border-bottom:0}.value{text-align:right;font-weight:800;word-break:break-all}button,input{font:inherit;border:1px solid var(--line);border-radius:17px;padding:13px 15px;background:var(--card2);color:var(--ink);outline:none}button{cursor:pointer;font-weight:900;transition:.16s transform,.16s filter}button:active{transform:scale(.975)}button.primary{background:var(--blue);border-color:transparent;color:white}button.success{background:var(--green);border-color:transparent;color:white}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.row>input{flex:1;min-width:120px}.actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}@media(max-width:560px){.actions{grid-template-columns:1fr}.nav{align-items:flex-start;flex-direction:column}.hero{border-radius:30px;padding:22px}.card{border-radius:26px;padding:17px}}pre{margin:0;padding:15px;border-radius:20px;background:rgba(0,0,0,.07);overflow:auto;max-height:430px;white-space:pre-wrap;word-break:break-word;font-size:13px;line-height:1.55}@media(prefers-color-scheme:dark){pre{background:rgba(255,255,255,.07)}}a{color:var(--blue);text-decoration:none;font-weight:900}.login{position:fixed;inset:0;display:grid;place-items:center;background:rgba(0,0,0,.34);backdrop-filter:blur(26px);z-index:20;padding:20px}.box{width:min(430px,100%);background:var(--card2);border:1px solid var(--line);border-radius:34px;padding:24px;box-shadow:var(--shadow)}.hidden{display:none!important}.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:rgba(17,24,39,.88);color:white;border-radius:999px;padding:12px 16px;font-weight:800;box-shadow:0 14px 40px rgba(0,0,0,.3);z-index:30;opacity:0;pointer-events:none;transition:.2s}.toast.show{opacity:1}.listItem{padding:12px;border:1px solid var(--line);border-radius:18px;background:rgba(255,255,255,.38);margin-bottom:10px}@media(prefers-color-scheme:dark){.listItem{background:rgba(255,255,255,.06)}}
</style></head><body>
<div id="login" class="login"><div class="box"><div class="logo">&#38632;</div><h2 style="margin:16px 0 8px;font-size:28px;letter-spacing:-.04em">登录控制中心</h2><p class="sub">输入部署信息里的 Web 控制台 Token。</p><div class="row"><input id="tokenInput" placeholder="Web Token" type="password" onkeydown="if(event.key==='Enter')saveToken()"><button class="primary" onclick="saveToken()">进入</button></div></div></div><div id="toast" class="toast"></div>
<main class="shell"><div class="nav"><div class="brand"><div class="logo">A</div><div><b>AstrBot-Deploy</b><span>中文一键部署控制台</span></div></div><div class="chip" id="online"><span class="dot"></span>检测中</div></div><section class="hero"><h1>控制 AstrBot 和 NapCat，像用手机设置一样简单。</h1><p>这里可以查看状态、新增 NapCat、重启服务、备份数据。界面已经适配手机、电脑、平板。</p><div class="heroActions"><button class="primary" onclick="openAstr()">打开 AstrBot</button><button onclick="refresh(true)">刷新状态</button><button onclick="copyInfo()">复制部署信息</button></div></section>
<section class="grid"><div class="card span3 kpi"><div class="icon blue">&#129302;</div><div><label>AstrBot</label><br><strong id="astrState">-</strong></div></div><div class="card span3 kpi"><div class="icon green">&#128049;</div><div><label>NapCat 数量</label><br><strong id="napCount">-</strong></div></div><div class="card span3 kpi"><div class="icon purple">&#127760;</div><div><label>Docker 网络</label><br><strong id="networkMini" style="font-size:18px">-</strong></div></div><div class="card span3 kpi"><div class="icon orange">&#128273;</div><div><label>连接 Token</label><br><strong style="font-size:18px">yuyu521521</strong></div></div><div class="card span4"><div class="title">快速入口</div><div class="stat"><span class="label">AstrBot</span><span class="value"><a id="astrUrl" target="_blank">打开 AstrBot</a></span></div><div class="stat"><span class="label">Docker 网络</span><span class="value" id="network">-</span></div><div class="stat"><span class="label">说明</span><span class="value">NapCat 反向 WS 自动配置</span></div></div><div class="card span4"><div class="title">新增 NapCat</div><p class="sub">输入数量，自动创建容器、端口、目录、日志、反向连接配置。</p><div class="row"><input id="napAdd" type="number" min="1" max="999" value="1"><button class="primary" onclick="addNapcat()">立即创建</button></div></div><div class="card span4"><div class="title">快捷操作</div><div class="actions"><button onclick="action('/api/restart',{target:'astrbot'})">重启 AstrBot</button><button onclick="action('/api/restart',{target:'napcat'})">重启 NapCat</button><button onclick="action('/api/restart',{target:'all'})">重启全部</button><button class="success" onclick="action('/api/backup',{})">立即备份</button></div></div><div class="card span7"><div class="title">容器状态</div><pre id="containers">加载中...</pre></div><div class="card span5"><div class="title">NapCat 列表</div><div id="napList">加载中...</div></div><div class="card span6"><div class="title">部署信息</div><pre id="info">加载中...</pre></div><div class="card span6"><div class="title">操作输出</div><pre id="output">等待操作...</pre></div></section></main>
<script>
let token=localStorage.getItem('astrbot_admin_token')||'';const $=id=>document.getElementById(id);function toast(t){const e=$('toast');e.textContent=t;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),1800)}function saveToken(){token=$('tokenInput').value.trim();localStorage.setItem('astrbot_admin_token',token);$('login').classList.add('hidden');refresh(true)}if(token)$('login').classList.add('hidden');async function api(path,opts={}){opts.headers=Object.assign({'X-Admin-Token':token,'Content-Type':'application/json'},opts.headers||{});const r=await fetch(path,opts);if(r.status===401){$('login').classList.remove('hidden');throw new Error('Token 不正确')}return await r.json()}function renderNapList(text){if(!text){$('napList').textContent='暂无';return}$('napList').innerHTML=text.split('\n').filter(Boolean).map(x=>'<div class="listItem">'+x.replace(/(http[^\s]+)/g,'<a target="_blank" href="$1">$1</a>')+'</div>').join('')}async function refresh(manual=false){try{const d=await api('/api/status');$('online').innerHTML='<span class="dot ok"></span>在线';$('astrState').textContent=(d.containers||'').includes('astrbot')?'运行中':'未知';$('containers').textContent=d.containers||'';$('info').textContent=d.deploy_info||'';renderNapList(d.napcat_list||'');$('napCount').textContent=d.napcat_count;$('network').textContent=d.network||'-';$('networkMini').textContent=d.network||'-';$('astrUrl').href=d.astrbot_url||'#';$('astrUrl').textContent=d.astrbot_url||'打开 AstrBot';if(manual)toast('状态已刷新')}catch(e){$('online').innerHTML='<span class="dot bad"></span>未登录';if(manual)toast(e.message)}}async function action(path,body){$('output').textContent='执行中，请稍等...';try{const d=await api(path,{method:'POST',body:JSON.stringify(body)});$('output').textContent=d.output||JSON.stringify(d,null,2);toast(d.ok?'执行完成':'执行失败')}catch(e){$('output').textContent=e.message;toast(e.message)}refresh()}function addNapcat(){const count=Math.max(1,Math.min(999,parseInt($('napAdd').value||'1',10)));action('/api/napcat/add',{count})}function openAstr(){const a=$('astrUrl').href;if(a&&a!=='#')window.open(a,'_blank')}async function copyInfo(){try{await navigator.clipboard.writeText($('info').textContent||'');toast('已复制部署信息')}catch(e){toast('复制失败')}}refresh();setInterval(refresh,10000);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "AstrBotDeployWeb/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))

    @property
    def state(self) -> dict[str, str]:
        return load_state(self.server.state_file)  # type: ignore[attr-defined]

    def token_ok(self) -> bool:
        token = self.state.get("WEB_ADMIN_TOKEN", "")
        if not token:
            return False
        supplied = self.headers.get("X-Admin-Token", "")
        if not supplied:
            supplied = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return supplied == token

    def send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.token_ok():
            self.send_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        if parsed.path == "/api/status":
            self.handle_status()
            return
        if parsed.path == "/api/logs":
            qs = parse_qs(parsed.query)
            name = re.sub(r"[^A-Za-z0-9_.-]", "", qs.get("container", ["astrbot"])[0]) or "astrbot"
            code, out = run(f"docker logs --tail 300 {shlex.quote(name)} 2>&1", timeout=30)
            self.send_json({"ok": code == 0, "output": out})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if not self.token_ok():
            self.send_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        data = self.read_json()
        parsed = urlparse(self.path)
        if parsed.path == "/api/napcat/add":
            count = int(data.get("count", 1))
            if count < 1 or count > 999:
                self.send_json({"ok": False, "output": "NapCat 数量必须是 1-999"})
                return
            code, out = manager_cmd(f"add_napcat_instances {count}; write_deploy_info", timeout=1800)
            self.send_json({"ok": code == 0, "output": out})
            return
        if parsed.path == "/api/restart":
            target = str(data.get("target", "all"))
            if target == "astrbot":
                script = 'docker restart "$ASTRBOT_CONTAINER"'
            elif target == "napcat":
                script = 'while IFS=$\'\\t\' read -r name _; do [[ -n "$name" ]] && docker restart "$name"; done < "$NAPCAT_INDEX_FILE"'
            else:
                script = "restart_all"
            code, out = manager_cmd(script, timeout=300)
            self.send_json({"ok": code == 0, "output": out or "执行完成"})
            return
        if parsed.path == "/api/backup":
            code, out = manager_cmd("backup_all", timeout=900)
            self.send_json({"ok": code == 0, "output": out})
            return
        self.send_error(404)

    def handle_status(self) -> None:
        state = self.state
        deploy_info = read_text(Path(state.get("DEPLOY_INFO_FILE", "/opt/astrbot/deploy_info.txt")))
        nap_index = Path(state.get("NAPCAT_INDEX_FILE", "/opt/astrbot/napcat_index.tsv"))
        nap_lines = []
        if nap_index.exists():
            for line in nap_index.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) >= 5:
                    nap_lines.append(f"{parts[0]}  WebUI: http://{state.get('PUBLIC_IP','服务器IP')}:{parts[1]}/webui  Token: {parts[4]}")
        self.send_json({
            "ok": True,
            "containers": docker_status(),
            "deploy_info": deploy_info,
            "napcat_list": "\n".join(nap_lines),
            "napcat_count": len(nap_lines),
            "network": state.get("NETWORK_NAME", "astrbot_network"),
            "astrbot_url": find_line_value(deploy_info, "AstrBot URL") or f"http://{self.headers.get('Host','').split(':')[0]}:{state.get('ASTRBOT_WEB_PORT','6185')}",
        })


def find_line_value(text: str, key: str) -> str:
    prefix = key + ":"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7070)
    parser.add_argument("--state", default="/opt/astrbot/.env")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.state_file = Path(args.state)  # type: ignore[attr-defined]
    print(f"AstrBot-Deploy Web Admin listening on {args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
