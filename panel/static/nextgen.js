/* 奶龙 Next Generation 2.0 — 协议端 / 登录中心 / 诊断 / Docker / 远程部署 / 日志增强
 * Plugs into app.js: window.NG_PAGES is consulted by render(); helpers from app.js
 * (req, toast, openModal, closeModal, confirmDanger, showTask, watchTask, esc, q, safeText,
 * copyText, qrSvgFor, okIcon, icon, pageStillActive, renderLogContent) are reused. */
(function(){
"use strict";
const NG = window.NG = {login:{slot:"",taskId:"",gen:0,seq:0,timer:null,busy:false,last:null}, logs:{timer:null,raw:""}, proto:null};
const LABEL = {napcat:"NapCat", snowluma:"SnowLuma"};
const STATE_TONE = {IDLE:"grey",REQUESTING:"blue",QR_READY:"blue",SCANNED:"orange",WAITING_CONFIRMATION:"orange",SUCCESS:"green",EXPIRED:"orange",REJECTED:"red",FAILED:"red",CANCELLED:"grey"};

/* ---------- icons ---------- */
const NG_ICONS = {
  protocol:`<path d="M7 7.5h10M7 16.5h10"/><rect x="3" y="4.5" width="18" height="6" rx="3"/><rect x="3" y="13.5" width="18" height="6" rx="3"/><path d="M7 7.5h.01M7 16.5h.01"/>`,
  qr:`<rect x="4" y="4" width="6" height="6" rx="1.5"/><rect x="14" y="4" width="6" height="6" rx="1.5"/><rect x="4" y="14" width="6" height="6" rx="1.5"/><path d="M14 14h2v2M20 14v6h-6v-2M17 17h.01"/>`,
  pulse:`<path d="M3 12h4l2.5-6 5 12 2.5-6H21"/>`,
  box:`<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>`,
  server:`<rect x="4" y="4" width="16" height="7" rx="2.5"/><rect x="4" y="13" width="16" height="7" rx="2.5"/><path d="M8 7.5h.01M8 16.5h.01M12 7.5h4M12 16.5h4"/>`,
  swap:`<path d="M7 7h12l-3.5-3.5M17 17H5l3.5 3.5"/>`,
  play:`<path d="M8 5.5v13l10-6.5Z"/>`, stop:`<rect x="6.5" y="6.5" width="11" height="11" rx="2.5"/>`,
  restart:`<path d="M20 11.5A8 8 0 1 0 17.6 17"/><path d="M20 5v6.5h-6.5"/>`, log:`<path d="M6 4h9l3 3v13H6Z"/><path d="M9 11h6M9 15h6"/>`,
  shield:`<path d="M12 3 5 6v5.5c0 4.3 3 7.7 7 9.5 4-1.8 7-5.2 7-9.5V6Z"/><path d="m9 12 2 2 4-4"/>`,
};
const _icon = window.icon;
window.icon = function(name){ if(NG_ICONS[name]) return `<svg class="adb-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${NG_ICONS[name]}</svg>`; return _icon(name); };
const ic = n => window.icon(n);

function logo(proto){
  if(proto==="snowluma") return `<span class="ng-logo snow" aria-hidden="true"><svg viewBox="0 0 40 40"><defs><linearGradient id="gSnow" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7dd3fc"/><stop offset="1" stop-color="#6366f1"/></linearGradient></defs><rect width="40" height="40" rx="12" fill="url(#gSnow)"/><path d="M20 9v22M10.5 14.5l19 11M29.5 14.5l-19 11" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/><circle cx="20" cy="20" r="3.4" fill="#fff"/></svg></span>`;
  return `<span class="ng-logo cat" aria-hidden="true"><svg viewBox="0 0 40 40"><defs><linearGradient id="gCat" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fbbf24"/><stop offset="1" stop-color="#f97316"/></linearGradient></defs><rect width="40" height="40" rx="12" fill="url(#gCat)"/><path d="M11 29V13l5.5 5h7l5.5-5v16a3 3 0 0 1-3 3H14a3 3 0 0 1-3-3Z" fill="#fff"/><circle cx="16.5" cy="23" r="1.6" fill="#f97316"/><circle cx="23.5" cy="23" r="1.6" fill="#f97316"/></svg></span>`;
}
function pill(text,tone){return `<span class="status-pill ${tone||"grey"}">${safeText(text)}</span>`}
function phaseText(l){ if(!l) return "未知"; if(l.online) return "已登录"; return ({stopped:"未运行",waiting_login:"未登录",waiting_qrcode:"等待扫码",qrcode_scanned:"已扫码",initializing:"初始化中",offline:"已离线",reconnecting:"重连中",unreachable:"不可达",not_installed:"未安装",generating_qrcode:"生成二维码"}[l.phase]||l.phase||"未登录"); }
function loginTone(l){ return l?.online?"green":(l?.phase==="stopped"||l?.phase==="not_installed")?"grey":"orange"; }
function fmtRate(n){ if(n==null) return "—"; const u=["B/s","KB/s","MB/s","GB/s"]; let i=0; while(n>=1024&&i<u.length-1){n/=1024;i++} return (n>=10||i===0?Math.round(n):n.toFixed(1))+" "+u[i]; }
function slotName(s){ const m=String(s||"").match(/(\d+)$/); return m?"机器人"+Number(m[1]):s; }
function head(title,sub,actions=""){ return `<div class="card span12 ng-head"><div><h3>${title}</h3><p class="muted">${sub}</p></div><div class="ng-head-actions">${actions}</div></div>`; }
const b = (t,js,c,extra="") => `<button class="${c||"soft"} pill-btn" ${extra} onclick="${js}">${t}</button>`;
async function task(url,body,opts={}){ const t=await req(url,{method:"POST",body:JSON.stringify(body||{})}); showTask(t.id); watchTask(t.id,opts); return t; }

/* ---------- 协议端 ---------- */
async function protocols(page="protocols",seq=state.renderSeq){
  const d = await req("/api/ng/protocols");
  if(!pageStillActive(page,seq)) return;
  NG.proto = d;
  const s = d.summary||{}, sl = d.snowluma||{};
  const consent = sl.consent ? pill("许可已确认","green") : pill("许可未确认","orange");
  let html = `<section class="grid ng-page">`+head("QQ 协议端", "AstrBot 是机器人框架，NapCat / SnowLuma 是 QQ 协议端，三者独立运行，通过 OneBot v11 反向 WebSocket 连接。每个账号同一时间只由一个协议端接管。",
    b(ic("shield")+"SnowLuma 许可","ngLicense()","soft")+b("镜像设置","ngImage()","soft")+b("一致性检查","ngReconcile()","soft")+b(ic("restart")+"刷新","render()","primary"))+
  `<div class="card span12 ng-stats">${[["账号",s.total||0,""],["NapCat",s.napcat||0,"cat"],["SnowLuma",s.snowluma||0,"snow"],["在线",s.online||0,"ok"],["OneBot 已连接",s.connected||0,"ok"],["冲突",s.conflicts||0,s.conflicts?"bad":""]].map(([k,v,c])=>`<div class="ng-stat ${c}"><b>${v}</b><span>${k}</span></div>`).join("")}<div class="ng-stat wide"><span>AstrBot</span>${d.astrbot?.running?pill("运行中","green"):pill("未运行","red")}<span>SnowLuma 许可</span>${consent}</div></div>`;
  if(!(d.slots||[]).length) html += `<div class="card span12 empty-state"><h3>还没有机器人</h3><p class="muted">先在「机器人」页面新增实例，再选择协议端。</p>${b("去新增","go('napcat')","primary")}</div>`;
  for(const it of d.slots||[]) html += slotCard(it);
  html += `</section>`;
  $("#content").innerHTML = html;
}
function slotCard(it){
  if(it.error) return `<div class="card span12"><h3>${safeText(it.display_name)}</h3><p class="muted">${safeText(it.error)}</p></div>`;
  const acct = it.online ? `${safeText(it.nickname||"QQ")} · ${safeText(it.uin||"")}` : (it.uin?`上次：${safeText(it.uin)}`:"未登录");
  const ob = it.onebot||{};
  return `<div class="card span12 ng-slot ${it.switching?"is-switching":""}" id="slot-${q(it.slot)}">
    <div class="ng-slot-head"><div class="ng-slot-title"><h3>${safeText(it.display_name)}</h3><span class="muted">${acct}</span></div>
      <div class="ng-slot-pills">${it.online?pill("在线","green"):pill("离线","grey")}${ob.connected?pill("OneBot 已连接","green"):pill(ob.listening?"AstrBot 等待连接":"OneBot 未连接","orange")}${it.conflict?pill("两个协议端同时运行","red"):""}${it.switching?pill("切换中","blue"):""}</div>
      <div class="ng-slot-actions">${b(ic("qr")+"登录","ngGoLogin('"+q(it.slot)+"')","primary")}${b(ic("pulse")+"诊断","ngGoDiag('"+q(it.slot)+"')","soft")}</div></div>
    <div class="ng-proto-grid">${protoCard(it,"napcat")}${protoCard(it,"snowluma")}</div></div>`;
}
function protoCard(it,proto){
  const c = it[proto]||{}, active = it.active===proto, slot=q(it.slot);
  const run = c.running?pill("运行中","green"):pill(c.installed?"已停止":"未安装","grey");
  const login = c.running?pill(phaseText(c.login),loginTone(c.login)):pill("—","grey");
  let actions="";
  if(!c.installed){
    actions = proto==="snowluma" ? b("安装 SnowLuma","ngInstall('"+slot+"')","primary") : `<span class="muted">请在「机器人」页面创建</span>`;
  } else if(active){
    actions = b(ic("play")+"启动",`ngAct('${slot}','${proto}','start')`,"success")+b(ic("stop")+"停止",`ngAct('${slot}','${proto}','stop')`,"danger-soft")+b(ic("restart")+"重启",`ngAct('${slot}','${proto}','restart')`,"soft")+b(ic("log")+"日志",`ngLogs('${proto==="napcat"?slot:q(c.container)}')`,"soft");
  } else {
    actions = b(ic("swap")+"切换到 "+LABEL[proto],`ngSwitch('${slot}','${proto}')`,"primary")+b(ic("log")+"日志",`ngLogs('${proto==="napcat"?slot:q(c.container)}')`,"soft");
  }
  const more = c.installed ? `<div class="ng-more">${b("配置",`ngConfig('${slot}','${proto}')`,"ghost")}${b("修复",`ngRepair('${slot}','${proto}')`,"ghost")}${b("更新",`ngUpdate('${slot}','${proto}')`,"ghost")}${proto==="snowluma"&&!active?b("卸载",`ngUninstall('${slot}')`,"ghost danger-text"):""}</div>` : "";
  return `<div class="ng-proto ${proto} ${active?"active":"inactive"} ${c.installed?"":"missing"}">
    ${active?`<span class="ng-active-badge">Active</span>`:""}
    <div class="ng-proto-top">${logo(proto)}<div><b>${LABEL[proto]}</b><small>${safeText(c.version||c.image||(c.installed?"版本未知":"未安装"))}</small></div></div>
    <div class="ng-proto-rows"><div><span>运行状态</span>${run}</div><div><span>登录状态</span>${login}</div><div><span>容器</span><code>${safeText(c.container||"")}</code></div>${c.digest?`<div><span>镜像摘要</span><code title="${q(c.digest)}">${safeText(String(c.digest).slice(0,19))}…</code></div>`:""}</div>
    <div class="ng-proto-actions">${actions}</div>${more}
    ${proto==="snowluma"?`<p class="ng-note">SnowLuma 只支持在 QQ 窗口扫码，面板会把窗口实时画面显示在登录中心。</p>`:""}
  </div>`;
}
window.ngGoLogin = slot => { NG.login.slot = slot; go("login"); };
window.ngGoDiag = slot => { NG.diagSlot = slot; go("diagnose"); };
window.ngLogs = target => { NG.logTarget = target; go("logs"); };
window.ngAct = (slot,proto,action) => {
  const run = async()=>{ await req("/api/ng/protocols/action",{method:"POST",body:JSON.stringify({slot,protocol:proto,action,confirm:action})}); toast(LABEL[proto]+" 已"+({start:"启动",stop:"停止",restart:"重启"}[action])); setTimeout(render,900); };
  if(action==="start") return withBusy("处理中",run);
  confirmDanger({title:`确认${action==="stop"?"停止":"重启"} ${LABEL[proto]}？`,name:slotName(slot),message:action==="stop"?"停止后该 QQ 账号离线，机器人不再响应。":"重启期间 QQ 会短暂离线。",confirmText:action==="stop"?"确认停止":"确认重启",onConfirm:()=>withBusy("处理中",run)});
};
window.ngSwitch = (slot,target) => {
  const from = NG.proto?.slots?.find(x=>x.slot===slot)?.active || "napcat";
  openModal(`<div class="ng-switch-confirm"><div class="ng-switch-visual">${logo(from)}<span class="ng-switch-arrow">${ic("swap")}</span>${logo(target)}</div>
    <h3>${slotName(slot)}：${LABEL[from]} → ${LABEL[target]}</h3>
    <ol class="ng-steps"><li>检查当前协议端与关键任务</li><li>备份两侧协议端配置</li><li>停止 ${LABEL[from]}（并关闭其开机自启，防止抢占账号）</li><li>写入 OneBot 反向 WebSocket（地址按 Docker 网络自动生成）</li><li>启动 ${LABEL[target]} 并检查就绪</li><li>校验 AstrBot 平台配置与连接</li></ol>
    <p class="muted">AstrBot 的插件、模型、人格、知识库、聊天记录不会被修改。任一步失败会自动回滚到 ${LABEL[from]}。不同协议端的登录状态各自独立保存，${LABEL[target]} 可能需要重新扫码。</p></div>`,
    async()=>{ closeModal(); const el=$("#slot-"+slot); el?.classList.add("is-switching"); await task("/api/ng/protocols/switch",{slot,target,confirm:"SWITCH"},{onDone:(t,ok)=>{ const r=t.result||{}; if(ok&&r.ok){ toast(r.needs_login?`已切换到 ${LABEL[target]}，请扫码登录`:`已切换到 ${LABEL[target]}`); if(r.needs_login){NG.login.slot=slot;} } else toast(r.message||"切换失败，已回滚","error"); render(); }}); },
    {confirmText:"开始切换",confirmClass:"primary"});
};
window.ngLicense = async (then) => {
  const d = NG.proto || await req("/api/ng/protocols"); const lic = d.snowluma.license, c = d.snowluma.consent;
  openModal(`<div class="ng-license"><div class="ng-license-head">${logo("snowluma")}<div><h3>SnowLuma 许可确认</h3><p class="muted">${safeText(lic.license)} · ${safeText(lic.eula)}</p></div></div>
    <ul>${lic.points.map(p=>`<li>${safeText(p)}</li>`).join("")}</ul>
    <p class="ng-links"><a href="${q(lic.license_url)}" target="_blank" rel="noopener noreferrer">LICENSE</a><a href="${q(lic.eula_url)}" target="_blank" rel="noopener noreferrer">EULA</a><a href="${q(lic.privacy_url)}" target="_blank" rel="noopener noreferrer">PRIVACY</a><a href="${q(lic.docs_url)}" target="_blank" rel="noopener noreferrer">官方部署文档</a></p>
    ${c?`<p class="ng-ok">已于 ${safeText(c.time)} 由 ${safeText(c.user)} 确认。</p>`:`<label class="ng-check"><input id="ngConsent" type="checkbox"> 我已完整阅读上述 LICENSE / EULA，确认仅用于个人非商业用途，并对“自动化部署”条款自行负责</label>`}</div>`,
    c ? null : async()=>{ if(!$("#ngConsent").checked) throw new Error("请先勾选确认"); await req("/api/ng/snowluma/consent",{method:"POST",body:JSON.stringify({confirm:"我已阅读并同意"})}); closeModal(); toast("已记录许可确认"); NG.proto=null; if(typeof then==="function") then(); else render(); },
    {confirmText:"同意并继续"});
};
window.ngInstall = async slot => {
  const d = NG.proto || await req("/api/ng/protocols");
  if(!d.snowluma.consent) return ngLicense(()=>ngInstall(slot));
  openModal(`<h3>安装 SnowLuma 到 ${slotName(slot)}</h3><p class="muted">正在检测环境…</p><div id="ngPre" class="ng-checks"></div>`, null);
  try{ const p = await req("/api/ng/snowluma/preflight"); $("#ngPre").innerHTML = checksHtml(p.checks);
    const hard = p.checks.filter(c=>!c.ok&&c.level==="error");
    openModal(`<h3>安装 SnowLuma 到 ${slotName(slot)}</h3><div class="ng-checks">${checksHtml(p.checks)}</div><p class="muted">将从官方渠道拉取 ${safeText(d.snowluma.image)}，创建独立目录 /opt/astrbot/snowluma/${safeText(slot.replace("napcat","snowluma"))}，端口只监听 127.0.0.1。安装后不会自动启动，避免与 NapCat 抢占同一账号。</p>`,
      hard.length?null:async()=>{ closeModal(); await task("/api/ng/snowluma/install",{slot},{onDone:()=>render()}); }, {confirmText:"开始安装"});
  }catch(e){ toast(e.message,"error"); }
};
function checksHtml(list){ return (list||[]).map(c=>`<div class="ng-check-row ${c.ok?"ok":c.ok===null?"skip":c.level==="warn"?"warn":"bad"}"><span class="ng-mark">${c.ok?"✓":c.ok===null?"—":c.level==="warn"?"!":"✕"}</span><div><b>${safeText(c.title)}</b><small>${safeText(c.detail||"")}</small>${c.suggestion?`<em>建议：${safeText(c.suggestion)}</em>`:""}</div></div>`).join(""); }
window.ngRepair = (slot,proto) => withBusy("提交中",()=>task(proto==="napcat"?"/api/ng/napcat/repair":"/api/ng/snowluma/repair",{slot},{onDone:()=>render()}));
window.ngUpdate = (slot,proto) => confirmDanger({title:`更新 ${LABEL[proto]}？`,name:slotName(slot),message:"更新前会自动备份协议端配置；正在使用的协议端会被重建，QQ 可能需要重新登录。",confirmText:"开始更新",onConfirm:()=>task(proto==="napcat"?"/api/ng/napcat/update":"/api/ng/snowluma/update",{slot},{onDone:()=>render()})});
window.ngUninstall = slot => openModal(`<div class="confirm-box"><div class="confirm-icon">!</div><div><h3>卸载 ${slotName(slot)} 的 SnowLuma？</h3><p class="muted">会删除 SnowLuma 容器；配置会先备份。默认保留数据目录（登录态）。</p><label class="ng-check"><input id="ngDelData" type="checkbox"> 同时删除 SnowLuma 数据目录（需开启危险操作）</label><input id="ngDelConfirm" placeholder="输入 ${q(slot)} 确认"></div></div>`,
  async()=>{ if($("#ngDelConfirm").value.trim()!==slot) throw new Error("请输入 "+slot+" 确认"); closeModal(); await task("/api/ng/snowluma/uninstall",{slot,keep_data:!$("#ngDelData").checked,confirm:slot},{onDone:()=>render()}); },{confirmText:"卸载",confirmClass:"danger"});
window.ngConfig = async (slot,proto) => { const c = await req(`/api/ng/protocols/config?slot=${encodeURIComponent(slot)}&protocol=${proto}`);
  openModal(`<h3>${LABEL[proto]} OneBot 配置 · ${slotName(slot)}</h3><p class="muted">AstrBot 反向 WS：<code>${safeText(c.astrbot_ws_url)}</code>（Token 已脱敏）</p>${(c.files||[]).map(f=>`<div class="ng-cfg"><b>${safeText(f.file)}</b>${["ws_clients","ws_servers","http_servers","http_clients"].map(k=>`<div><span>${{ws_clients:"反向 WebSocket",ws_servers:"正向 WebSocket",http_servers:"HTTP API",http_clients:"HTTP 上报"}[k]}</span><code>${safeText(JSON.stringify(f[k]||[]))}</code></div>`).join("")}</div>`).join("")||`<p class="muted">没有找到配置文件</p>`}${c.ports?`<p class="muted">端口（仅 127.0.0.1）：${safeText(JSON.stringify(c.ports))}</p>`:""}`,null);
};
window.ngImage = async () => { const d = NG.proto || await req("/api/ng/protocols");
  openModal(`<h3>SnowLuma 镜像</h3><p class="muted">只使用官方镜像（motricseven7/snowluma）。生产环境建议固定版本 tag，并填写 sha256 校验值：拉取后不一致会拒绝安装 / 更新。</p><label>镜像<input id="ngImg" value="${q(d.snowluma.image)}"></label><label>固定校验值（可选）<input id="ngDig" placeholder="sha256:…" value="${q(d.snowluma.pinned_digest||"")}"></label>`,
  async()=>{ await req("/api/ng/snowluma/image",{method:"POST",body:JSON.stringify({image:$("#ngImg").value,pinned_digest:$("#ngDig").value})}); closeModal(); toast("已保存"); NG.proto=null; render(); },{confirmText:"保存"}); };
window.ngReconcile = () => withBusy("检查中",async()=>{ const r = await req("/api/ng/reconcile",{method:"POST",body:"{}"}); toast(r.actions.length?`已停止 ${r.actions.length} 个非当前协议端`:"一致：每个账号只有一个协议端在运行"); render(); });

/* ---------- 登录中心 ---------- */
async function login(page="login",seq=state.renderSeq){
  const d = await req("/api/ng/protocols");
  if(!pageStillActive(page,seq)) return;
  NG.proto = d;
  const slots = d.slots||[];
  if(!slots.length){ $("#content").innerHTML = `<section class="grid">${head("登录中心","还没有机器人实例。",b("去新增","go('napcat')","primary"))}</section>`; return; }
  if(!NG.login.slot || !slots.find(x=>x.slot===NG.login.slot)) NG.login.slot = (slots.find(x=>!x.online)||slots[0]).slot;
  $("#content").innerHTML = `<section class="grid ng-page">
    <div class="card span12 ng-chips" role="tablist">${slots.map(x=>`<button role="tab" class="ng-chip ${x.slot===NG.login.slot?"on":""}" onclick="ngPickSlot('${q(x.slot)}')"><i class="dot ${x.online?"g":"o"}"></i>${safeText(x.display_name)}<small>${LABEL[x.active]}</small></button>`).join("")}</div>
    <div class="card span12 ng-login" id="ngLogin"><div class="ng-login-stage" id="ngStage"></div><div class="ng-login-side" id="ngSide"></div></div>
  </section>`;
  NG.login.taskId=""; NG.login.gen=0; NG.login.started=0; NG.login.seq=0; NG.login.last=null;
  ngPoll(true);
}
window.ngPickSlot = slot => { if(slot===NG.login.slot) return; NG.login.slot=slot; NG.login.taskId=""; NG.login.gen=0; NG.login.started=0; NG.login.seq=0; NG.login.last=null; document.querySelectorAll(".ng-chip").forEach(el=>el.classList.toggle("on",el.getAttribute("onclick").includes("'"+slot+"'"))); ngPoll(true); };
function stopPoll(){ clearTimeout(NG.login.timer); NG.login.timer=null; }
async function ngPoll(force=false){
  stopPoll();
  if(state.page!=="login") return;
  const slot = NG.login.slot, since = force?0:NG.login.seq;
  let d;
  try{ d = await req(`/api/ng/login?slot=${encodeURIComponent(slot)}&since_seq=${since}`); }
  catch(e){ if(state.page==="login") NG.login.timer=setTimeout(ngPoll,4000); return; }
  if(state.page!=="login" || slot!==NG.login.slot) return;
  // Drop stale responses: an older task (generation) must never overwrite a newer one.
  if(d.task_id && NG.login.taskId && d.task_id!==NG.login.taskId && (d.started_at||0) < (NG.login.started||0)) { NG.login.timer=setTimeout(ngPoll,800); return; }
  if(d.task_id && d.task_id!==NG.login.taskId){ NG.login.taskId=d.task_id; NG.login.gen=d.generation||0; NG.login.started=d.started_at||0; NG.login.seq=0; force=true; if(d.qr?.unchanged){ return ngPoll(true); } }
  drawLogin(d, force);
  const live = d.task_id && !d.terminal;
  NG.login.timer = setTimeout(ngPoll, document.hidden?4000: live?1200:6000);
}
function drawLogin(d, force){
  const prev = NG.login.last; NG.login.last = d;
  const slotInfo = (NG.proto?.slots||[]).find(x=>x.slot===NG.login.slot)||{};
  const proto = d.protocol || d.active_protocol || slotInfo.active || "napcat";
  const cur = d.current || {};
  const stage = $("#ngStage"), side = $("#ngSide");
  if(!stage||!side) return;
  // ---- stage ----
  const qrChanged = d.qr && !d.qr.unchanged && d.qr.seq !== NG.login.seq;
  if(d.state==="SUCCESS"){
    stage.innerHTML = `<div class="ng-success">${okIcon()}<h3>${d.already?"QQ 已在线":"登录成功"}</h3><p>${safeText(d.account?.nickname||cur.nickname||"")} ${safeText(d.account?.uin||cur.uin||"")}</p></div>`;
    if(prev && prev.state!=="SUCCESS" && prev.task_id===d.task_id){ toast("登录成功"); invalidateCache("dashboard","napcat","pool"); NG.proto=null; }
  } else if(d.qr && (qrChanged || force || !stage.querySelector(".ng-qr"))){
    if(!d.qr.unchanged){
      NG.login.seq = d.qr.seq;
      if(d.qr.kind==="url"){
        stage.innerHTML = `<div class="ng-qr ng-pop"><div class="ng-qr-code">${qrSvgFor(d.qr.url)||`<p class="muted">无法绘制二维码</p>`}</div><p class="ng-qr-tip">用手机 QQ 扫码，并在手机上确认登录</p><p class="ng-qr-meta" id="ngQrMeta"></p></div>`;
      } else if(d.qr.kind==="image"){
        stage.innerHTML = `<div class="ng-qr ng-pop screen"><img id="ngScreen" alt="QQ 登录窗口实时画面" src="data:image/png;base64,${d.qr.png_base64}" onclick="ngScreenClick(event)"><p class="ng-qr-tip">这是 SnowLuma 容器内 QQ 登录窗口的实时画面：用手机 QQ 扫描其中的二维码。二维码失效时可直接点击画面中的二维码刷新。</p><p class="ng-qr-meta" id="ngQrMeta"></p></div>`;
      }
    }
  } else if(!d.qr && (!d.task_id || d.terminal)){
    const tone = d.terminal && d.state!=="CANCELLED" && d.task_id ? "ng-idle bad" : "ng-idle";
    stage.innerHTML = `<div class="${tone}">${window.scanHeroIcon?scanHeroIcon():""}<h3>${cur.online?"QQ 已在线":d.task_id?safeText(d.state_text):"准备登录"}</h3><p class="muted">${cur.online?`${safeText(cur.nickname||"")} ${safeText(cur.uin||"")}`:(d.task_id?`查看右侧错误说明后点击「重新申请」`:`点击「申请登录」获取 ${LABEL[proto]} 的二维码`)}</p></div>`;
  } else if(!d.qr && !stage.querySelector(".ng-loading")){
    stage.innerHTML = `<div class="ng-idle ng-loading"><span class="spin big"></span><h3>${safeText(d.state_text||"正在申请登录")}</h3></div>`;
  }
  if(d.terminal && d.state!=="SUCCESS" && d.task_id) stage.querySelector(".ng-qr")?.classList.add("dim");
  const meta = $("#ngQrMeta");
  if(meta && d.qr){ const age = d.qr_age!=null?`已显示 ${d.qr_age}s`:""; meta.textContent = [age, d.qr.expires_hint?`约 ${d.qr.expires_hint}s 后过期`:(proto==="napcat"?"有效期由 QQ 决定，过期后自动换新":"二维码由 QQ 客户端管理"), d.qr_refreshes?`已换码 ${d.qr_refreshes} 次`:"", d.deadline_in?`任务剩余 ${Math.floor(d.deadline_in/60)}:${String(d.deadline_in%60).padStart(2,"0")}`:""].filter(Boolean).join(" · "); }
  // ---- side ----
  const tl = (d.timeline||[]).map(r=>`<li class="${r.status}"><i></i><span>${safeText(r.label)}</span>${r.at?`<time>${new Date(r.at*1000).toLocaleTimeString()}</time>`:""}</li>`).join("");
  const err = d.error ? errorCard(d.error) : "";
  const warns = (d.warnings||[]).slice(-2).map(w=>`<div class="ng-warn">${safeText(w.title)}：${safeText((w.raw_message||"").slice(0,140))}</div>`).join("");
  const running = d.task_id && !d.terminal;
  const acct = d.account?.uin ? `${safeText(d.account.nickname||"")} ${safeText(d.account.uin)}` : cur.online ? `${safeText(cur.nickname||"")} ${safeText(cur.uin||"")}` : (slotInfo.uin?`上次：${safeText(slotInfo.uin)}`:"—");
  const checks = (d.checks||[]).length ? `<div class="ng-checks small">${checksHtml(d.checks)}</div>` : "";
  side.innerHTML = `<div class="ng-login-info">
      <div><span>QQ 账号</span><b>${acct}</b></div>
      <div><span>账号状态</span>${cur.online||d.state==="SUCCESS"?pill("在线","green"):pill(phaseText(cur),loginTone(cur))}</div>
      <div><span>协议端</span><b>${logo(proto)} ${LABEL[proto]}</b></div>
      <div><span>登录进度</span>${pill(d.state_text||"空闲",STATE_TONE[d.state]||"grey")}</div>
    </div>
    <ol class="ng-timeline">${tl}</ol>${err}${warns}${checks}
    <div class="ng-login-actions">
      ${running?b("取消申请","ngLoginAct('cancel')","danger-soft")+b("刷新二维码","ngLoginAct('refresh')","soft")+b("重新申请","ngLoginAct('restart')","soft")
        :cur.online&&d.state!=="FAILED"?b("重新登录","ngLoginAct('restart')","soft"):b(d.task_id?"重新申请":"申请登录",`ngLoginAct('${d.task_id?"restart":"request"}')`,"primary")}
      ${b("查看详情","ngLoginDetail()","ghost")}${b("登录日志","ngLogs('login')","ghost")}
    </div>`;
}
function errorCard(e){
  return `<div class="ng-error ${e.state==="REJECTED"?"rejected":e.state==="EXPIRED"?"expired":""}"><div class="ng-error-head"><b>${safeText(e.title)}</b><span>${safeText(LABEL[e.protocol]||e.protocol||"")}</span></div>
    <p>${safeText(e.description)}</p><p class="ng-sugg">建议：${safeText(e.suggestion)}</p>
    <dl><dt>错误码</dt><dd><code>${safeText(e.code)}</code>${e.raw_code?` · 原始 <code>${safeText(e.raw_code)}</code>`:""}</dd><dt>原始消息</dt><dd>${safeText((e.raw_message||"—").slice(0,300))}</dd><dt>阶段</dt><dd>${safeText(e.stage||"—")}</dd><dt>时间</dt><dd>${safeText(e.time||"")}</dd></dl></div>`;
}
window.ngScreenClick = async ev => {
  const img = ev.currentTarget, r = img.getBoundingClientRect();
  const x = (ev.clientX - r.left) * img.naturalWidth / r.width, y = (ev.clientY - r.top) * img.naturalHeight / r.height;
  try{ await req("/api/ng/login",{method:"POST",body:JSON.stringify({slot:NG.login.slot,action:"click",task_id:NG.login.taskId,x,y})}); toast("已点击 QQ 窗口"); setTimeout(()=>ngPoll(),900); }catch(e){ toast(e.message,"error"); }
};
window.ngLoginAct = action => withBusy("处理中", async()=>{
  const body = {slot:NG.login.slot, action, task_id:NG.login.taskId};
  const t = await req("/api/ng/login",{method:"POST",body:JSON.stringify(body)});
  if(action==="request"||action==="restart"){ NG.login.taskId=t.task_id; NG.login.gen=t.generation; NG.login.started=t.started_at||0; NG.login.seq=0; }
  if(action==="cancel") toast("已取消登录申请");
  drawLogin(t, true); ngPoll(action!=="refresh");
});
window.ngLoginDetail = () => { const d = NG.login.last||{};
  openModal(`<h3>登录详情 · ${slotName(NG.login.slot)}</h3><p class="muted">任务 ${safeText(d.task_id||"—")} · 第 ${safeText(d.generation||0)} 次 · 用时 ${safeText(d.elapsed||0)}s</p>
    <div class="ng-events">${(d.events||[]).slice().reverse().map(e=>`<div class="${e.level}"><time>${safeText(e.time)}</time><span>${safeText(e.text)}</span></div>`).join("")||"<p class='muted'>暂无事件</p>"}</div>
    ${d.error?`<h4>原始错误</h4><pre class="code">${safeText(JSON.stringify(d.error,null,2))}</pre>`:""}${b("错误码对照表","ngCodes()","ghost")}`,null); };
window.ngCodes = async () => { const t = await req("/api/ng/login/codes");
  openModal(`<h3>登录错误码对照表</h3><p class="muted">原始码来自 NapCat / SnowLuma 源码；未收录的原始码按「未知错误」显示并保留原文。</p><div class="ng-codes">${t.codes.map(c=>`<div><code>${c.code}</code><b>${safeText(c.title)}</b><p>${safeText(c.description)}</p><small>建议：${safeText(c.suggestion)}</small></div>`).join("")}</div><h4>原始码映射</h4><div class="ng-codes">${t.sources.map(s=>`<div><code>${safeText(s.protocol)}</code><b>${safeText(s.raw)}</b><small>→ ${safeText(s.code)}</small></div>`).join("")}</div>`,null); };

/* ---------- 诊断 ---------- */
async function diagnose(page="diagnose",seq=state.renderSeq){
  const d = await req("/api/ng/protocols"); if(!pageStillActive(page,seq)) return; NG.proto=d;
  const slots = d.slots||[];
  $("#content").innerHTML = `<section class="grid ng-page">${head("一键诊断","检查协议端运行、QQ 在线、OneBot 端口、WebSocket 连接、Token、AstrBot 连接与 Docker 网络。",
    `<select id="ngDiagSlot"><option value="">全部机器人</option>${slots.map(x=>`<option value="${q(x.slot)}" ${NG.diagSlot===x.slot?"selected":""}>${safeText(x.display_name)} · ${LABEL[x.active]}</option>`).join("")}</select>`+b(ic("pulse")+"开始诊断","ngRunDiag()","primary")+b("下载报告","ngDiagDownload()","soft"))}<div class="span12 grid" id="ngDiag"></div></section>`;
  ngRunDiag();
}
window.ngRunDiag = async () => { const el=$("#ngDiag"); if(!el) return; el.innerHTML=`<div class="card span12"><span class="spin"></span> 正在诊断…</div>`;
  const slot=$("#ngDiagSlot")?.value||""; NG.diagSlot=slot;
  try{ const d = await req("/api/ng/diagnose"+(slot?`?slot=${encodeURIComponent(slot)}`:""));
    el.innerHTML = d.reports.map(r=>`<div class="card span6 ng-report ${r.ok?"ok":"bad"}"><div class="ng-report-head"><h3>${safeText(r.display_name)}</h3>${pill(r.label||"",r.protocol==="snowluma"?"blue":"orange")}${r.ok?pill("全部正常","green"):pill("有问题","red")}</div><p class="muted">${safeText(r.summary)}</p><div class="ng-checks">${checksHtml(r.checks)}</div><div class="ng-report-actions">${b("复制报告",`ngCopyReport('${q(r.slot)}')`,"ghost")}${b("修复连接",`ngRepair('${q(r.slot)}','${q(r.protocol||"napcat")}')`,"ghost")}${b("去登录",`ngGoLogin('${q(r.slot)}')`,"ghost")}</div></div>`).join("")||`<div class="card span12">没有机器人</div>`;
    NG.diagReports = d.reports;
  }catch(e){ el.innerHTML=`<div class="card span12">${safeText(e.message)}</div>`; } };
window.ngCopyReport = slot => { const r=(NG.diagReports||[]).find(x=>x.slot===slot); if(!r) return; copyText([`${r.display_name}（${r.label}）`, ...r.checks.map(c=>`${c.ok?"✔":c.ok===null?"—":"✘"} ${c.title}：${c.detail}${c.suggestion?"（建议："+c.suggestion+"）":""}`), "结论："+r.summary].join("\n")); };
window.ngDiagDownload = () => { const slot=$("#ngDiagSlot")?.value||""; location.href="/api/ng/diagnose?format=text"+(slot?"&slot="+encodeURIComponent(slot):""); };

/* ---------- Docker ---------- */
async function docker(page="docker",seq=state.renderSeq){
  const d = await req("/api/ng/docker"); if(!pageStillActive(page,seq)) return;
  const cs = d.containers||[];
  $("#content").innerHTML = `<section class="grid ng-page">${head("Docker", `Docker ${safeText(d.version||"不可用")} · 网络 ${safeText(d.network?.name||"")}`, b(ic("restart")+"刷新","render()","primary"))}
    <div class="card span12"><h3>容器</h3><div class="ng-tiles">${cs.map(c=>`<div class="ng-tile"><div class="ng-tile-head"><b>${safeText(c.name)}</b>${pill(c.state==="running"?"运行中":c.state,c.state==="running"?"green":"grey")}</div><small>${safeText(c.image)}</small><small>${safeText(c.status)}</small><div class="ng-usage"><span>CPU ${safeText(c.usage?.cpu||"—")}</span><span>内存 ${safeText(c.usage?.mem||"—")}</span><span>网络 ${safeText(c.usage?.net||"—")}</span></div>${b(ic("log")+"日志",`ngLogs('${q(c.name)}')`,"ghost")}</div>`).join("")||"<p class='muted'>没有容器</p>"}</div></div>
    <div class="card span6"><h3>镜像</h3><div class="ng-list">${(d.images||[]).map(i=>`<div><b>${safeText(i.repo)}:${safeText(i.tag)}</b><small>${safeText(i.size)} · ${safeText(i.created)}</small></div>`).join("")||"<p class='muted'>无</p>"}</div></div>
    <div class="card span6"><h3>网络成员</h3><div class="ng-list">${(d.network?.members||[]).map(m=>`<div><b>${safeText(m.name)}</b><small>${safeText(m.ip)}</small></div>`).join("")||"<p class='muted'>网络不存在或无成员</p>"}</div></div></section>`;
}

/* ---------- 远程部署 ---------- */
async function ssh(page="ssh",seq=state.renderSeq){
  const d = await req("/api/ng/ssh"); if(!pageStillActive(page,seq)) return;
  $("#content").innerHTML = `<section class="grid ng-page">${head("SSH 远程部署","输入服务器 IP、SSH 端口、用户名和密码，一键检测环境并部署奶龙（AstrBot + 协议端 + 面板）。密码使用 AES-256-GCM 加密保存，主机指纹首次连接后固定。",b("+ 添加服务器","ngSshEdit()","primary"))}
    ${(d.servers||[]).map(s=>`<div class="card span6 ng-server"><div class="ng-tile-head"><b>${safeText(s.name)}</b>${s.last_deploy?pill(s.last_deploy.ok?"已部署":"部署失败",s.last_deploy.ok?"green":"red"):pill("未部署","grey")}</div><p class="muted">${safeText(s.username)}@${safeText(s.host)}:${safeText(s.port)}${s.host_key?` · ${safeText(s.host_key.fingerprint).slice(0,22)}…`:""}</p>${s.last_check?`<p class="muted">上次检测 ${safeText(s.last_check.time)} · ${safeText(s.last_check.info?.OS||"")} · ${safeText(s.last_check.info?.ARCH||"")}</p>`:""}${s.last_deploy?.panel?`<p><a class="link-pill" href="${q(s.last_deploy.panel)}" target="_blank" rel="noopener noreferrer">${safeText(s.last_deploy.panel)}</a></p>`:""}<div class="ng-proto-actions">${b("检测环境",`ngSshDetect('${q(s.id)}')`,"soft")}${b("一键部署",`ngSshDeploy('${q(s.id)}')`,"primary")}${b("编辑",`ngSshEdit('${q(s.id)}')`,"ghost")}${b("删除",`ngSshDelete('${q(s.id)}')`,"ghost danger-text")}</div></div>`).join("")||`<div class="card span12 empty-state"><h3>还没有服务器</h3><p class="muted">添加一台 Debian / Ubuntu 服务器开始。</p></div>`}</section>`;
  NG.ssh = d.servers||[];
}
window.ngSshEdit = id => { const s=(NG.ssh||[]).find(x=>x.id===id)||{port:22,username:"root"};
  openModal(`<h3>${id?"编辑":"添加"}服务器</h3><label>名称<input id="sN" value="${q(s.name||"")}"></label><label>服务器 IP / 域名<input id="sH" value="${q(s.host||"")}" autocapitalize="off"></label><label>SSH 端口<input id="sP" type="number" value="${q(s.port||22)}"></label><label>用户名<input id="sU" value="${q(s.username||"root")}" autocapitalize="off"></label><label>密码<input id="sW" type="password" placeholder="${id?"留空表示不修改":""}" autocomplete="new-password"></label><p class="muted">密码只保存在本服务器，加密存储，不会回显。</p>`,
  async()=>{ await req("/api/ng/ssh/save",{method:"POST",body:JSON.stringify({id,name:$("#sN").value,host:$("#sH").value,port:$("#sP").value,username:$("#sU").value,password:$("#sW").value})}); closeModal(); toast("已保存"); render(); },{confirmText:"保存"}); };
window.ngSshDelete = id => confirmDanger({title:"删除服务器？",message:"只删除面板里保存的连接信息与加密密码，不会影响远程服务器。",confirmText:"删除",onConfirm:async()=>{ await req("/api/ng/ssh/delete",{method:"POST",body:JSON.stringify({id,confirm:"DELETE"})}); render(); }});
window.ngSshDetect = id => withBusy("正在连接",async()=>{ const r = await req("/api/ng/ssh/detect",{method:"POST",body:JSON.stringify({id})}); openModal(`<h3>环境检测 · ${safeText(r.server.host)}</h3><div class="ng-checks">${checksHtml(r.checks)}</div>`,null); });
window.ngSshDeploy = id => { const s=(NG.ssh||[]).find(x=>x.id===id)||{};
  openModal(`<h3>部署到 ${safeText(s.host)}</h3><p class="muted">会通过 SSH 运行奶龙一键安装脚本：自动检测架构、系统、Docker、内存、磁盘和网络，安装依赖与 Docker，并启动面板。</p><label>同时创建 NapCat 实例数（0 = 只装面板，之后在远程面板中部署）<input id="sC" type="number" min="0" max="50" value="0"></label><label class="ng-check"><input id="sM" type="checkbox"> 使用 GitHub 加速镜像</label>`,
  async()=>{ closeModal(); await task("/api/ng/ssh/deploy",{id,confirm:"DEPLOY",napcat_count:Number($("#sC")?.value||0),mirror:$("#sM")?.checked},{onDone:()=>render()}); },{confirmText:"开始部署"}); };

/* ---------- 日志中心（增强） ---------- */
async function ngLogsPage(page="logs",seq=state.renderSeq){
  let sources=[]; try{ sources = await req("/api/ng/log-sources"); }catch(e){ sources=[{id:"astrbot",label:"AstrBot",group:"AstrBot"}]; }
  if(!pageStillActive(page,seq)) return;
  const groups={}; sources.forEach(s=>(groups[s.group]=groups[s.group]||[]).push(s));
  const cur = NG.logTarget || "astrbot"; NG.logTarget="";
  $("#content").innerHTML = `<section class="grid"><div class="card span12 log-center-card"><div class="section-head"><div><h3>日志中心</h3><p class="muted">AstrBot、NapCat、SnowLuma、OneBot 通信、登录、协议切换与 Docker 日志统一查看，敏感凭据已脱敏。</p></div></div>
    <div class="log-toolbar ng-log-toolbar"><div class="log-filters"><select id="ngLogSrc">${Object.entries(groups).map(([g,list])=>`<optgroup label="${q(g)}">${list.map(s=>`<option value="${q(s.id)}">${safeText(s.label)}</option>`).join("")}</optgroup>`).join("")}</select>
      <input id="ngLogKey" placeholder="搜索关键词"><select id="ngLogLevel"><option value="">全部级别</option><option value="error">仅错误</option><option value="warn">警告及以上</option></select>
      <select id="ngLogSince"><option value="">全部时间</option><option value="10m">最近 10 分钟</option><option value="1h">最近 1 小时</option><option value="6h">最近 6 小时</option><option value="24h">最近 24 小时</option></select></div>
      <div class="log-actions">${b("刷新","ngLoadLog()","primary")}<button id="ngLive" class="soft pill-btn live-on" onclick="ngToggleLive()">实时：开</button><button id="ngScroll" class="soft pill-btn" onclick="ngToggleScroll()">自动滚动：开</button>${b("复制","copyText(NG.logs.shown||'')","soft")}${b("下载","ngDownloadLog()","soft")}${b("全屏","$('#logBox').requestFullscreen?.()","soft")}</div></div>
    <pre id="logBox" class="code log-viewer">加载中...</pre></div></section>`;
  const sel=$("#ngLogSrc"); sel.value=cur; if(!sel.value) sel.value="astrbot";
  ["ngLogSrc","ngLogLevel","ngLogSince"].forEach(id=>$("#"+id).onchange=()=>ngLoadLog());
  $("#ngLogKey").oninput=()=>ngFilterLog();
  NG.logs.live=true; state.logPaused=false; ngLoadLog();
}
window.ngLoadLog = async () => {
  clearTimeout(NG.logs.timer);
  if(state.page!=="logs"||!$("#ngLogSrc")) return;
  const src=$("#ngLogSrc").value, since=$("#ngLogSince").value;
  try{ const d = await req(`/api/ng/logs?source=${encodeURIComponent(src)}&lines=1500${since?"&since="+since:""}`); NG.logs.raw=d.content||""; ngFilterLog(); }
  catch(e){ renderLogContent("读取失败："+e.message); }
  if(NG.logs.live && state.page==="logs") NG.logs.timer=setTimeout(ngLoadLog, document.hidden?8000:2500);
};
function ngFilterLog(){ const key=($("#ngLogKey")?.value||"").toLowerCase(), lv=$("#ngLogLevel")?.value||"";
  const errRe=/error|fail|exception|traceback|fatal|失败|错误|异常|✘/i, warnRe=/warn|警告|timeout|超时|retry|重试/i;
  const lines=String(NG.logs.raw||"").split("\n").filter(l=>(!key||l.toLowerCase().includes(key))&&(!lv||(lv==="error"?errRe.test(l):errRe.test(l)||warnRe.test(l))));
  NG.logs.shown=lines.join("\n"); renderLogContent(NG.logs.shown||"（没有匹配的日志）"); }
window.ngToggleLive = () => { NG.logs.live=!NG.logs.live; const b=$("#ngLive"); b.textContent="实时："+(NG.logs.live?"开":"关"); b.classList.toggle("live-on",NG.logs.live); if(NG.logs.live) ngLoadLog(); else clearTimeout(NG.logs.timer); };
window.ngToggleScroll = () => { state.logPaused=!state.logPaused; $("#ngScroll").textContent="自动滚动："+(state.logPaused?"关":"开"); };
window.ngDownloadLog = () => { const src=$("#ngLogSrc").value, since=$("#ngLogSince").value; location.href=`/api/ng/logs?source=${encodeURIComponent(src)}&lines=5000&download=1${since?"&since="+since:""}`; };

/* ---------- 仪表盘：协议端总览 ---------- */
const _dashboard = window.dashboard;
window.dashboard = async function(page="dashboard",seq=state.renderSeq){
  await _dashboard(page,seq);
  if(page!=="dashboard"||!pageStillActive(page,seq)) return;
  let d; try{ d = await req("/api/ng/protocols"); }catch(e){ return; }
  if(!pageStillActive(page,seq)) return;
  const sys = state.data?.system || {};
  const s = d.summary||{};
  const host = $("#content .grid") || $("#content");
  document.querySelectorAll("#content .ng-dash").forEach(x=>x.remove());
  const el = document.createElement("div"); el.className="card span12 ng-dash";
  const rows = (d.slots||[]).slice(0,6).map(x=>`<div class="ng-dash-row" onclick="ngGoLogin('${q(x.slot)}')">${logo(x.active)}<div><b>${safeText(x.display_name)}</b><small>${x.online?`${safeText(x.nickname||"")} ${safeText(x.uin||"")}`:"未登录"}</small></div>${x.online?pill("在线","green"):pill("离线","grey")}${(x.onebot||{}).connected?pill("OneBot","green"):pill("OneBot","orange")}</div>`).join("");
  el.innerHTML = `<div class="ng-dash-grid">
    <div class="ng-kpi"><span>AstrBot</span>${d.astrbot?.running?pill("运行中","green"):pill("未运行","red")}</div>
    <div class="ng-kpi"><span>QQ 协议端</span><b>NapCat ${s.napcat||0} · SnowLuma ${s.snowluma||0}</b></div>
    <div class="ng-kpi"><span>在线账号</span><b>${s.online||0} / ${s.total||0}</b></div>
    <div class="ng-kpi"><span>OneBot 连接</span><b>${s.connected||0} / ${s.total||0}</b></div>
    <div class="ng-kpi"><span>CPU</span><b>${sys.cpu_percent!=null?sys.cpu_percent+"%":"—"}</b></div>
    <div class="ng-kpi"><span>内存</span><b>${sys.memory?.used_percent!=null?sys.memory.used_percent+"%":"—"}</b></div>
    <div class="ng-kpi"><span>网络 ↓/↑</span><b>${fmtRate(sys.net?.rx_rate)} / ${fmtRate(sys.net?.tx_rate)}</b></div>
    <div class="ng-kpi"><span>Docker</span>${state.data?.docker?.ok===false?pill("异常","red"):pill("正常","green")}</div>
  </div>${rows?`<div class="ng-dash-rows">${rows}</div>`:""}<div class="ng-head-actions">${b("协议端","go('protocols')","soft")}${b("登录中心","go('login')","primary")}${b("诊断","go('diagnose')","soft")}</div>`;
  host.prepend(el);
};

/* ---------- AstrBot：Token 脱敏 + 验证后显示 ---------- */
const _astrbot = window.astrbot;
window.astrbot = async function(page="astrbot",seq=state.renderSeq){
  await _astrbot(page,seq);
  if(!pageStillActive(page,seq)) return;
  document.querySelectorAll("#content .info-line").forEach(line=>{ if(line.querySelector("b")?.textContent.includes("Token")){ const v=line.querySelector(".value"); if(v){ v.onclick=null; v.removeAttribute("onclick"); v.insertAdjacentHTML("beforeend",` <button class="ghost pill-btn" onclick="ngReveal(event)">显示</button>`); } } });
};
window.ngReveal = ev => { ev?.stopPropagation?.();
  openModal(`<h3>显示连接 Token</h3><p class="muted">OneBot Token 默认脱敏。请输入面板密码验证，本次操作会写入审计日志。</p><label>面板密码<input id="ngPw" type="password" autocomplete="current-password"></label><div id="ngTok"></div>`,
  async()=>{ const r = await req("/api/ng/secret/reveal",{method:"POST",body:JSON.stringify({what:"reverse_token",password:$("#ngPw").value})}); $("#ngTok").innerHTML=`<pre class="code">${safeText(r.value)}</pre>`; await copyText(r.value); },{confirmText:"验证并复制"}); };

window.NG_PAGES = {protocols, login, diagnose, docker, ssh};
window.logs = ngLogsPage;
document.addEventListener("visibilitychange",()=>{ if(!document.hidden && state.page==="login") ngPoll(); });
window.addEventListener("hashchange",()=>{ if(state.page!=="login") stopPoll(); if(state.page!=="logs") clearTimeout(NG.logs.timer); });
if(document.querySelector("#app:not(.hidden)")) { try{ renderNav(); }catch(e){} }
})();
