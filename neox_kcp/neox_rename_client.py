#!/usr/bin/env python3
"""
NeoX KCP 长连接改名客户端（单文件完整版）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import queue
import secrets
import socket
import struct
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_SALT = "0"
DEFAULT_CRYPTO_MODE = 0

SYNC_MAGIC_DEFAULT = 0x688DAFB2
G1_DEFAULT = 0xE88DAFB3
G2_DEFAULT = 0xE88DAFB2
MASK_DEFAULT = 0xFFFFFFFE
HEARTBEAT_MARKER = 0xE4B868B9
KCP_CONNECT_HI_MAGIC = 0x8FAFD21E25C5E09B

HS_CMD_SYNC1 = 0x04
HS_CMD_SYNC2 = 0x09
HS_CMD_HEARTBEAT = 0x00
HS_CMD_HI = 0x7D

SYNC1_SIZE = 48
SYNC2_SIZE = 30
HEARTBEAT_SIZE = 48
IKCP_INTERVAL = 0.02

IKCP_PUSH, IKCP_ACK, IKCP_WASK, IKCP_WINS = 81, 82, 83, 84
IKCP_HEADER = 24
IKCP_MSS = 1200
IKCP_WND = 32

FRAME_ID_ENTITY_METHOD = 0x8000

GATE_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA7ax5CGFu8KKAXGUuRbks
bUHSaNvm91DS7qRLOhhNs1j0rSC+O94bfhY84DmCEuyLWwrCXe4Rq0FYatktqksG
RM5buCM/pRwJhcT+GAyJPozM+vkend7jxxScbi8/ojVnAUSD9dBP1TT3DBRta5gb
X10R/XsVTgPDNkH8vP+kqW6dYYUb9TnRtdl+HYz0trOTR7DTdi/BuOkOTrC6azq1
yYQY2HfQOdjiH5oZ8nYaeFnaFfd6FfqmuUV/d0Z2kFRadq02ZwgiL/Xak17vdpOp
U+UIxWAy0N/bE+PL5OycVNh51KUuVHyTF6H3iwXqq0iW8KxQq0/8Gqxhc3lDtl04
fwIDAQAB
-----END PUBLIC KEY-----
"""

REQ_NEW_CONNECTION = 0
REPLY_CONNECTED = 1


def log(tag: str, msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}", file=sys.stderr, flush=True)


def varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def read_varint(data: bytes, pos: int = 0) -> Tuple[int, int]:
    value = shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("truncated varint")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too large")


def zigzag32(v: int) -> int:
    return (v << 1) ^ (v >> 31)


def unzigzag32(v: int) -> int:
    return (v >> 1) ^ -(v & 1)


def uvar_field(no: int, value: int) -> bytes:
    return varint((no << 3) | 0) + varint(value)


def sint32_field(no: int, value: int) -> bytes:
    return varint((no << 3) | 0) + varint(zigzag32(value))


def bytes_field(no: int, value: bytes) -> bytes:
    return varint((no << 3) | 2) + varint(len(value)) + value


def message_field(no: int, value: bytes) -> bytes:
    return bytes_field(no, value)


def parse_fields(data: bytes) -> List[Tuple[int, int, Any]]:
    fields, pos = [], 0
    while pos < len(data):
        raw_key, pos = read_varint(data, pos)
        no, wt = raw_key >> 3, raw_key & 7
        if wt == 0:
            value, pos = read_varint(data, pos)
        elif wt == 2:
            size, pos = read_varint(data, pos)
            value = data[pos:pos + size]
            if len(value) != size:
                raise ValueError("truncated bytes field")
            pos += size
        else:
            raise ValueError(f"unsupported wire type: {wt}")
        fields.append((no, wt, value))
    return fields


def rpc_index(name: str, salt: str = DEFAULT_SALT) -> int:
    d = hashlib.md5((name + salt).encode("utf-8")).digest()
    return (((d[-4] & 0x7F) << 24) | (d[-3] << 16) | (d[-2] << 8) | d[-1])


def prop_value(value: Any) -> bytes:
    if isinstance(value, bool):
        return uvar_field(2, int(value))
    if isinstance(value, int):
        return uvar_field(1, value)
    if isinstance(value, str):
        return bytes_field(4, value.encode("utf-8"))
    raise TypeError(f"unsupported arg type: {type(value).__name__}")


def prop_item_value(value: Any) -> bytes:
    return message_field(3, prop_value(value))


def tuple_param(values: Sequence[Any]) -> bytes:
    prop_dict = b"".join(message_field(2, prop_item_value(v)) for v in values)
    return uvar_field(1, 44) + message_field(4, prop_dict)


def area_message(rpc_name: str, values: Sequence[Any], *, salt: str) -> bytes:
    method = sint32_field(2, rpc_index(rpc_name, salt))
    return message_field(3, method) + message_field(4, tuple_param(values))


def decode_prop_value(data: bytes) -> Any:
    for no, wt, v in parse_fields(data):
        if no == 1 and wt == 0:
            return v
        if no == 2 and wt == 0:
            return bool(v)
        if no == 4 and wt == 2:
            return v.decode("utf-8", errors="replace")
    return None


def decode_area_message(data: bytes) -> Dict[str, Any]:
    result: Dict[str, Any] = {"method_index": None, "args": []}
    for no, wt, v in parse_fields(data):
        if no == 2 and wt == 0:
            result["guid"] = v
        elif no == 3 and wt == 2:
            for mn, mw, mv in parse_fields(v):
                if mn == 2 and mw == 0:
                    result["method_index"] = unzigzag32(mv)
        elif no == 4 and wt == 2:
            args = []
            for cn, cw, cv in parse_fields(v):
                if cn != 4 or cw != 2:
                    continue
                for gn, gw, gv in parse_fields(cv):
                    if gn != 2 or gw != 2:
                        continue
                    for pn, pw, pv in parse_fields(gv):
                        if pn == 3 and pw == 2:
                            args.append(decode_prop_value(pv))
            result["args"] = args
    return result


def decode_inner_frame(data: bytes) -> Dict[str, Any]:
    if len(data) < 6:
        raise ValueError("inner frame too short")
    size, frame_id = struct.unpack("<IH", data[:6])
    if size != len(data) - 4:
        raise ValueError(f"bad length: header={size}, actual={len(data) - 4}")
    if frame_id != FRAME_ID_ENTITY_METHOD:
        raise ValueError(f"bad frame id: 0x{frame_id:04x}")
    decoded = decode_area_message(data[6:])
    decoded["frame_id_hex"] = f"0x{frame_id:04x}"
    return decoded


def inner_frame(area: bytes) -> bytes:
    body = struct.pack("<H", FRAME_ID_ENTITY_METHOD) + area
    return struct.pack("<I", len(body)) + body


def rpc_inner_frame(rpc_name: str, values: Sequence[Any], *, salt: str) -> bytes:
    return inner_frame(area_message(rpc_name, values, salt=salt))


def sauth_json_string(token: str, sdkuid: str) -> str:
    return json.dumps({"sdkuid": sdkuid, "accesstoken": token}, ensure_ascii=False)


class RC4Stream:
    def __init__(self, key_bytes: bytes):
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + key_bytes[i % len(key_bytes)]) & 0xFF
            s[i], s[j] = s[j], s[i]
        self._s, self._i, self._j = s, 0, 0

    def update(self, data: bytes) -> bytes:
        out = bytearray()
        s, i, j = self._s, self._i, self._j
        for byte in data:
            i = (i + 1) & 0xFF
            j = (j + s[i]) & 0xFF
            s[i], s[j] = s[j], s[i]
            out.append(byte ^ s[(s[i] + s[j]) & 0xFF])
        self._i, self._j = i, j
        return bytes(out)


def native_aes_key_material(key_bytes: bytes) -> Tuple[Optional[bytes], Optional[int]]:
    n = len(key_bytes)
    if n <= 23:
        needed, bits = 16, 128
    elif n <= 31:
        needed, bits = 24, 192
    else:
        needed, bits = 32, 256
    if n < needed:
        return None, None
    return key_bytes[:needed].ljust(needed, b"\x00"), bits


class CryptoStream:
    def __init__(self, mode_id: int, key: bytes, *, encrypt: bool):
        if mode_id == 0:
            self._stream = RC4Stream(key)
            return
        material, _ = native_aes_key_material(key)
        if material is None:
            self._stream = RC4Stream(key)
            return
        iv = b"\x00" * 16
        m = modes.CFB(iv) if mode_id == 1 else modes.OFB(iv)
        cipher = Cipher(algorithms.AES(material), m)
        self._stream = cipher.encryptor() if encrypt else cipher.decryptor()

    def update(self, data: bytes) -> bytes:
        return self._stream.update(data)


def rsa_oaep_encrypt(public_key_pem: bytes, data: bytes) -> bytes:
    pub = serialization.load_pem_public_key(public_key_pem)
    return pub.encrypt(data, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA1()),
        algorithm=hashes.SHA1(), label=None))


class WireConfig:
    def __init__(self, magic: int = SYNC_MAGIC_DEFAULT, mask: int = MASK_DEFAULT):
        self.g1 = (magic | 0x80000001) & 0xFFFFFFFF
        self.g2 = (self.g1 & 0xFFFFFFFE) & 0xFFFFFFFF
        self.g3 = (mask | 1) & 0xFFFFFFFF

    def is_handshake(self, first_u32: int) -> bool:
        return ((first_u32 ^ self.g1) & self.g3) == 0

    def is_data(self, first_u32: int) -> bool:
        return first_u32 == self.g2


class HandshakeCodec:
    def __init__(self, cfg: WireConfig):
        self.cfg = cfg

    def build_sync1(self, idx: int) -> bytes:
        rand = secrets.randbits(31)
        sync = ((rand & ~self.cfg.g3) | self.cfg.g2 | 0x80000001) & 0xFFFFFFFF
        body = struct.pack("<I", sync) + bytes([idx & 0xFF, HS_CMD_SYNC1])
        return body + b"\x00" * (SYNC1_SIZE - len(body))

    def build_sync2(self, idx: int, token: int, val: int) -> bytes:
        token_out = ((token & 0xFFFFFFFF00000000)
                     | ((token + self.cfg.g1) & 0xFFFFFFFF))
        body = (struct.pack("<I", self.cfg.g1) + bytes([idx & 0xFF, HS_CMD_SYNC2])
                + struct.pack("<QH", token_out, val & 0xFFFF))
        return body + b"\x00" * (SYNC2_SIZE - len(body))

    def build_heartbeat(self, idx: int) -> bytes:
        body = (struct.pack("<I", self.cfg.g1)
                + bytes([idx & 0xFF, HS_CMD_HEARTBEAT, 0xFF])
                + struct.pack("<I", HEARTBEAT_MARKER))
        return body + b"\x00" * (HEARTBEAT_SIZE - len(body))

    def parse(self, pkt: bytes) -> Optional[Dict[str, Any]]:
        if len(pkt) < 6:
            return None
        first = struct.unpack("<I", pkt[:4])[0]
        out: Dict[str, Any] = {
            "first_u32": first, "idx": pkt[4], "cmd": pkt[5],
            "is_handshake": self.cfg.is_handshake(first),
            "is_data": self.cfg.is_data(first),
        }
        if out["is_handshake"] and out["cmd"] in (HS_CMD_SYNC1, HS_CMD_SYNC2) and len(pkt) >= 16:
            out["token"] = struct.unpack("<Q", pkt[6:14])[0]
            out["val"] = struct.unpack("<H", pkt[14:16])[0]
        if out["is_handshake"] and out["cmd"] == HS_CMD_HI and len(pkt) >= 14:
            out["magic"] = struct.unpack("<Q", pkt[6:14])[0]
        return out


class MiniKCP:
    def __init__(self, conv: int, on_output, mss: int = IKCP_MSS):
        self.conv, self.on_output, self.mss = conv, on_output, mss
        self.snd_next = 0
        self.rcv_next = 0
        self.snd_buf: List[Dict[str, Any]] = []
        self.rcv_buf: Dict[int, Tuple[int, bytes]] = {}
        self.ready_msgs: List[bytes] = []
        self._pending: List[bytes] = []
        self._lock = threading.Lock()

    def send(self, msg: bytes) -> None:
        frags = [msg[i:i + self.mss] for i in range(0, len(msg), self.mss)] or [b""]
        with self._lock:
            for i, payload in enumerate(frags):
                self.snd_buf.append({"sn": self.snd_next,
                                     "frg": len(frags) - 1 - i,
                                     "data": payload,
                                     "sent_at": None, "rto": 0.3})
                self.snd_next += 1

    def _seg(self, cmd: int, frg: int, sn: int, payload: bytes) -> bytes:
        head = struct.pack("<IBBHIII", self.conv, cmd, frg, IKCP_WND,
                           int(time.monotonic() * 1000) & 0xFFFFFFFF,
                           sn, self.rcv_next)
        return head + struct.pack("<I", len(payload)) + payload

    def input(self, pkt: bytes) -> None:
        if len(pkt) < IKCP_HEADER:
            return
        conv, cmd, frg, wnd, ts, sn, una, ln = struct.unpack("<IBBHIIII", pkt[:IKCP_HEADER])
        if conv != self.conv:
            return
        with self._lock:
            self.snd_buf = [s for s in self.snd_buf if s["sn"] >= una]
            payload = pkt[IKCP_HEADER:IKCP_HEADER + ln]
            if cmd == IKCP_PUSH:
                if sn >= self.rcv_next:
                    self.rcv_buf.setdefault(sn, (frg, payload))
                self.on_output(self._seg(IKCP_ACK, 0, sn, b""))
            elif cmd == IKCP_ACK:
                self.snd_buf = [s for s in self.snd_buf if s["sn"] != sn]
            elif cmd == IKCP_WASK:
                self.on_output(self._seg(IKCP_WINS, 0, 0, b""))
            self._assemble()

    def _assemble(self) -> None:
        while self.rcv_next in self.rcv_buf:
            frg, payload = self.rcv_buf.pop(self.rcv_next)
            self._pending.append(payload)
            self.rcv_next += 1
            if frg == 0:
                self.ready_msgs.append(b"".join(self._pending))
                self._pending = []

    def recv(self) -> Optional[bytes]:
        with self._lock:
            return self.ready_msgs.pop(0) if self.ready_msgs else None

    def flush(self) -> None:
        with self._lock:
            now = time.monotonic()
            for seg in self.snd_buf:
                if seg["sent_at"] is None or now - seg["sent_at"] > seg["rto"]:
                    if seg["sent_at"] is not None:
                        seg["rto"] = min(seg["rto"] * 1.5, 5.0)
                    seg["sent_at"] = now
                    self.on_output(self._seg(IKCP_PUSH, seg["frg"], seg["sn"], seg["data"]))


def native_frame(frame_id: int, body: bytes = b"") -> bytes:
    return struct.pack("<I", 2 + len(body)) + struct.pack("<H", frame_id) + body


def parse_native_frame(data: bytes) -> Tuple[int, bytes]:
    if len(data) < 6:
        raise ValueError("frame too short")
    size = struct.unpack("<I", data[:4])[0]
    if size != len(data) - 4:
        raise ValueError(f"bad frame length: header={size}, actual={len(data) - 4}")
    return struct.unpack("<H", data[4:6])[0], data[6:]


def parse_session_seed(data: bytes) -> Dict[str, Any]:
    out = {"seed": 0, "crypto": 0}
    for no, wt, v in parse_fields(data):
        if no == 1 and wt == 0:
            out["seed"] = v
        elif no == 2 and wt == 0:
            out["crypto"] = v
    return out


def encrypt_string_message(ciphertext: bytes) -> bytes:
    return bytes_field(1, ciphertext)


def session_key_message(session_key: bytes, seed: int, crypto_mode: int) -> bytes:
    digest = hashlib.sha1(str(seed).encode("ascii") + session_key).digest()
    msg = (bytes_field(1, secrets.token_bytes(2))
           + bytes_field(2, session_key)
           + uvar_field(3, int.from_bytes(digest[:8], "big"))
           + bytes_field(4, secrets.token_bytes(9)))
    if crypto_mode >= 1:
        msg += uvar_field(5, crypto_mode)
    return msg


def connect_server_request(clientid: bytes) -> bytes:
    return uvar_field(2, REQ_NEW_CONNECTION) + bytes_field(3, clientid)


def parse_connect_reply(data: bytes) -> int:
    for no, wt, v in parse_fields(data):
        if no == 2 and wt == 0:
            return v
    raise ValueError("ConnectServerReply.type missing")


class NeoXClient:
    def __init__(self, host: str, port: int, *, salt: str = DEFAULT_SALT,
                 crypto_mode: int = DEFAULT_CRYPTO_MODE,
                 frame_base: int = 0,
                 public_key_pem: bytes = GATE_PUBLIC_KEY_PEM,
                 verbose: bool = False):
        self.peer = (host, port)
        self.salt = salt
        self.crypto_mode = crypto_mode
        self.frame_base = frame_base
        self.public_key_pem = public_key_pem
        self.verbose = verbose
        self.cfg = WireConfig()
        self.hs = HandshakeCodec(self.cfg)
        self.kcp = MiniKCP(self.cfg.g2, self._send_raw)
        self.session_key: Optional[bytes] = None
        self.send_stream: Optional[CryptoStream] = None
        self.recv_stream: Optional[CryptoStream] = None
        self.ctrl_queue: "queue.Queue[Tuple[int, bytes]]" = queue.Queue()
        self.frame_queue: "queue.Queue[bytes]" = queue.Queue()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.5)
        self.inbound: "queue.Queue[bytes]" = queue.Queue()
        self._alive = True
        self._threads: List[threading.Thread] = []
        self.idx = 0

    def _send_raw(self, data: bytes) -> None:
        self.sock.sendto(data, self.peer)

    def send_frame(self, frame: bytes) -> None:
        self.kcp.send(frame)
        self.kcp.flush()

    def send_ctrl(self, frame_id: int, payload: bytes = b"") -> None:
        self.send_frame(native_frame(frame_id, payload))

    def handshake(self, timeout: float = 8.0) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        self._send_raw(self.hs.build_sync1(self.idx))
        log("hs->", "sync-1 请求 (cmd=4, 48B)")
        token = val = None
        while time.monotonic() < deadline:
            pkt = self._recv_sock(deadline)
            info = self.hs.parse(pkt) if pkt else None
            if info and info.get("cmd") == HS_CMD_SYNC1 and "token" in info:
                token, val = info["token"], info["val"]
                break
        if token is None:
            raise TimeoutError("网关未回应 sync-1 (cmd=4)")
        log("hs<-", f"sync-1 应答 token=0x{token:016x}")
        self._send_raw(self.hs.build_sync2(self.idx, token, val))
        log("hs->", "sync-2 (cmd=9, 30B, token+G1)")
        while time.monotonic() < deadline:
            pkt = self._recv_sock(deadline)
            if pkt is None:
                continue
            first = struct.unpack("<I", pkt[:4])[0] if len(pkt) >= 4 else 0
            if self.cfg.is_data(first):
                log("hs<-", f"先于 hi 收到数据包 ({len(pkt)}B)")
                self.kcp.input(pkt)
                return {"token": token, "val": val}
            info = self.hs.parse(pkt)
            if info and info.get("cmd") == HS_CMD_HI:
                if info.get("magic") != KCP_CONNECT_HI_MAGIC:
                    raise ValueError(f"hi magic 不匹配: 0x{info.get('magic', 0):016x}")
                log("hs<-", "hi (cmd=0x7d, magic ok) -> KCP 会话已建立")
                return {"token": token, "val": val}
        raise TimeoutError("网关未发送 hi (cmd=0x7d)")

    def _recv_sock(self, deadline: float) -> Optional[bytes]:
        remain = deadline - time.monotonic()
        if remain <= 0:
            return None
        self.sock.settimeout(min(0.5, remain))
        try:
            pkt, _ = self.sock.recvfrom(4096)
            return pkt
        except socket.timeout:
            return None

    def start_io(self) -> None:
        def reader():
            self.sock.settimeout(0.5)
            while self._alive:
                try:
                    pkt, _ = self.sock.recvfrom(4096)
                except (OSError, socket.timeout):
                    if self._alive:
                        continue
                    return
                self.inbound.put(pkt)

        def dispatch():
            while self._alive:
                try:
                    pkt = self.inbound.get(timeout=0.5)
                except queue.Empty:
                    continue
                if len(pkt) < 4:
                    continue
                first = struct.unpack("<I", pkt[:4])[0]
                if self.cfg.is_data(first):
                    self.kcp.input(pkt)
                    msg = self.kcp.recv()
                    while msg is not None:
                        self._on_kcp_message(msg)
                        msg = self.kcp.recv()
                elif not self.cfg.is_handshake(first) and self.verbose:
                    log("raw<-", f"invalid magic 0x{first:08x}")

        def updater():
            last_hb = time.monotonic()
            while self._alive:
                self.kcp.flush()
                if time.monotonic() - last_hb > 10.0:
                    last_hb = time.monotonic()
                    self._send_raw(self.hs.build_heartbeat(self.idx))
                    log("hb->", "心跳 (cmd=0)")
                time.sleep(IKCP_INTERVAL)

        for target in (reader, dispatch, updater):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def _on_kcp_message(self, msg: bytes) -> None:
        try:
            frame_id, payload = parse_native_frame(msg)
        except ValueError:
            log("rpc<-", f"坏帧: {msg[:32].hex()}")
            return
        if frame_id == FRAME_ID_ENTITY_METHOD:
            if self.recv_stream is None:
                log("rpc<-", "加密帧但会话密钥未就绪")
                return
            self.frame_queue.put(self.recv_stream.update(payload))
        else:
            self.ctrl_queue.put((frame_id, payload))

    def stop(self) -> None:
        self._alive = False
        try:
            self.sock.close()
        except OSError:
            pass


def run_rename(host: str, port: int, nickname: str, token: str, sdkuid: str,
               *, salt: str = DEFAULT_SALT, crypto_mode: int = DEFAULT_CRYPTO_MODE,
               frame_base: int = 0, public_key_pem: bytes = GATE_PUBLIC_KEY_PEM,
               verbose: bool = False) -> Dict[str, Any]:
    cl = NeoXClient(host, port, salt=salt, crypto_mode=crypto_mode,
                    frame_base=frame_base, public_key_pem=public_key_pem,
                    verbose=verbose)
    result: Dict[str, Any] = {"steps": []}
    try:
        hs = cl.handshake()
        result["steps"].append({"step": "udp_handshake", **hs})
        cl.start_io()
        fb = frame_base
        cl.send_ctrl(fb)
        fid, payload = _ctrl(cl, "seed_reply", fb)
        seed_info = parse_session_seed(payload)
        seed = seed_info["seed"]
        log("rpc<-", f"seed_reply seed={seed} crypto={seed_info['crypto']}")
        result["steps"].append({"step": "seed", "seed": seed,
                                "crypto": seed_info["crypto"]})
        session_key = secrets.token_bytes(32)
        sk_msg = session_key_message(session_key, seed,
                                     seed_info["crypto"] or crypto_mode)
        cl.send_ctrl(fb + 1, encrypt_string_message(
            rsa_oaep_encrypt(public_key_pem, sk_msg)))
        fid, payload = _ctrl(cl, "session_key_ok", fb + 1)
        cl.session_key = session_key
        cl.send_stream = CryptoStream(cl.crypto_mode, session_key, encrypt=True)
        cl.recv_stream = CryptoStream(cl.crypto_mode, session_key, encrypt=False)
        result["steps"].append({"step": "session_key", "status": "ok"})
        clientid = secrets.token_hex(8)
        cl.send_ctrl(fb + 2, connect_server_request(clientid.encode()))
        fid, payload = _ctrl(cl, "connect_reply", fb + 2)
        reply_type = parse_connect_reply(payload)
        if reply_type != REPLY_CONNECTED:
            raise RuntimeError(f"connect_reply 被拒: type={reply_type}")
        result["steps"].append({"step": "connect_server", "type": reply_type,
                                "clientid": clientid})
        log("rpc<-", "connect_reply (connected)")
        login = rpc_inner_frame("loginWithAuthJson",
                                [sauth_json_string(token, sdkuid)], salt=salt)
        cl.send_frame(native_frame(FRAME_ID_ENTITY_METHOD,
                                   cl.send_stream.update(login)))
        reply = decode_inner_frame(cl.frame_queue.get(timeout=8.0))
        result["steps"].append({"step": "loginWithAuthJson", "reply": reply})
        logged_in = bool(reply["args"] and reply["args"][0] is True)
        if not logged_in:
            raise RuntimeError(f"登录失败: {reply['args']}")
        rename = rpc_inner_frame("set_nickname", [nickname], salt=salt)
        cl.send_frame(native_frame(FRAME_ID_ENTITY_METHOD,
                                   cl.send_stream.update(rename)))
        reply2 = decode_inner_frame(cl.frame_queue.get(timeout=8.0))
        result["steps"].append({"step": "set_nickname", "reply": reply2})
        result["login_ok"] = True
        result["rename_ok"] = bool(reply2["args"] and reply2["args"][0] is True)
        result["nickname"] = nickname
        return result
    finally:
        cl.stop()


def _ctrl(cl: NeoXClient, expect: str, want_id: int, timeout: float = 8.0) -> Tuple[int, bytes]:
    try:
        fid, payload = cl.ctrl_queue.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError(f"网关未应答 {expect}") from None
    if fid != want_id:
        log("rpc<-", f"帧 id 0x{fid:04x} 与预期 0x{want_id:04x} 不符（可试 --frame-base 调整）")
    return fid, payload


def run_probe(host: str, port: int) -> None:
    cfg = WireConfig()
    hs = HandshakeCodec(cfg)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3.0)
    print(f"probe udp://{host}:{port}")
    p1 = hs.build_sync1(0)
    print(f"-> sync-1 (cmd=4, {len(p1)}B): {p1.hex()}")
    sock.sendto(p1, (host, port))
    try:
        pkt, addr = sock.recvfrom(4096)
        print(f"<- {len(pkt)}B from {addr}: {pkt.hex()}")
        info = hs.parse(pkt)
        print(f"   解码: {info}")
        if info and info.get("cmd") == HS_CMD_SYNC1 and "token" in info:
            p2 = hs.build_sync2(0, info["token"], info["val"])
            print(f"-> sync-2 (cmd=9, {len(p2)}B): {p2.hex()}")
            sock.sendto(p2, (host, port))
            for _ in range(3):
                try:
                    pkt, _ = sock.recvfrom(4096)
                except socket.timeout:
                    break
                print(f"<- {len(pkt)}B: {pkt.hex()}")
                print(f"   解码: {hs.parse(pkt)}")
    except socket.timeout:
        print("<- 超时（sync-1 无应答：地址不对 / 网关未开 / magic 被改）")
    sock.close()


def cmd_self_test() -> None:
    cfg = WireConfig()
    hs = HandshakeCodec(cfg)
    p1 = struct.pack("<I", G1_DEFAULT) + bytes([0, HS_CMD_SYNC1]) + b"\x00" * 42
    assert len(hs.build_sync1(0)) == SYNC1_SIZE
    p2 = hs.build_sync2(0, 0x1122334455667788, 0x1234)
    tok = struct.unpack("<Q", p2[6:14])[0]
    assert len(p2) == SYNC2_SIZE and p2[5] == HS_CMD_SYNC2
    assert (tok & 0xFFFFFFFF) == (0x55667788 + G1_DEFAULT) & 0xFFFFFFFF
    assert (tok >> 32) == 0x11223344
    hb = hs.build_heartbeat(0)
    assert hb[5] == 0 and hb[6] == 0xFF
    assert struct.unpack("<I", hb[7:11])[0] == HEARTBEAT_MARKER
    f = native_frame(0x8000, b"\x01\x02\x03")
    assert f == bytes.fromhex("050000000080010203"), f.hex()
    fid, body = parse_native_frame(f)
    assert fid == 0x8000 and body == b"\x01\x02\x03"
    wire: List[bytes] = []
    acks: List[bytes] = []
    a = MiniKCP(G2_DEFAULT, wire.append)
    b = MiniKCP(G2_DEFAULT, acks.append)
    msg = b"x" * 2500
    a.send(msg)
    a.flush()
    assert all(seg[4] == IKCP_PUSH for seg in wire)
    for seg in wire:
        b.input(seg)
    assert b.recv() == msg
    assert acks and all(seg[4] == IKCP_ACK for seg in acks)
    for ack in acks:
        a.input(ack)
    assert not a.snd_buf
    assert rpc_index("set_nickname") == 1648625260
    assert rpc_index("on_set_nickname") == 447905912
    assert rpc_index("on_become_player") == 405156285
    seed_msg = uvar_field(1, 12345) + uvar_field(2, 1)
    assert parse_session_seed(seed_msg) == {"seed": 12345, "crypto": 1}
    assert parse_connect_reply(uvar_field(2, REPLY_CONNECTED)) == REPLY_CONNECTED
    key = secrets.token_bytes(32)
    for mode in (0, 1, 2):
        enc = CryptoStream(mode, key, encrypt=True)
        dec = CryptoStream(mode, key, encrypt=False)
        data = secrets.token_bytes(100)
        assert dec.update(enc.update(data)) == data
    frame = rpc_inner_frame("set_nickname", ["测试"], salt=DEFAULT_SALT)
    decoded = decode_inner_frame(frame)
    assert decoded["method_index"] == rpc_index("set_nickname")
    assert decoded["args"] == ["测试"]
    print("self-test: OK")


def main() -> int:
    ap = argparse.ArgumentParser(description="NeoX KCP 长连接改名客户端（单文件版）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-test").set_defaults(func=lambda a: cmd_self_test())
    p = sub.add_parser("probe", help="探测网关握手")
    p.add_argument("host")
    p.add_argument("port", type=int)
    p.set_defaults(func=lambda a: run_probe(a.host, a.port))
    p = sub.add_parser("client", help="登录 + 改名")
    p.add_argument("--host", required=True, help="网关 IP")
    p.add_argument("--port", type=int, required=True, help="网关端口")
    p.add_argument("--nickname", required=True, help="新昵称")
    p.add_argument("--token", required=True, help="CK 中的 accesstoken")
    p.add_argument("--sdkuid", default="", help="CK 中的 sdkuid")
    p.add_argument("--salt", default=DEFAULT_SALT, help="RpcIndex salt（默认 0）")
    p.add_argument("--crypto-mode", type=int, default=DEFAULT_CRYPTO_MODE,
                   help="0=RC4 1=AES-CFB128 2=AES-OFB128")
    p.add_argument("--frame-base", type=int, default=0,
                   help="seed_request 帧 id；session_key/connect 用 base+1/base+2")
    p.add_argument("--public-key-pem", default="",
                   help="网关公钥 PEM 文件（默认用内嵌公钥）")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=lambda a: print(json.dumps(run_rename(
        a.host, a.port, a.nickname, a.token, a.sdkuid,
        salt=a.salt, crypto_mode=a.crypto_mode, frame_base=a.frame_base,
        public_key_pem=open(a.public_key_pem, "rb").read() if a.public_key_pem else GATE_PUBLIC_KEY_PEM,
        verbose=a.verbose), ensure_ascii=False, indent=2)))
    args = ap.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
