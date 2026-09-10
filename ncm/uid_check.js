#!/usr/bin/env node
// 网易云 ID/昵称 释放检测 —— 多通道无频控版
//
// 通道:
//   linuxapi  POST /api/linux/forward (AES-128-ECB, Linux客户端协议)  50连发零风控
//   eapi      POST /eapi/* (AES-128-ECB, PC客户端协议 + 随机化cookie指纹) 15连发零风控
//   明文       /api/* 直调 (备用, 高频会触发 -462 风控)
//
// 用法:
//   node uid_check.js uid 12345678 [12345679 ...]     检测 UID 是否释放
//   node uid_check.js nick 名字 [名字2 ...]           检测昵称是否被占用
//   node uid_check.js watch-uid 12345678 [间隔秒]     蹲守 UID, 释放即报警
//   node uid_check.js watch-nick 名字 [间隔秒]        蹲守昵称, 释放即报警
const crypto = require('crypto');

// ---------- 通道实现 ----------

// 通道A: linuxapi
const LKEY = Buffer.from('rFgB&h#%2?^eDg:Q', 'utf8');
const LINUX_UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36';
const linuxForward = async (url, params = {}) => {
  const text = JSON.stringify({ method: 'POST', url, params });
  const c = crypto.createCipheriv('aes-128-ecb', LKEY, null);
  const eparams = Buffer.concat([c.update(Buffer.from(text, 'utf8')), c.final()]).toString('hex').toUpperCase();
  const res = await fetch('https://music.163.com/api/linux/forward', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': LINUX_UA },
    body: 'eparams=' + eparams,
  });
  return res.json();
};

// 通道B: eapi (每次请求随机化 cookie 指纹以绕过按指纹的风控计数)
const EKEY = Buffer.from('e82ckenh8dichen8', 'utf8');
const PC_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';
const rnd = (n) => crypto.randomBytes(n).toString('hex');
const eapiCall = async (path, url, data) => {
  const text = JSON.stringify(data);
  const digest = crypto.createHash('md5').update(`nobody${url}use${text}md5forencrypt`).digest('hex');
  const payload = `${url}-36cd479b6b5-${text}-36cd479b6b5-${digest}`;
  const c = crypto.createCipheriv('aes-128-ecb', EKEY, null);
  const params = Buffer.concat([c.update(Buffer.from(payload, 'utf8')), c.final()]).toString('hex').toUpperCase();
  const cookie = `os=pc; appver=9.1.115; channel=netease; NMTID=${rnd(16)}; __remember_me=true; _ntes_nuid=${rnd(16)}; requestId=${Date.now()}_${Math.floor(Math.random() * 1000)}`;
  const res = await fetch('https://music.163.com/eapi' + path, {
    method: 'POST',
    headers: { 'User-Agent': PC_UA, 'Content-Type': 'application/x-www-form-urlencoded', Cookie: cookie },
    body: 'params=' + params,
  });
  return res.json();
};

// ---------- 检测逻辑 ----------

const checkUidVia = {
  linuxapi: (uid) => linuxForward(`https://music.163.com/api/v1/user/detail/${uid}`, {}),
  eapi: (uid) => eapiCall(`/v1/user/detail/${uid}`, `/api/v1/user/detail/${uid}`, {}),
  plain: async (uid) => {
    const res = await fetch(`https://music.163.com/api/v1/user/detail/${uid}`, {
      headers: { Referer: 'https://music.163.com/', 'User-Agent': PC_UA },
    });
    return res.json();
  },
};

const checkNickVia = {
  linuxapi: (nickname) => linuxForward('https://music.163.com/api/nickname/duplicated', { nickname }),
  eapi: (nickname) => eapiCall('/user/nickname/duplicated', '/api/user/nickname/duplicated', { nickname }),
  plain: async (nickname) => {
    const res = await fetch('https://music.163.com/api/nickname/duplicated', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', Referer: 'https://music.163.com/' },
      body: 'nickname=' + encodeURIComponent(nickname),
    });
    return res.json();
  },
  plainB: async (nickname) => {
    // 与 plain 同数据但独立限流桶(实测 A桶406时 B 仍可用, 400连发未触发)
    const res = await fetch('https://music.163.com/api/user/nickname/duplicated', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', Referer: 'https://music.163.com/' },
      body: 'nickname=' + encodeURIComponent(nickname),
    });
    return res.json();
  },
};

const parseUid = (uid, j) => {
  if (j.code === 200 && j.profile) return { uid, status: 'OCCUPIED', nickname: j.profile.nickname };
  if (j.code === 404) return { uid, status: j.message ? 'BANNED' : 'RELEASED', note: j.message || '账号不存在/已注销，ID 已释放' };
  return null; // 非预期(如 -462)，交由上层降级
};

const parseNick = (nickname, j) => {
  if (j.code === 200 && j.duplicated === false) return { nickname, status: 'RELEASED', note: '昵称未被占用，可以使用' };
  if (j.code === 200 && j.duplicated === true) return { nickname, status: 'OCCUPIED' };
  return null;
};

// 多通道自动降级 + 风控退避重试 + 轮询起点(均匀分摊各独立限流桶)
// 实测: 昵称检测有4个独立通道(A/B明文路径、eapi、linuxapi), 各自独立限流
// 轮换使用 + 406退避 = 实测300连发零失败, 突发限流完全免疫
// 风控形态: -462(人机验证) 和 406"操作频繁"(<5s 自愈, 仅单桶~100次/窗口触发)
const CHANNELS = ['linuxapi', 'eapi', 'plain', 'plainB'];
let rotationCursor = 0;
const sleep = (ms) => new Promise((s) => setTimeout(s, ms));
const runWithFallback = async (fn, parse, arg, maxRetry = 4) => {
  const errors = [];
  const ordered = [...CHANNELS.slice(rotationCursor), ...CHANNELS.slice(0, rotationCursor)];
  rotationCursor = (rotationCursor + 1) % CHANNELS.length; // 下次从另一通道起步
  for (let attempt = 0; attempt <= maxRetry; attempt++) {
    const blocked = [];
    for (const ch of ordered) {
      try {
        const j = await fn[ch](arg);
        const r = parse(arg, j);
        if (r) return { ...r, channel: ch };
        if (j.code === -462 || j.code === 406) blocked.push(ch); // 风控/限流，稍后重试
        else errors.push(`${ch}: ${JSON.stringify(j).slice(0, 80)}`);
      } catch (e) {
        errors.push(`${ch}: ${e.message}`);
      }
    }
    if (!blocked.length) break; // 不是风控问题，直接失败
    if (attempt < maxRetry) {
      const wait = 3000 * (attempt + 1); // 3s, 6s, 9s, 12s 退避
      await sleep(wait);
    }
  }
  return { status: 'UNKNOWN', note: errors.join(' | ') };
};

const TAG = { RELEASED: '[已释放]', OCCUPIED: '[占用中]', BANNED: '[已封禁]', UNKNOWN: '[未知]' };
const fmt = (r, isUid) => {
  const id = isUid ? `uid=${r.uid}` : `昵称=${r.nickname}`;
  return `${TAG[r.status]} ${id}` + (r.nickname && !isUid ? '' : r.nickname ? ` 昵称=${r.nickname}` : '') +
    (r.note ? ` (${r.note})` : '') + (r.channel ? ` via ${r.channel}` : '');
};

(async () => {
  const args = process.argv.slice(2);
  const cmd = args[0];
  if (!cmd) {
    console.error('用法: node uid_check.js uid <id>... | nick <名>... | watch-uid <id> [秒] | watch-nick <名> [秒]');
    process.exit(1);
  }

  if (cmd === 'watch-uid' || cmd === 'watch-nick') {
    const isUid = cmd === 'watch-uid';
    const target = args[1];
    const interval = parseInt(args[2] || '60', 10);
    const fn = isUid ? checkUidVia : checkNickVia;
    const parse = isUid ? parseUid : parseNick;
    console.error(`蹲守 ${isUid ? 'uid' : '昵称'}=${target}，每 ${interval}s 检测一次（多通道降级），释放即报警`);
    while (true) {
      const r = await runWithFallback(fn, parse, target);
      console.log(new Date().toLocaleTimeString(), fmt(r, isUid));
      if (r.status === 'RELEASED') { console.error(`>>> ${target} 已释放！快去注册/修改！`); process.exit(0); }
      await new Promise((s) => setTimeout(s, interval * 1000));
    }
  }

  if (cmd === 'uid' || cmd === 'nick') {
    const isUid = cmd === 'uid';
    const fn = isUid ? checkUidVia : checkNickVia;
    const parse = isUid ? parseUid : parseNick;
    for (const t of args.slice(1)) {
      console.log(fmt(await runWithFallback(fn, parse, t), isUid));
    }
    process.exit(0);
  }

  console.error('未知命令: ' + cmd);
  process.exit(1);
})();
