const crypto = require('crypto');
function md5(s){return crypto.createHash('md5').update(s).digest();}
const KEY_REQ = md5('EWUIGEHWS-TPCY');  // 请求加密密钥
const KEY_RESP = md5('FEWUIFEUIW-CYTP'); // 响应解密密钥
function enc(obj){
  const data = Buffer.from(JSON.stringify(obj), 'utf8');
  const c = crypto.createCipheriv('aes-128-ecb', KEY_REQ, null);
  c.setAutoPadding(true);
  return Buffer.concat([c.update(data), c.final()]).toString('base64');
}
function dec(b64){
  const d = crypto.createDecipheriv('aes-128-ecb', KEY_RESP, null);
  d.setAutoPadding(true);
  return Buffer.concat([d.update(Buffer.from(b64,'base64')), d.final()]).toString('utf8');
}
const mode = process.argv[2];
if(mode === 'enc'){
  console.log(enc(JSON.parse(process.argv[3])));
} else if(mode === 'dec'){
  console.log(dec(process.argv[3]));
}
