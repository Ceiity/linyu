#!/usr/bin/env python3
"""
NeoX rename "protocol machine" research skeleton.

This file is intentionally offline/private-server oriented. It shows what a
minimal old-game rename protocol client would probably look like after the
client-side pieces recovered so far:

  1. validate or accept a nickname
  2. calculate RpcIndex("set_nickname" + salt)
  3. build AreaMessage(method=index, args=(nickname,))
  4. wrap it as uint32_le(length) + uint16_le(0x8000) + AreaMessage
  5. optionally zlib-compress
  6. encrypt with the selected stream mode
  7. expect an on_set_nickname(result, msg) callback

It does not implement old official server auth, production KCP/TCP, or any
unauthorized live-service access.
"""

from __future__ import annotations

import argparse
import base64
import json
from dataclasses import dataclass
from typing import Any, Dict

from neox_rename_protocol_replay import (
    CRYPTO_MODES,
    DEFAULT_CRYPTO_MODE,
    DEFAULT_SALT,
    FRAME_ID_ENTITY_METHOD,
    callback_payload,
    decode_area_message,
    decode_inner_frame,
    inner_frame,
    open_payload,
    rename_inner_frame,
    rpc_index,
    rpc_md5,
    seal_payload,
)


@dataclass
class RenameProtocolMachine:
    salt: str = DEFAULT_SALT
    recv_salt: str = DEFAULT_SALT
    crypto_mode: int = DEFAULT_CRYPTO_MODE
    session_key: bytes = b"A" * 32
    compress: bool = False

    def build_rename(self, nickname: str, *, include_md5: bool = False) -> Dict[str, Any]:
        frame = rename_inner_frame(nickname, salt=self.salt, include_md5=include_md5)
        return {
            "stage": "client_build_inner_rename_frame",
            "network_ready": False,
            "rpc_name": "set_nickname",
            "rpc_index": rpc_index("set_nickname", self.salt),
            "rpc_index_hex": f"0x{rpc_index('set_nickname', self.salt):08x}",
            "rpc_md5_hex": rpc_md5("set_nickname").hex(),
            "frame_id_hex": f"0x{FRAME_ID_ENTITY_METHOD:04x}",
            "nickname": nickname,
            "inner_frame_hex": frame.hex(),
            "inner_frame_base64": base64.b64encode(frame).decode("ascii"),
            "decoded_check": decode_inner_frame(frame),
        }

    def encrypt_rename(self, nickname: str) -> Dict[str, Any]:
        plain = rename_inner_frame(nickname, salt=self.salt)
        sealed = seal_payload(
            plain,
            self.session_key,
            self.crypto_mode,
            compress=self.compress,
        )
        opened = open_payload(
            sealed,
            self.session_key,
            self.crypto_mode,
            compressed=self.compress,
        )
        return {
            "stage": "client_encrypt_payload",
            "crypto_mode": self.crypto_mode,
            "crypto_name": CRYPTO_MODES[self.crypto_mode].name,
            "compressed_before_encrypt": self.compress,
            "session_key_hex": self.session_key.hex(),
            "plain_inner_frame_hex": plain.hex(),
            "encrypted_payload_hex": sealed.hex(),
            "encrypted_payload_base64": base64.b64encode(sealed).decode("ascii"),
            "roundtrip_ok": opened == plain,
            "decoded_after_decrypt": decode_inner_frame(opened),
            "not_wire_ready": [
                "missing login/auth token",
                "missing seed/session-key exchange with the real peer",
                "missing KCP/TCP outer packet header",
                "missing runtime avatar area id/guid if required by server",
            ],
        }

    def mock_server_decode(self, encrypted_payload_hex: str) -> Dict[str, Any]:
        sealed = bytes.fromhex(encrypted_payload_hex)
        plain = open_payload(
            sealed,
            self.session_key,
            self.crypto_mode,
            compressed=self.compress,
        )
        decoded = decode_inner_frame(plain)
        return {
            "stage": "mock_server_decode",
            "decoded": decoded,
            "rpc_name_guess": (
                "set_nickname"
                if decoded.get("method_index") == rpc_index("set_nickname", self.salt)
                else "unknown"
            ),
        }

    def build_callback(self, result: bool = True, msg: str = "") -> Dict[str, Any]:
        payload = callback_payload(
            "on_set_nickname",
            [result, msg],
            salt=self.recv_salt,
        )
        candidate = inner_frame(payload)
        return {
            "stage": "server_business_callback_template",
            "wire_packet": False,
            "callback": "on_set_nickname(result, msg)",
            "callback_index": rpc_index("on_set_nickname", self.recv_salt),
            "callback_index_hex": f"0x{rpc_index('on_set_nickname', self.recv_salt):08x}",
            "callback_md5_hex": rpc_md5("on_set_nickname").hex(),
            "args": [result, msg],
            "payload_hex": payload.hex(),
            "payload_base64": base64.b64encode(payload).decode("ascii"),
            "decoded_as_area_like_payload": decode_area_message(payload),
            "candidate_0x8000_frame_hex": candidate.hex(),
            "candidate_warning": (
                "0x8000 is confirmed for client->server entity_method; "
                "server->client gate wrapper still needs deeper native trace."
            ),
        }

    def full_offline_demo(self, nickname: str) -> Dict[str, Any]:
        build = self.build_rename(nickname)
        enc = self.encrypt_rename(nickname)
        server = self.mock_server_decode(enc["encrypted_payload_hex"])
        callback = self.build_callback(True, "")
        return {
            "research_only": True,
            "what_this_resembles": "a minimal historical rename protocol-machine skeleton",
            "client_build": build,
            "client_encrypt": enc,
            "server_decode": server,
            "server_callback_template": callback,
            "confirmed": [
                "set_nickname(name) RPC name",
                "RpcIndex salt=0 value 1648625260 / 0x6244066c",
                "client->server inner frame id 0x8000",
                "AreaMessage simple string argument encoding",
                "on_set_nickname(result,msg) callback name and simple args",
            ],
            "not_confirmed": [
                "live official server address",
                "unauthenticated rename possibility",
                "complete KCP/TCP raw outer packet",
                "server->client gate wrapper frame id",
                "runtime salt different from '0'",
                "production AES IV initial bytes",
            ],
        }


def machine_from_args(args: argparse.Namespace) -> RenameProtocolMachine:
    session_key = bytes.fromhex(args.session_key_hex) if args.session_key_hex else b"A" * 32
    if args.crypto_mode not in CRYPTO_MODES:
        raise SystemExit(f"unsupported crypto mode: {args.crypto_mode}")
    return RenameProtocolMachine(
        salt=args.salt,
        recv_salt=args.recv_salt,
        crypto_mode=args.crypto_mode,
        session_key=session_key,
        compress=args.compress,
    )


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline NeoX rename protocol-machine research skeleton")
    parser.add_argument("nickname", nargs="?", default="淋雨")
    parser.add_argument("--salt", default=DEFAULT_SALT)
    parser.add_argument("--recv-salt", default=DEFAULT_SALT)
    parser.add_argument("--crypto-mode", type=int, default=DEFAULT_CRYPTO_MODE, choices=sorted(CRYPTO_MODES))
    parser.add_argument("--session-key-hex", default="")
    parser.add_argument("--compress", action="store_true")
    parser.add_argument("--include-md5", action="store_true")
    parser.add_argument("--only", choices=("build", "encrypt", "callback", "demo"), default="demo")
    args = parser.parse_args()

    machine = machine_from_args(args)
    if args.only == "build":
        print_json(machine.build_rename(args.nickname, include_md5=args.include_md5))
    elif args.only == "encrypt":
        print_json(machine.encrypt_rename(args.nickname))
    elif args.only == "callback":
        print_json(machine.build_callback(True, ""))
    else:
        print_json(machine.full_offline_demo(args.nickname))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
