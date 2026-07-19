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
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>AstrBot 控制中心</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f5f5f7;
      --panel: rgba(255,255,255,.72);
      --panel-strong: rgba(255,255,255,.88);
      --text: #1d1d1f;
      --muted: #6e6e73;
      --blue: #007aff;
      --green: #34c759;
      --red: #ff3b30;
      --border: rgba(60,60,67,.16);
      --shadow: 0 24px 80px rgba(0,0,0,.12);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #06070a;
        --panel: rgba(28,28,30,.68);
        --panel-strong: rgba(44,44,46,.86);
        --text: #f5f5f7;
        --muted: #98989d;
        --border: rgba(255,255,255,.14);
        --shadow: 0 24px 80px rgba(0,0,0,.46);
      }
    }
    * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
    body {
      margin: 0; min-height: 100vh; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", "Microsoft YaHei", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 15% 0%, rgba(0,122,255,.22), transparent 30%),
        radial-gradient(circle at 90% 10%, rgba(175,82,222,.18), transparent 28%),
        linear-gradient(180deg, var(--bg), var(--bg));
      padding: max(18px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(24px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
    }
    .wrap { max-width: 1180px; margin: 0 auto; }
    header { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin: 18px 0 22px; }
    h1 { margin: 0; font-size: clamp(34px, 7vw, 64px); letter-spacing: -.055em; line-height: .95; }
    .sub { color: var(--muted); margin-top: 10px; font-size: 15px; }
    .pill { border: 1px solid var(--border); background: var(--panel); border-radius: 999px; padding: 10px 14px; backdrop-filter: blur(24px); white-space: nowrap; }
    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 16px; }
    .card { grid-column: span 12; background: var(--panel); border: 1px solid var(--border); border-radius: 28px; padding: 20px; box-shadow: var(--shadow); backdrop-filter: blur(28px); }
    @media (min-width: 800px) { .span4 { grid-column: span 4; } .span5 { grid-column: span 5; } .span7 { grid-column: span 7; } .span6 { grid-column: span 6; } }
    .title { font-weight: 800; font-size: 20px; letter-spacing: -.02em; margin: 0 0 12px; }
    .stat { display: flex; justify-content: space-between; gap: 12px; padding: 11px 0; border-bottom: 1px solid var(--border); }
    .stat:last-child { border-bottom: 0; }
    .label { color: var(--muted); }
    .value { text-align: right; font-weight: 650; word-break: break-all; }
    button, input, select {
      font: inherit; border: 1px solid var(--border); border-radius: 16px; padding: 13px 15px;
      background: var(--panel-strong); color: var(--text); outline: none;
    }
    button { cursor: pointer; font-weight: 750; transition: transform .12s ease, opacity .12s ease; }
    button:active { transform: scale(.98); }
    .primary { background: var(--blue); color: #fff; border-color: transparent; }
    .green { background: var(--green); color: #fff; border-color: transparent; }
    .red { background: var(--red); color: #fff; border-color: transparent; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    .row > input { flex: 1; min-width: 130px; }
    .actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    @media (max-width: 520px) { .actions { grid-template-columns: 1fr; } header { align-items: start; flex-direction: column; } }
    pre { margin: 0; padding: 14px; border-radius: 18px; background: rgba(0,0,0,.08); overflow: auto; max-height: 420px; white-space: pre-wrap; word-break: break-word; }
    .ok { color: var(--green); font-weight: 800; }
    .bad { color: var(--red); font-weight: 800; }
    .login { position: fixed; inset: 0; display: grid; place-items: center; background: rgba(0,0,0,.25); backdrop-filter: blur(22px); z-index: 10; padding: 20px; }
    .login .box { width: min(420px, 100%); background: var(--panel-strong); border: 1px solid var(--border); border-radius: 30px; padding: 24px; box-shadow: var(--shadow); }
    .hidden { display: none !important; }
    a { color: var(--blue); text-decoration: none; font-weight: 700; }
  </style>
</head>
<body>
  <div id="login" class="login">
    <div class="box">
      <h2 style="margin:0 0 8px">登录控制中心</h2>
      <p class="sub">输入部署时生成的 Web 控制台 Token。</p>
      <div class="row"><input id="tokenInput" placeholder="Web Token" type="password"><button class="primary" onclick="saveToken()">进入</button></div>
    </div>
  </div>
  <main class="wrap">
    <header>
      <div>
        <h1>AstrBot 控制中心</h1>
        <div class="sub">像苹果设置一样，手机、电脑、平板都能管 AstrBot + NapCat。</div>
      </div>
      <div class="pill" id="online">检测中...</div>
    </header>
    <section class="grid">
      <div class="card span4">
        <div class="title">快速入口</div>
        <div class="stat"><span class="label">AstrBot</span><span class="value"><a id="astrUrl" target="_blank">打开</a></span></div>
        <div class="stat"><span class="label">NapCat 数量</span><span class="value" id="napCount">-</span></div>
        <div class="stat"><span class="label">Docker 网络</span><span class="value" id="network">-</span></div>
        <div class="stat"><span class="label">连接 Token</span><span class="value">yuyu521521</span></div>
      </div>
      <div class="card span4">
        <div class="title">新增 NapCat</div>
        <p class="sub">输入数量，系统会自动创建容器、端口、目录、反向连接配置。</p>
        <div class="row">
          <input id="napAdd" type="number" min="1" max="999" value="1">
          <button class="primary" onclick="addNapcat()">创建</button>
        </div>
      </div>
      <div class="card span4">
        <div class="title">常用操作</div>
        <div class="actions">
          <button onclick="action('/api/restart', {target:'astrbot'})">重启 AstrBot</button>
          <button onclick="action('/api/restart', {target:'napcat'})">重启 NapCat</button>
          <button onclick="action('/api/restart', {target:'all'})">重启全部</button>
          <button class="green" onclick="action('/api/backup', {})">立即备份</button>
        </div>
      </div>
      <div class="card span7">
        <div class="title">容器状态</div>
        <pre id="containers">加载中...</pre>
      </div>
      <div class="card span5">
        <div class="title">NapCat 列表</div>
        <pre id="napList">加载中...</pre>
      </div>
      <div class="card span6">
        <div class="title">部署信息</div>
        <pre id="info">加载中...</pre>
      </div>
      <div class="card span6">
        <div class="title">操作输出</div>
        <pre id="output">等待操作...</pre>
      </div>
    </section>
  </main>
  <script>
    let token = localStorage.getItem('astrbot_admin_token') || '';
    const $ = id => document.getElementById(id);
    function saveToken(){ token = $('tokenInput').value.trim(); localStorage.setItem('astrbot_admin_token', token); $('login').classList.add('hidden'); refresh(); }
    if(token) $('login').classList.add('hidden');
    async function api(path, opts={}){
      opts.headers = Object.assign({'X-Admin-Token': token}, opts.headers || {});
      const r = await fetch(path, opts);
      if(r.status === 401){ $('login').classList.remove('hidden'); throw new Error('Token 不正确'); }
      return await r.json();
    }
    async function refresh(){
      try {
        const d = await api('/api/status');
        $('online').innerHTML = d.ok ? '<span class="ok">在线</span>' : '<span class="bad">异常</span>';
        $('containers').textContent = d.containers || '';
        $('napList').textContent = d.napcat_list || '暂无';
        $('info').textContent = d.deploy_info || '';
        $('napCount').textContent = d.napcat_count;
        $('network').textContent = d.network || '-';
        $('astrUrl').href = d.astrbot_url || '#';
        $('astrUrl').textContent = d.astrbot_url || '打开';
      } catch(e) { $('online').innerHTML = '<span class="bad">未登录</span>'; }
    }
    async function action(path, body){
      $('output').textContent = '执行中，请稍等...';
      try {
        const d = await api(path, {method:'POST', body: JSON.stringify(body)});
        $('output').textContent = d.output || JSON.stringify(d, null, 2);
      } catch(e) { $('output').textContent = e.message; }
      refresh();
    }
    function addNapcat(){
      const count = Math.max(1, Math.min(999, parseInt($('napAdd').value || '1', 10)));
      action('/api/napcat/add', {count});
    }
    refresh();
    setInterval(refresh, 10000);
  </script>
</body>
</html>
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
