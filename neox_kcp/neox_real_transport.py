#!/usr/bin/env python3
"""NeoX real-UDP/KCP transport research client and mock gate.

Outer wire format recovered from libclient.so (Capstone static analysis,
see 游戏逆向研究总档案.txt sections 25/26/29/30):

  set_kcp_sync_magic(magic, mask)  @0x1fc0cb4
    G1 = magic | 0x80000001   (default 0xe88dafb3)  -> first u32 of handshake packets
    G2 = magic | 0x80000000   (default 0xe88dafb2)  -> KCP conv of data packets
    G3 = mask | 1             (file default 0xfffffffe)

  Handshake control packet  (client -> server, first u32 == G1):
    +0x00 u32  sync = (rand & ~G3) | G2 | 0x80000001   == G1 with defaults
    +0x04 u8   idx  (echo channel byte, from this+0x2ac)
    +0x05 u8   cmd
    +0x06 ...  payload
    cmd = 4   sync-1 request, 48 bytes total (this+0x284 = 0x30), zero filled
    cmd = 9   sync-2, 30 bytes total: u64 token @+6 (low32 += G1), u16 @+0e
    cmd = 0   heartbeat: 0xff @+6, u32 0xe4b868b9 @+7, 48 bytes
    server sync-1 reply (cmd=4): u64 token @+6, u16 @+0e  (>=16 bytes)
    server hi (cmd=0x7d) carries magic 0x8fafd21e25c5e09b (handle_connect_hi
    @0x214c2f0) after which the KCP session is created.

  KCP data packets: first u32 == G2 (dispatcher @0x206ba84 rejects anything
  else as "invalid magic"), then standard ikcp segment header:
    conv u32 | cmd u8 (81 push/82 ack/83 wask/84 wins) | frg u8 | wnd u16
    | ts u32 | sn u32 | una u32 | len u32   (24 bytes)

Business frame layout (CONFIRMED from libclient.so static analysis):
  generic frame sender 0x1ff39d8 (buffer, message, frame_id):
    writes [u32 len][u16 frame_id] header then the serialized protobuf body;
  entity frame builder 0x1fdc140 does the same with frame_id = 0x8000 and
  len = total_size - 4 (the u32 counts every byte after itself, including
  the 2 id bytes). Mobile handshake RPC frame ids (send_seed_request,
  send_session_key, send_connect_server, ...) are runtime indices into the
  message-type registry built from client_gate.proto (init @0x21a55fc,
  48-byte entries, index = (descriptor - base)/48); the registration order
  follows the proto file's message order. The defaults below assume that
  order and stay overridable via --frame-base for live calibration.

Business layer (confirmed inner framing from script analysis):
  uint32_le(len) + uint16_le(0x8000) + AreaMessage, one KCP message each.

Usage:
  python3 neox_real_transport.py self-test
  python3 neox_real_transport.py server --port 30001
  python3 neox_real_transport.py client --host 127.0.0.1 --port 30001 \
      --nickname 新名字 --token LOGIN_TOKEN --sdkuid 10086
  python3 neox_real_transport.py probe 1.2.3.4 30001   # real-server calibration
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import secrets
import socket
import struct
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from neox_rename_protocol_replay import (
    CryptoStream,
    DEFAULT_CRYPTO_MODE,
    DEFAULT_SALT,
    KCP_CONNECT_HI_MAGIC,
    known_indices,
    rpc_index,
    make_random_session_material,
    rsa_oaep_decrypt,
    rsa_oaep_encrypt,
    parse_encrypt_string,
    parse_session_key_message,
    seed_session_digest,
    digest64,
    public_pem_from_private,
    generate_demo_private_key,
    seal_payload,
    open_payload,
    callback_payload,
    decode_inner_frame,
    inner_frame,
    rename_inner_frame,
    rpc_inner_frame,
    sauth_json_string,
    uvar_field,
    bytes_field,
    OLD_LOGIN_PUBLIC_KEY_PEM,
)

# ---------------------------------------------------------------------------
# Wire constants recovered from libclient.so
# ---------------------------------------------------------------------------
SYNC_MAGIC_DEFAULT = 0x688DAFB2          # magic value whose |0x80000001 == G1 file default
G1_DEFAULT = 0xE88DAFB3                  # magic | 0x80000001 (handshake first u32)
G2_DEFAULT = 0xE88DAFB2                  # magic | 0x80000000 (KCP conv)
MASK_DEFAULT = 0xFFFFFFFE                # sync mask (file default)
HEARTBEAT_MARKER = 0xE4B868B9            # heartbeat constant @0x214d7e4
KCP_CONV = G2_DEFAULT                    # data-phase conv (see dispatcher 0x206ba84)

HS_CMD_SYNC1 = 0x04                      # sync request / reply
HS_CMD_SYNC2 = 0x09                      # second sync (token echo, +G1)
HS_CMD_HEARTBEAT = 0x00                  # keepalive, carries 0xff + marker
HS_CMD_HI = 0x7D                         # server "hi": creates the KCP session

SYNC1_SIZE = 48                          # this+0x284 = 0x30
SYNC2_SIZE = 30                          # mov w2, #0x1e
HEARTBEAT_SIZE = 48

IKCP_PUSH = 81
IKCP_ACK = 82
IKCP_WASK = 83
IKCP_WINS = 84
IKCP_HEADER = 24
IKCP_MSS = 1200
IKCP_WND = 32


def log(tag: str, msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}", file=sys.stderr, flush=True)


def hexdump(data: bytes, limit: int = 64) -> str:
    s = data[:limit].hex()
    return s + ("..." if len(data) > limit else "")


class WireConfig:
    """Runtime mirror of the native sync-magic globals."""

    def __init__(self, magic: int = SYNC_MAGIC_DEFAULT, mask: int = MASK_DEFAULT):
        self.set_kcp_sync_magic(magic, mask)

    def set_kcp_sync_magic(self, magic: int, mask: int) -> None:
        # native: G1 = magic|0x80000001; G2 = G1 & ~1; G3 = mask|1
        self.g1 = (magic | 0x80000001) & 0xFFFFFFFF
        self.g2 = (self.g1 & 0xFFFFFFFE) & 0xFFFFFFFF
        self.g3 = (mask | 1) & 0xFFFFFFFF

    def is_handshake(self, first_u32: int) -> bool:
        return ((first_u32 ^ self.g1) & self.g3) == 0

    def is_data(self, first_u32: int) -> bool:
        return first_u32 == self.g2


# ---------------------------------------------------------------------------
# Handshake packet codec (byte layout from so)
# ---------------------------------------------------------------------------
class HandshakeCodec:
    def __init__(self, cfg: WireConfig):
        self.cfg = cfg

    def build_sync1(self, idx: int, rand: Optional[int] = None) -> bytes:
        # 0x214d8xx: w8 = (rand & ~G3) | G2 | 0x80000001; cmd=4; size 48
        if rand is None:
            rand = secrets.randbits(31)
        sync = ((rand & ~self.cfg.g3) | self.cfg.g2 | 0x80000001) & 0xFFFFFFFF
        body = struct.pack("<I", sync) + bytes([idx & 0xFF, HS_CMD_SYNC1])
        return body + b"\x00" * (SYNC1_SIZE - len(body))

    def build_sync2(self, idx: int, token: int, val: int) -> bytes:
        # 0x214d214: u64 this+0x278 @+6, u16 this+0x280 @+0e, cmd=9, 30 bytes
        token_out = ((token & 0xFFFFFFFF00000000)
                     | ((token + self.cfg.g1) & 0xFFFFFFFF))
        body = (struct.pack("<I", self.cfg.g1) + bytes([idx & 0xFF, HS_CMD_SYNC2])
                + struct.pack("<QH", token_out, val & 0xFFFF))
        return body + b"\x00" * (SYNC2_SIZE - len(body))

    def build_heartbeat(self, idx: int) -> bytes:
        # 0x214d7e0: halfword 0xff00 @+5 (bytes 00 ff), u32 0xe4b868b9 @+7
        body = (struct.pack("<I", self.cfg.g1) + bytes([idx & 0xFF, HS_CMD_HEARTBEAT, 0xFF])
                + struct.pack("<I", HEARTBEAT_MARKER))
        return body + b"\x00" * (HEARTBEAT_SIZE - len(body))

    def build_hi(self, idx: int, magic: int = KCP_CONNECT_HI_MAGIC) -> bytes:
        body = (struct.pack("<I", self.cfg.g1) + bytes([idx & 0xFF, HS_CMD_HI])
                + struct.pack("<Q", magic))
        return body + b"\x00" * (SYNC1_SIZE - len(body))

    def parse(self, pkt: bytes) -> Optional[Dict[str, Any]]:
        """Mirror of the native dispatcher @0x206ba84."""
        if len(pkt) < 6:
            return None
        first = struct.unpack("<I", pkt[:4])[0]
        out: Dict[str, Any] = {
            "first_u32": first,
            "idx": pkt[4],
            "cmd": pkt[5],
            "is_handshake": self.cfg.is_handshake(first),
            "is_data": self.cfg.is_data(first),
        }
        if out["is_handshake"] and out["cmd"] in (HS_CMD_SYNC1, HS_CMD_SYNC2) and len(pkt) >= 16:
            out["token"] = struct.unpack("<Q", pkt[6:14])[0]
            out["val"] = struct.unpack("<H", pkt[14:16])[0]
        if out["is_handshake"] and out["cmd"] == HS_CMD_HI and len(pkt) >= 14:
            out["magic"] = struct.unpack("<Q", pkt[6:14])[0]
        return out


# ---------------------------------------------------------------------------
# Minimal wire-compatible KCP (ikcp segment format)
# ---------------------------------------------------------------------------
class MiniKCP:
    """Standard ikcp segment framing with a simple reliable-ARQ engine.

    Segment: conv u32 | cmd u8 | frg u8 | wnd u16 | ts u32 | sn u32 | una u32
    | len u32. Push fragments are acked individually and cumulatively via
    una; retransmission uses a plain RTO timer. This is sufficient to carry
    framed messages with a real ikcp peer that tolerates a simple client.
    """

    def __init__(self, conv: int, on_output, mss: int = IKCP_MSS):
        self.conv = conv
        self.on_output = on_output
        self.mss = mss
        self.snd_next = 0
        self.rcv_next = 0
        self.snd_buf: List[Dict[str, Any]] = []
        self.rcv_buf: Dict[int, Tuple[int, bytes]] = {}
        self.delivered: List[Tuple[int, bytes]] = []  # (frg, payload) in order
        self.ready_msgs: List[bytes] = []
        self._pending_msg: List[bytes] = []
        self.rto = 0.3
        self._lock = threading.Lock()

    # -- send ---------------------------------------------------------------
    def send(self, msg: bytes) -> None:
        frags = [msg[i:i + self.mss] for i in range(0, len(msg), self.mss)] or [b""]
        with self._lock:
            for i, payload in enumerate(frags):
                self.snd_buf.append({
                    "sn": self.snd_next,
                    "frg": len(frags) - 1 - i,
                    "data": payload,
                    "ts": time.monotonic(),
                    "sent": False,
                })
                self.snd_next += 1

    def _seg(self, cmd: int, frg: int, sn: int, payload: bytes) -> bytes:
        head = struct.pack(
            "<IBBHIII",
            self.conv, cmd, frg, IKCP_WND,
            int(time.monotonic() * 1000) & 0xFFFFFFFF,
            sn, self.rcv_next,
        )
        return head + struct.pack("<I", len(payload)) + payload

    # -- receive ------------------------------------------------------------
    def input(self, pkt: bytes) -> None:
        if len(pkt) < IKCP_HEADER:
            return
        conv, cmd, frg, wnd, ts, sn, una, ln = struct.unpack("<IBBHIIII", pkt[:IKCP_HEADER])
        if conv != self.conv:
            return
        with self._lock:
            # process una: drop acked segments
            self.snd_buf = [s for s in self.snd_buf if s["sn"] >= una]
            payload = pkt[IKCP_HEADER:IKCP_HEADER + ln]
            if cmd == IKCP_PUSH:
                self.rcv_buf.setdefault(sn, (frg, payload))
            elif cmd == IKCP_ACK:
                self.snd_buf = [s for s in self.snd_buf if s["sn"] != sn]
            elif cmd == IKCP_WASK:
                pass  # handled in flush: emit WINS
            self._assemble()

    def _assemble(self) -> None:
        while self.rcv_next in self.rcv_buf:
            frg, payload = self.rcv_buf.pop(self.rcv_next)
            self._pending_msg.append(payload)
            self.rcv_next += 1
            if frg == 0:
                self.ready_msgs.append(b"".join(self._pending_msg))
                self._pending_msg = []

    def recv(self) -> Optional[bytes]:
        with self._lock:
            return self.ready_msgs.pop(0) if self.ready_msgs else None

    # -- pump ---------------------------------------------------------------
    def flush(self) -> None:
        with self._lock:
            now = time.monotonic()
            for seg in self.snd_buf:
                if not seg["sent"] or now - seg["ts"] > self.rto:
                    seg["ts"] = now
                    seg["sent"] = True
                    self.on_output(self._seg(IKCP_PUSH, seg["frg"], seg["sn"], seg["data"]))
                    self.on_output(self._seg(IKCP_ACK, 0, seg["sn"], b""))  # piggyback-ish
            if self.snd_buf:
                self.rto = min(self.rto * 1.5, 5.0)

    def ack_pending(self) -> None:
        with self._lock:
            for sn in list(self.rcv_buf.keys()):
                self.on_output(self._seg(IKCP_ACK, 0, sn, b""))
            if self.rcv_buf:
                self.on_output(self._seg(IKCP_WINS, 0, 0, b""))


# ---------------------------------------------------------------------------
# Business framing inside the KCP channel (native layout from 0x1ff39d8):
#   [u32 len-4][u16 frame_id][body]  - len counts bytes after the u32 itself.
# ---------------------------------------------------------------------------
FRAME_ID_ENTITY_METHOD = 0x8000  # confirmed (entity builder 0x1fdc140)

# Mobile handshake RPC frame ids: indices into the client_gate.proto message
# registry (init @0x21a55fc). Sequential defaults assuming proto message
# order EncryptString, SessionSeed, SessionKey, ...; calibrate against a live
# gate with --frame-base / per-id overrides if needed.
FRAME_ID_SEED_REQUEST = 1
FRAME_ID_SEED_REPLY = 2
FRAME_ID_SESSION_KEY = 3
FRAME_ID_SESSION_KEY_OK = 4
FRAME_ID_CONNECT_SERVER = 5
FRAME_ID_CONNECT_REPLY = 6


def native_frame(frame_id: int, body: bytes = b"") -> bytes:
    """Byte-exact layout of libclient.so's frame sender (0x1ff39d8)."""
    return struct.pack("<I", 2 + len(body)) + struct.pack("<H", frame_id) + body


def parse_native_frame(data: bytes) -> Tuple[int, bytes]:
    """Inverse of native_frame; raises on short/length-mismatched input."""
    if len(data) < 6:
        raise ValueError("frame too short")
    size = struct.unpack("<I", data[:4])[0]
    if size != len(data) - 4:
        raise ValueError(f"bad frame length: header={size}, actual={len(data) - 4}")
    return struct.unpack("<H", data[4:6])[0], data[6:]


class BusinessLayer:
    """seed/session-key handshake + login-token + rename over any frame channel."""

    def __init__(self, public_key_pem: bytes, crypto_mode: int = DEFAULT_CRYPTO_MODE,
                 salt: str = DEFAULT_SALT):
        self.public_key_pem = public_key_pem
        self.crypto_mode = crypto_mode
        self.salt = salt
        self.session_key: Optional[bytes] = None
        self.send_stream: Optional[CryptoStream] = None
        self.recv_stream: Optional[CryptoStream] = None
        self.reply_queue: "queue.Queue[Tuple[int, bytes]]" = queue.Queue()
        self.index_to_name = {v: k for k, v in known_indices(salt).items()}
        self.index_to_name[rpc_index("loginWithAuthJson", salt)] = "loginWithAuthJson"

    # client side -------------------------------------------------------------
    def build_seed_request(self) -> bytes:
        return native_frame(FRAME_ID_SEED_REQUEST)

    def build_session_key(self, seed: int) -> Tuple[bytes, bytes]:
        material = make_random_session_material(
            seed=seed, session_key_hex="", crypto_mode=self.crypto_mode,
            digest_layout="seed-key", session_layout="key-in-field2",
        )
        encrypted = rsa_oaep_encrypt(self.public_key_pem, material["session_key_message"])
        self.session_key = material["session_key"]
        return native_frame(FRAME_ID_SESSION_KEY, encrypted), material["session_key"]

    def build_connect_server(self, clientid: str) -> bytes:
        return native_frame(FRAME_ID_CONNECT_SERVER, uvar_field(1, 0) + bytes_field(2, clientid.encode()))

    def build_encrypted_rpc(self, frame: bytes) -> bytes:
        assert self.send_stream is not None
        return native_frame(FRAME_ID_ENTITY_METHOD, self.send_stream.update(frame))

    # both sides ----------------------------------------------------------------
    def enable_crypto(self, session_key: bytes) -> None:
        self.session_key = session_key
        self.send_stream = CryptoStream(self.crypto_mode, session_key, encrypt=True)
        self.recv_stream = CryptoStream(self.crypto_mode, session_key, encrypt=False)

    def feed_frame(self, data: bytes) -> Optional[bytes]:
        """Route one native frame; returns a decrypted business frame for
        encrypted entity frames, otherwise queues the control reply."""
        frame_id, payload = parse_native_frame(data)
        if frame_id == FRAME_ID_ENTITY_METHOD:
            assert self.recv_stream is not None
            return self.recv_stream.update(payload)
        self.reply_queue.put((frame_id, payload))
        return None


# ---------------------------------------------------------------------------
# Transport endpoints
# ---------------------------------------------------------------------------
class UdpTransport:
    """Handshake state machine + KCP session + business layer over a send hook."""

    def __init__(self, send_fn, cfg: WireConfig,
                 is_server: bool, public_key_pem: bytes, private_key_pem: bytes,
                 crypto_mode: int = DEFAULT_CRYPTO_MODE, verbose: bool = True):
        self.send_fn = send_fn
        self.cfg = cfg
        self.is_server = is_server
        self.hs = HandshakeCodec(cfg)
        self.biz = BusinessLayer(public_key_pem, crypto_mode)
        self.private_key_pem = private_key_pem
        self.verbose = verbose
        self.kcp = MiniKCP(KCP_CONV, self._kcp_output)
        self.idx = 0
        self.hi_seen = threading.Event()
        self.frames_in: "queue.Queue[bytes]" = queue.Queue()
        self._alive = True
        self._threads: List[threading.Thread] = []
        self.server_state: Dict[str, Any] = {}  # mock-gate side session info

    def _kcp_output(self, seg: bytes) -> None:
        self.send_fn(seg)
        if self.verbose:
            log("kcp->", f"{len(seg)}B seg: {hexdump(seg, 40)}")

    # -- client handshake -----------------------------------------------------
    def client_handshake(self, recv_fn, timeout: float = 8.0) -> Dict[str, Any]:
        """recv_fn() -> bytes blocks for the next datagram from the gate."""
        deadline = time.monotonic() + timeout
        token = val = None
        # stage 1: sync-1 request
        self.send_fn(self.hs.build_sync1(self.idx))
        log("hs->", "sync-1 request (cmd=4, 48B)")
        while time.monotonic() < deadline:
            pkt = recv_fn()
            info = self._dispatch_raw(pkt)
            if info and info.get("cmd") == HS_CMD_SYNC1 and "token" in info:
                token, val = info["token"], info["val"]
                break
        if token is None:
            raise TimeoutError("no sync-1 reply (cmd=4 token) from gate")
        log("hs<-", f"sync-1 reply token=0x{token:016x} val={val}")

        # stage 2: sync-2 (token echo with low32 += G1)
        self.send_fn(self.hs.build_sync2(self.idx, token, val))
        log("hs->", "sync-2 (cmd=9, 30B, token+G1)")

        # stage 3: wait for hi (cmd=0x7d + magic) -> KCP data phase
        while time.monotonic() < deadline:
            pkt = recv_fn()
            first = struct.unpack("<I", pkt[:4])[0] if len(pkt) >= 4 else 0
            if self.cfg.is_data(first):
                self.hi_seen.set()
                log("hs<-", f"data packet before hi (conv ok), {len(pkt)}B")
                self.kcp.input(pkt)
                break
            info = self._dispatch_raw(pkt)
            if info and info.get("cmd") == HS_CMD_HI:
                if info.get("magic") != KCP_CONNECT_HI_MAGIC:
                    raise ValueError(f"bad hi magic: 0x{info.get('magic', 0):016x}")
                self.hi_seen.set()
                log("hs<-", "hi (cmd=0x7d, magic ok) -> KCP session created")
                break
        if not self.hi_seen.is_set():
            raise TimeoutError("no hi (cmd=0x7d) from gate")
        return {"token": token, "val": val}

    # -- server handshake -------------------------------------------------------
    def server_handshake(self, first_pkt: bytes, recv_fn) -> None:
        info = self.hs.parse(first_pkt)
        assert info and info["is_handshake"] and info["cmd"] == HS_CMD_SYNC1
        self.idx = info["idx"]
        token = secrets.randbits(63) | (1 << 62)
        val = secrets.randbits(15)
        self.server_state.update({"token": token, "val": val})
        reply = (struct.pack("<I", self.cfg.g1) + bytes([self.idx, HS_CMD_SYNC1])
                 + struct.pack("<QH", token, val))
        self.send_fn(reply)
        log("hs->", f"sync-1 reply token=0x{token:016x}")
        # wait sync-2
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            pkt = recv_fn()
            info = self.hs.parse(pkt)
            if info and info["cmd"] == HS_CMD_SYNC2:
                expect_lo = (self.server_state["token"] + self.cfg.g1) & 0xFFFFFFFF
                got_lo = info.get("token", 0) & 0xFFFFFFFF
                log("hs<-", f"sync-2 token_lo=0x{got_lo:08x} expect=0x{expect_lo:08x} "
                           f"({'ok' if got_lo == expect_lo else 'MISMATCH'})")
                self.send_fn(self.hs.build_hi(self.idx))
                log("hs->", "hi (cmd=0x7d, magic)")
                self.hi_seen.set()
                return
            self._dispatch_raw(pkt)

    # -- packet pump -------------------------------------------------------------
    def _dispatch_raw(self, pkt: bytes) -> Optional[Dict[str, Any]]:
        if len(pkt) < 4:
            return None
        first = struct.unpack("<I", pkt[:4])[0]
        if self.cfg.is_handshake(first):
            info = self.hs.parse(pkt)
            if self.verbose:
                log("hs<-", f"{len(pkt)}B {info}")
            return info
        if self.cfg.is_data(first):
            self.kcp.input(pkt)
            msg = self.kcp.recv()
            while msg is not None:
                self._on_kcp_message(msg)
                msg = self.kcp.recv()
            return {"data": True}
        if self.verbose:
            log("raw<-", f"invalid magic 0x{first:08x}: {hexdump(pkt)}")
        return None

    def _on_kcp_message(self, msg: bytes) -> None:
        try:
            frame = self.biz.feed_frame(msg)
        except ValueError:
            log("rpc<-", f"bad native frame: {hexdump(msg)}")
            return
        if frame is not None:
            self.frames_in.put(frame)

    def send_frame(self, frame: bytes) -> None:
        """Send one pre-built native frame as one KCP message."""
        self.kcp.send(frame)
        self.kcp.flush()

    def send_ctrl(self, frame_id: int, payload: bytes = b"") -> None:
        self.send_frame(native_frame(frame_id, payload))

    def start_io(self, feed_fn=None) -> None:
        """feed_fn(pkt) -> Optional[bytes]: pull inbound packets (None = poll)."""
        def reader():
            while self._alive:
                pkt = feed_fn() if feed_fn else None
                if pkt is None:
                    time.sleep(0.005)
                    continue
                self._dispatch_raw(pkt)

        def updater():
            last_hb = time.monotonic()
            while self._alive:
                self.kcp.flush()
                self.kcp.ack_pending()
                if self.is_server:
                    self._server_pump()
                if time.monotonic() - last_hb > 10.0:
                    last_hb = time.monotonic()
                    if not self.is_server:
                        self.send_fn(self.hs.build_heartbeat(self.idx))
                        log("hb->", "heartbeat (cmd=0)")
                time.sleep(0.02)  # kcp_interval=20ms from network_config

        for target in (reader, updater):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._alive = False

    # -- mock-gate business logic (server side) -----------------------------------
    def _server_pump(self) -> None:
        try:
            frame_id, payload = self.biz.reply_queue.get_nowait()
        except queue.Empty:
            return
        if frame_id == FRAME_ID_SEED_REQUEST:
            seed = secrets.randbits(63)
            self.server_state["seed"] = seed
            self.send_ctrl(FRAME_ID_SEED_REPLY, seed.to_bytes(8, "little"))
            log("rpc->", "seed_reply")
        elif frame_id == FRAME_ID_SESSION_KEY:
            session_msg = rsa_oaep_decrypt(self.private_key_pem, payload)
            fields = parse_session_key_message(session_msg)
            session_key = bytes.fromhex(fields["field2_hex"])
            digest_ok = fields.get("field3") == digest64(
                seed_session_digest(self.server_state["seed"], session_key, "seed-key"))
            self.server_state["digest_ok"] = digest_ok
            # the client negotiates the stream cipher in SessionKey.field5
            negotiated = int(fields.get("field5", 0))
            self.biz.crypto_mode = negotiated
            self.biz.enable_crypto(session_key)
            self.send_ctrl(FRAME_ID_SESSION_KEY_OK)
            log("rpc->", f"session_key_ok (digest {'ok' if digest_ok else 'BAD'}, "
                         f"crypto mode {negotiated})")
        elif frame_id == FRAME_ID_CONNECT_SERVER:
            self.send_ctrl(FRAME_ID_CONNECT_REPLY, bytes([1]))
            log("rpc->", "connect_reply (connected)")

    def server_handle_frames(self, on_frame) -> None:
        """Mock-gate main loop: decrypt frames, dispatch, reply encrypted."""
        while self._alive:
            try:
                frame = self.frames_in.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                decoded = decode_inner_frame(frame)
            except ValueError:
                log("rpc<-", f"bad frame {hexdump(frame)}")
                continue
            name = self.biz.index_to_name.get(decoded["method_index"], "unknown")
            log("rpc<-", f"{name} args={decoded['args']}")
            logged_in = self.server_state.get("logged_in", False)
            if name == "loginWithAuthJson":
                try:
                    auth = json.loads(decoded["args"][0])
                except (ValueError, IndexError):
                    auth = {}
                logged_in = bool(auth.get("accesstoken"))
                self.server_state["logged_in"] = logged_in
                self.server_state["sdkuid"] = auth.get("sdkuid", "")
                reply_name, reply_args = "on_become_player", [logged_in, "login ok" if logged_in else "bad token"]
            elif name == "set_nickname":
                if logged_in:
                    self.server_state["nickname"] = decoded["args"][0]
                    reply_name, reply_args = "on_set_nickname", [True, "OK"]
                else:
                    reply_name, reply_args = "on_set_nickname", [False, "not logged in"]
            else:
                reply_name, reply_args = "on_set_nickname", [False, f"unknown rpc {name}"]
            reply = inner_frame(callback_payload(reply_name, reply_args))
            assert self.biz.send_stream is not None
            self.send_ctrl(FRAME_ID_ENTITY_METHOD, self.biz.send_stream.update(reply))
            log("rpc->", f"{reply_name} {reply_args}")


# ---------------------------------------------------------------------------
# Client pipeline: real UDP -> handshake -> KCP -> seed/session -> login -> rename
# ---------------------------------------------------------------------------
def run_client(host: str, port: int, nickname: str, token: str, sdkuid: str,
               crypto_mode: int, verbose: bool,
               public_key_pem: Optional[bytes] = None) -> Dict[str, Any]:
    if public_key_pem is None:
        # default: the mock gate writes its public key next to this script
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_gate_public.pem")
        if not os.path.exists(path):
            raise SystemExit("error: --public-key-pem missing (or run the mock gate first "
                             "so mock_gate_public.pem exists)")
        public_key_pem = open(path, "rb").read()
    private_key_pem = b""  # client side never needs a private key
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    peer = (host, port)

    def send_fn(data: bytes) -> None:
        sock.sendto(data, peer)

    inbound: "queue.Queue[bytes]" = queue.Queue()

    def recv_block() -> Optional[bytes]:
        try:
            return inbound.get(timeout=0.5)
        except queue.Empty:
            return None

    def socket_reader():
        while True:
            try:
                pkt, _ = sock.recvfrom(4096)
            except (OSError, socket.timeout):
                return
            inbound.put(pkt)

    reader_thread = threading.Thread(target=socket_reader, daemon=True)
    reader_thread.start()

    tp = UdpTransport(send_fn, WireConfig(), is_server=False,
                      public_key_pem=public_key_pem, private_key_pem=private_key_pem,
                      crypto_mode=crypto_mode, verbose=verbose)

    result: Dict[str, Any] = {"steps": []}
    try:
        hs = tp.client_handshake(recv_block)
        result["steps"].append({"step": "udp_handshake", **{k: hs[k] for k in ("token", "val")}})

        tp.start_io(recv_block)

        # business handshake: seed -> session key -> connect_server
        tp.send_ctrl(FRAME_ID_SEED_REQUEST)
        frame_id, payload = ctrl_reply(tp, "seed_reply")
        assert frame_id == FRAME_ID_SEED_REPLY, f"expected seed_reply id, got 0x{frame_id:04x}"
        seed = int.from_bytes(payload, "little")
        frame, session_key = tp.biz.build_session_key(seed)
        tp.send_frame(frame)
        frame_id, payload = ctrl_reply(tp, "session_key_ok")
        assert frame_id == FRAME_ID_SESSION_KEY_OK, f"expected session_key_ok id, got 0x{frame_id:04x}"
        tp.biz.enable_crypto(session_key)
        result["steps"].append({"step": "session_key", "seed": seed, "status": "ok"})

        clientid = secrets.token_hex(8)
        tp.send_frame(tp.biz.build_connect_server(clientid))
        frame_id, payload = ctrl_reply(tp, "connect_reply")
        assert frame_id == FRAME_ID_CONNECT_REPLY, f"expected connect_reply id, got 0x{frame_id:04x}"
        result["steps"].append({"step": "connect_server", "ret_type": payload[0], "clientid": clientid})

        # login with token, then rename, both as encrypted 0x8000 entity frames
        sauth = sauth_json_string(token, sdkuid)
        login_frame = rpc_inner_frame("loginWithAuthJson", [sauth])
        tp.send_frame(tp.biz.build_encrypted_rpc(login_frame))
        reply = decode_inner_frame(wait_frame(tp))
        result["steps"].append({"step": "loginWithAuthJson", "reply": reply})

        rename_frame = rename_inner_frame(nickname)
        tp.send_frame(tp.biz.build_encrypted_rpc(rename_frame))
        reply2 = decode_inner_frame(wait_frame(tp))
        result["steps"].append({"step": "set_nickname", "reply": reply2})

        result["login_ok"] = reply["args"][0] is True
        result["rename_ok"] = reply2["args"][0] is True
        result["nickname"] = nickname
    finally:
        tp.stop()
        sock.close()
    return result


def ctrl_reply(tp: "UdpTransport", expect: str, timeout: float = 6.0) -> Tuple[int, bytes]:
    try:
        tag, payload = tp.biz.reply_queue.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError(f"gate did not answer with {expect}") from None
    return tag, payload


def wait_frame(tp: UdpTransport, timeout: float = 6.0) -> bytes:
    return tp.frames_in.get(timeout=timeout)


# ---------------------------------------------------------------------------
# Mock gate over real UDP + KCP (single socket, sessions keyed by peer addr)
# ---------------------------------------------------------------------------
def run_server(bind: str, port: int, crypto_mode: int, verbose: bool) -> None:
    private_key_pem = generate_demo_private_key()
    public_key_pem = public_pem_from_private(private_key_pem)
    with open("mock_gate_private.pem", "wb") as f:
        f.write(private_key_pem)
    with open("mock_gate_public.pem", "wb") as f:
        f.write(public_key_pem)
    log("gate", f"listening udp://{bind}:{port} (demo RSA key written to mock_gate_*.pem)")

    outer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    outer.bind((bind, port))

    sessions: Dict[Tuple[str, int], UdpTransport] = {}
    sessions_lock = threading.Lock()

    def make_session(addr: Tuple[str, int], first_pkt: bytes) -> UdpTransport:
        def send_fn(data: bytes) -> None:
            outer.sendto(data, addr)

        tp = UdpTransport(send_fn, WireConfig(), is_server=True,
                          public_key_pem=public_key_pem, private_key_pem=private_key_pem,
                          crypto_mode=crypto_mode, verbose=verbose)
        inbound: "queue.Queue[bytes]" = queue.Queue()
        tp.inbound = inbound  # type: ignore[attr-defined]

        def recv_block() -> Optional[bytes]:
            try:
                return inbound.get(timeout=0.5)
            except queue.Empty:
                return None

        def serve():
            try:
                tp.server_handshake(first_pkt, recv_block)
                tp.start_io(recv_block)
                tp.server_handle_frames(lambda frame: None)
            except Exception as exc:
                log("gate", f"session {addr} ended: {exc}")

        threading.Thread(target=serve, daemon=True).start()
        return tp

    codec = HandshakeCodec(WireConfig())
    while True:
        pkt, addr = outer.recvfrom(4096)
        with sessions_lock:
            tp = sessions.get(addr)
            if tp is None:
                info = codec.parse(pkt)
                if info and info["is_handshake"] and info["cmd"] == HS_CMD_SYNC1:
                    tp = make_session(addr, pkt)
                    sessions[addr] = tp
                else:
                    continue
        tp.inbound.put(pkt)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# probe: send recovered handshake bytes to a real gate and dump responses
# ---------------------------------------------------------------------------
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
        print(f"   decoded: {info}")
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
                print(f"   decoded: {hs.parse(pkt)}")
    except socket.timeout:
        print("<- timeout (no reply to sync-1)")
    sock.close()


# ---------------------------------------------------------------------------
def cmd_self_test() -> None:
    cfg = WireConfig()
    hs = HandshakeCodec(cfg)
    p1 = hs.build_sync1(0, rand=0)
    assert struct.unpack("<I", p1[:4])[0] == G1_DEFAULT, hex(struct.unpack('<I', p1[:4])[0])
    assert p1[5] == HS_CMD_SYNC1 and len(p1) == SYNC1_SIZE
    p2 = hs.build_sync2(0, 0x1122334455667788, 0x1234)
    assert len(p2) == SYNC2_SIZE and p2[5] == HS_CMD_SYNC2
    tok = struct.unpack("<Q", p2[6:14])[0]
    assert (tok & 0xFFFFFFFF) == (0x55667788 + G1_DEFAULT) & 0xFFFFFFFF
    assert (tok >> 32) == 0x11223344
    hb = hs.build_heartbeat(0)
    assert hb[5] == 0 and hb[6] == 0xFF and struct.unpack("<I", hb[7:11])[0] == HEARTBEAT_MARKER

    # native business frame layout (0x1ff39d8): [u32 len][u16 id][body],
    # u32 counts every byte after itself
    f = native_frame(0x8000, b"\x01\x02\x03")
    assert f == bytes.fromhex("050000000080010203"), f.hex()
    fid, body = parse_native_frame(f)
    assert fid == 0x8000 and body == b"\x01\x02\x03"
    empty = native_frame(1)
    assert struct.unpack("<I", empty[:4])[0] == 2 and empty[4:6] == b"\x01\x00"

    # KCP segment round trip
    box: List[bytes] = []
    a = MiniKCP(KCP_CONV, box.append)
    b = MiniKCP(KCP_CONV, box.append)
    msg = b"x" * 2500
    a.send(msg)
    a.flush()
    for seg in box:
        b.input(seg)
    b.ack_pending()
    got = b.recv()
    assert got == msg
    print("self-test: OK")


def main() -> int:
    ap = argparse.ArgumentParser(description="NeoX real UDP/KCP transport research tool")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("self-test").set_defaults(func=lambda a: cmd_self_test())

    p = sub.add_parser("server")
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--port", type=int, default=30001)
    p.add_argument("--crypto-mode", type=int, default=DEFAULT_CRYPTO_MODE)
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=lambda a: run_server(a.bind, a.port, a.crypto_mode, a.verbose))

    p = sub.add_parser("client")
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--nickname", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--sdkuid", default="")
    p.add_argument("--crypto-mode", type=int, default=DEFAULT_CRYPTO_MODE)
    p.add_argument("--public-key-pem", default="")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=lambda a: print(json.dumps(
        run_client(a.host, a.port, a.nickname, a.token, a.sdkuid, a.crypto_mode, a.verbose,
                   open(a.public_key_pem, "rb").read() if a.public_key_pem else None),
        ensure_ascii=False, indent=2)))

    p = sub.add_parser("probe")
    p.add_argument("host")
    p.add_argument("port", type=int)
    p.set_defaults(func=lambda a: run_probe(a.host, a.port))

    args = ap.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
