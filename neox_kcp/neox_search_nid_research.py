#!/usr/bin/env python3
"""
NeoX find_player_by_nid research helper.

This script is for offline/private-server research. It builds the recovered
inner RPC frame for find_player_by_nid(nid), decodes it back for verification,
and can optionally POST the frame to an HTTP endpoint you own.

It does not implement login, KCP/TCP, encryption, compression, or old official
server access.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
from typing import Any, Dict, List, Sequence, Tuple
from urllib import request


FRAME_ID_ENTITY_METHOD = 0x8000
DEFAULT_SALT = "0"


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
    value = 0
    shift = 0
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


def zigzag32(value: int) -> int:
    return (value << 1) ^ (value >> 31)


def unzigzag32(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def key(field_no: int, wire_type: int) -> bytes:
    return varint((field_no << 3) | wire_type)


def uvar_field(field_no: int, value: int) -> bytes:
    return key(field_no, 0) + varint(value)


def sint32_field(field_no: int, value: int) -> bytes:
    return key(field_no, 0) + varint(zigzag32(value))


def bytes_field(field_no: int, value: bytes) -> bytes:
    return key(field_no, 2) + varint(len(value)) + value


def message_field(field_no: int, value: bytes) -> bytes:
    return bytes_field(field_no, value)


def rpc_index(name: str, salt: str = DEFAULT_SALT) -> int:
    digest = hashlib.md5((name + salt).encode("utf-8")).digest()
    return (
        ((digest[-4] & 0x7F) << 24)
        | (digest[-3] << 16)
        | (digest[-2] << 8)
        | digest[-1]
    )


def rpc_md5(name: str) -> str:
    return hashlib.md5(name.encode("utf-8")).hexdigest()


def prop_int(value: int) -> bytes:
    # PropValue.ivalue = field 1.
    return uvar_field(1, value)


def prop_item(value: int) -> bytes:
    # PropItem.value = field 3.
    return message_field(3, prop_int(value))


def tuple_param(values: Sequence[int]) -> bytes:
    # oper=44 identifies the tuple/list-style argument container observed in
    # the recovered AreaMessage tests.
    prop_dict = b"".join(message_field(2, prop_item(value)) for value in values)
    return uvar_field(1, 44) + message_field(4, prop_dict)


def area_message_find_player_by_nid(nid: int, salt: str = DEFAULT_SALT) -> bytes:
    method = sint32_field(2, rpc_index("find_player_by_nid", salt))
    return message_field(3, method) + message_field(4, tuple_param([nid]))


def inner_frame_find_player_by_nid(nid: int, salt: str = DEFAULT_SALT) -> bytes:
    area = area_message_find_player_by_nid(nid, salt)
    body = struct.pack("<H", FRAME_ID_ENTITY_METHOD) + area
    return struct.pack("<I", len(body)) + body


def parse_fields(data: bytes) -> List[Tuple[int, int, Any]]:
    fields = []
    pos = 0
    while pos < len(data):
        raw_key, pos = read_varint(data, pos)
        field_no = raw_key >> 3
        wire_type = raw_key & 7
        if wire_type == 0:
            value, pos = read_varint(data, pos)
        elif wire_type == 2:
            size, pos = read_varint(data, pos)
            value = data[pos : pos + size]
            if len(value) != size:
                raise ValueError("truncated bytes field")
            pos += size
        else:
            raise ValueError(f"unsupported wire type: {wire_type}")
        fields.append((field_no, wire_type, value))
    return fields


def decode_inner_frame(frame: bytes) -> Dict[str, Any]:
    size = struct.unpack("<I", frame[:4])[0]
    frame_id = struct.unpack("<H", frame[4:6])[0]
    if size != len(frame) - 4:
        raise ValueError(f"bad frame length: header={size}, actual={len(frame) - 4}")
    if frame_id != FRAME_ID_ENTITY_METHOD:
        raise ValueError(f"bad frame id: 0x{frame_id:04x}")
    area = frame[6:]
    decoded: Dict[str, Any] = {"frame_id_hex": f"0x{frame_id:04x}", "args": []}
    for field_no, wire_type, value in parse_fields(area):
        if field_no == 3 and wire_type == 2:
            for method_no, method_wire, method_value in parse_fields(value):
                if method_no == 2 and method_wire == 0:
                    decoded["method_index"] = unzigzag32(method_value)
        elif field_no == 4 and wire_type == 2:
            decoded["args"] = decode_tuple_param(value)
    return decoded


def decode_tuple_param(param: bytes) -> List[int]:
    args = []
    for field_no, wire_type, value in parse_fields(param):
        if field_no != 4 or wire_type != 2:
            continue
        for child_no, child_wire, child_value in parse_fields(value):
            if child_no != 2 or child_wire != 2:
                continue
            for item_no, item_wire, item_value in parse_fields(child_value):
                if item_no != 3 or item_wire != 2:
                    continue
                for val_no, val_wire, val_value in parse_fields(item_value):
                    if val_no == 1 and val_wire == 0:
                        args.append(val_value)
    return args


def mock_profile(nid: int, nickname: str) -> Dict[str, Any]:
    avatar_id = f"avatar_{nid}"
    return {
        "callback": "on_query_player_profile",
        "info": {
            "result": True,
            "errcode": 0,
            "data": {
                "avatar_info": {
                    avatar_id: {
                        "id": avatar_id,
                        "eid": avatar_id,
                        "nid": nid,
                        "nickname": nickname,
                        "default_name": "",
                        "avatar_img_id": 0,
                        "avatar_img_url": "",
                        "avatar_frame_id": 0,
                        "nickname_frame_id": 0,
                        "pvp_status": 0,
                        "logout_time": 0,
                        "can_add": True,
                        "can_chat": True,
                    }
                }
            },
        },
    }


def post_to_owned_endpoint(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_payload(nid: int, salt: str) -> Dict[str, Any]:
    frame = inner_frame_find_player_by_nid(nid, salt)
    return {
        "research_only": True,
        "network_ready": False,
        "rpc_name": "find_player_by_nid",
        "salt": salt,
        "nid": nid,
        "rpc_index": rpc_index("find_player_by_nid", salt),
        "rpc_index_hex": f"0x{rpc_index('find_player_by_nid', salt):08x}",
        "rpc_md5_hex": rpc_md5("find_player_by_nid"),
        "inner_frame_hex": frame.hex(),
        "inner_frame_base64": base64.b64encode(frame).decode("ascii"),
        "decoded_check": decode_inner_frame(frame),
        "missing_for_real_game_wire": [
            "login/auth token",
            "seed/session key handshake",
            "stream encryption/compression",
            "TCP/KCP transport header",
            "runtime avatar area id/guid",
            "server-to-client outer callback wrapper",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="NeoX find_player_by_nid offline research helper")
    parser.add_argument("nid", nargs="?", type=int, default=3886699)
    parser.add_argument("--salt", default=DEFAULT_SALT)
    parser.add_argument("--mock-name", default="淋雨")
    parser.add_argument("--post-owned-url", default="", help="optional HTTP endpoint you own, e.g. http://127.0.0.1:8787/rpc")
    args = parser.parse_args()

    payload = build_payload(args.nid, args.salt)
    output: Dict[str, Any] = {
        "request": payload,
        "mock_callback_shape": mock_profile(args.nid, args.mock_name),
        "important_note": "This is an inner-frame/offline research script, not an unauthenticated old-server client.",
    }
    if args.post_owned_url:
        output["owned_endpoint_response"] = post_to_owned_endpoint(args.post_owned_url, payload)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
