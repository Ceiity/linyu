#!/usr/bin/env node
// 网易云音乐 UID 释放检测工具（linuxapi 加密通道，无需登录，无频控）
//
// 用法:
//   node uid_check.js <uid> [uid2 uid3 ...]      单次/批量检测
//   node uid_check.js --watch <uid> [间隔秒]     轮询蹲守模式，释放即报警
//
// 判定逻辑:
//   code 404 (无 message)          => 已释放（账号不存在或已注销，ID 可用）
//   code 404 + "该账号已被封禁"     => 被封禁（ID 仍被占用）
//   code 200 + profile             => 账号正常存在
const crypto = require('crypto');

const LINUX_KEY = Buffer.from('rFgB&h#%2?^eDg:Q', 'utf8');
const UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36';

const eparams = (obj) => {
  const cipher = crypto.createCipheriv('aes-128-ecb', LINUX_KEY, null);
  return Buffer.concat([cipher.update(Buffer.from(JSON.stringify(obj), 'utf8')), cipher.final()])
    .toString('hex').toUpperCase();
};

const checkUid = async (uid) => {
  const body = 'eparams=' + eparams({
    method: 'POST',
    url: `https://music.163.com/api/v1/user/detail/${uid}`,
    params: {},
  });
  const res = await fetch('https://music.163.com/api/linux/forward', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': UA },
    body,
  });
  const j = await res.json();
  if (j.code === 200 && j.profile) {
    return { uid, status: 'OCCUPIED', nickname: j.profile.nickname };
  }
  if (j.code === 404) {
    return { uid, status: j.message ? 'BANNED' : 'RELEASED', note: j.message || '账号不存在/已注销，ID 已释放' };
  }
  return { uid, status: 'UNKNOWN', raw: JSON.stringify(j).slice(0, 120) };
};

const fmt = (r) => {
  const tag = { RELEASED: '[已释放]', OCCUPIED: '[占用中]', BANNED: '[已封禁]', UNKNOWN: '[未知]' }[r.status];
  return `${tag} uid=${r.uid}` + (r.nickname ? ` 昵称=${r.nickname}` : '') + (r.note ? ` (${r.note})` : '');
};

(async () => {
  const args = process.argv.slice(2);
  if (!args.length) {
    console.error('用法: node uid_check.js <uid> [...] | --watch <uid> [间隔秒]');
    process.exit(1);
  }

  if (args[0] === '--watch') {
    const uid = args[1];
    const interval = parseInt(args[2] || '60', 10);
    console.error(`蹲守 uid=${uid}，每 ${interval}s 检测一次，释放即退出`);
    while (true) {
      const r = await checkUid(uid);
      console.log(new Date().toLocaleTimeString(), fmt(r));
      if (r.status === 'RELEASED') { console.error(`>>> uid=${uid} 已释放！`); process.exit(0); }
      await new Promise(s => setTimeout(s, interval * 1000));
    }
  }

  for (const uid of args) {
    try { console.log(fmt(await checkUid(uid))); }
    catch (e) { console.log(`[错误] uid=${uid} ${e.message}`); }
  }
})();
