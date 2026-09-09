#!/usr/bin/env python3
"""
NeoX old-game RPC demo for your own mock server.

This is not a real NetEase gateway client. It deliberately does not implement
login, session-key handshake, compression, encryption, or TCP/KCP transport.
It builds the recovered inner AreaMessage-style frame, then sends it as JSON to
an HTTP mock endpoint you control.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Sequence, Tuple
from urllib import request


FRAME_ID_ENTITY_METHOD = 0x8000
DEFAULT_SALT = "0"

RPC_ACTIONS = {
    "rename": ("set_nickname", "name"),
    "search-nid": ("find_player_by_nid", "nid"),
    "search-name": ("find_player_by_name", "name"),
}

MOCK_PLAYERS = {
    10086: {
        "id": "avatar_900001",
        "eid": "avatar_900001",
        "nid": 10086,
        "nickname": "开服老玩家",
        "default_name": "",
        "avatar_img_id": 101,
        "avatar_img_url": "",
        "avatar_frame_id": 1,
        "nickname_frame_id": 0,
        "pvp_status": 0,
        "logout_time": 0,
        "login_time": 0,
        "hall_space_id": "",
        "gender": 0,
        "is_info_pub": True,
        "qualify_level": 0,
        "can_add": True,
        "can_chat": True,
        "is_online": True,
    },
    123456: {
        "id": "avatar_123456",
        "eid": "avatar_123456",
        "nid": 123456,
        "nickname": "淋雨大佬",
        "default_name": "",
        "avatar_img_id": 520,
        "avatar_img_url": "",
        "avatar_frame_id": 6,
        "nickname_frame_id": 0,
        "pvp_status": 0,
        "logout_time": 0,
        "login_time": 0,
        "hall_space_id": "",
        "gender": 0,
        "is_info_pub": True,
        "qualify_level": 0,
        "can_add": True,
        "can_chat": True,
        "is_online": False,
    },
}


def rpc_index(name: str, salt: str = DEFAULT_SALT) -> int:
    digest = hashlib.md5((name + salt).encode("utf-8")).digest()
    return (
        ((digest[-4] & 0x7F) << 24)
        | (digest[-3] << 16)
        | (digest[-2] << 8)
        | digest[-1]
    )


def read_varint(data: bytes, pos: int) -> Tuple[int, int]:
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


def varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


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


def prop_value(value: Any) -> bytes:
    if isinstance(value, int):
        return uvar_field(1, value)
    if isinstance(value, str):
        return bytes_field(4, value.encode("utf-8"))
    raise TypeError(f"unsupported argument type: {type(value).__name__}")


def tuple_param(values: Sequence[Any]) -> bytes:
    items = b"".join(message_field(2, message_field(3, prop_value(v))) for v in values)
    return uvar_field(1, 44) + message_field(4, items)


def build_area_message(rpc_name: str, values: Sequence[Any], salt: str) -> bytes:
    method = sint32_field(2, rpc_index(rpc_name, salt))
    return message_field(3, method) + message_field(4, tuple_param(values))


def build_inner_frame(rpc_name: str, values: Sequence[Any], salt: str = DEFAULT_SALT) -> bytes:
    area = build_area_message(rpc_name, values, salt)
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


def decode_area_message(area: bytes) -> Dict[str, Any]:
    method_index = None
    args = []
    for field_no, wire_type, value in parse_fields(area):
        if field_no == 3 and wire_type == 2:
            for m_no, m_wire, m_value in parse_fields(value):
                if m_no == 2 and m_wire == 0:
                    method_index = unzigzag32(m_value)
        if field_no == 4 and wire_type == 2:
            args = decode_tuple_param(value)
    return {"method_index": method_index, "args": args}


def decode_tuple_param(param: bytes) -> List[Any]:
    args = []
    for field_no, wire_type, value in parse_fields(param):
        if field_no != 4 or wire_type != 2:
            continue
        for d_no, d_wire, d_value in parse_fields(value):
            if d_no != 2 or d_wire != 2:
                continue
            args.append(decode_prop_item(d_value))
    return args


def decode_prop_item(item: bytes) -> Any:
    for field_no, wire_type, value in parse_fields(item):
        if field_no == 3 and wire_type == 2:
            return decode_prop_value(value)
    return None


def decode_prop_value(value: bytes) -> Any:
    for field_no, wire_type, raw in parse_fields(value):
        if field_no == 1 and wire_type == 0:
            return raw
        if field_no == 4 and wire_type == 2:
            return raw.decode("utf-8", errors="replace")
    return None


def decode_inner_frame(frame: bytes) -> Dict[str, Any]:
    if len(frame) < 6:
        raise ValueError("frame too short")
    length = struct.unpack("<I", frame[:4])[0]
    frame_id = struct.unpack("<H", frame[4:6])[0]
    if length != len(frame) - 4:
        raise ValueError(f"bad length: header={length}, actual={len(frame) - 4}")
    if frame_id != FRAME_ID_ENTITY_METHOD:
        raise ValueError(f"bad frame id: 0x{frame_id:04x}")
    decoded = decode_area_message(frame[6:])
    decoded["frame_id"] = frame_id
    return decoded


def action_values(action: str, raw_value: str) -> Tuple[str, List[Any]]:
    rpc_name, arg_name = RPC_ACTIONS[action]
    if arg_name == "nid":
        if not raw_value.isdigit():
            raise SystemExit("search-nid needs a numeric nid")
        return rpc_name, [int(raw_value)]
    return rpc_name, [raw_value]


def mock_response(decoded: Dict[str, Any], salt: str) -> Dict[str, Any]:
    index_to_rpc = {rpc_index(name, salt): name for name, _ in RPC_ACTIONS.values()}
    rpc_name = index_to_rpc.get(decoded["method_index"], "unknown")
    args = decoded["args"]
    if rpc_name == "set_nickname":
        return {"callback": "on_set_nickname", "result": True, "msg": "", "new_name": args[0]}
    if rpc_name == "find_player_by_nid":
        player = MOCK_PLAYERS.get(int(args[0]))
        return {
            "callback": "on_query_player_profile",
            "info": profile_info(player),
        }
    if rpc_name == "find_player_by_name":
        word = str(args[0])
        player = next((p for p in MOCK_PLAYERS.values() if p["nickname"] == word), None)
        return {
            "callback": "on_query_player_profile",
            "info": profile_info(player),
        }
    return {"result": False, "errcode": 400, "msg": "unknown rpc index"}


def profile_info(player: Dict[str, Any] | None) -> Dict[str, Any]:
    if not player:
        return {"result": False, "errcode": 404, "data": {"avatar_info": {}}}
    player_id = str(player.get("id") or player.get("eid") or player.get("nid"))
    return {
        "result": True,
        "errcode": 0,
        "data": {
            "avatar_info": {
                player_id: player,
            },
        },
    }


class MockHandler(BaseHTTPRequestHandler):
    server_version = "NeoXMock/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[mock] " + fmt % args + "\n")

    def do_POST(self) -> None:
        if self.path != "/rpc":
            self.send_error(404, "use /rpc")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(size)
            payload = json.loads(body.decode("utf-8"))
            if "inner_frame_hex" in payload:
                frame = bytes.fromhex(payload["inner_frame_hex"])
            else:
                frame = base64.b64decode(payload["inner_frame_base64"])
            decoded = decode_inner_frame(frame)
            response = {
                "ok": True,
                "decoded": decoded,
                "mock_result": mock_response(decoded, payload.get("salt", DEFAULT_SALT)),
            }
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        data = json.dumps(response, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_server(host: str, port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), MockHandler)
    print(f"mock server: http://{host}:{port}/rpc")
    print("press Ctrl+C to stop")
    httpd.serve_forever()


def post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise SystemExit(f"request failed: {exc}") from exc


def make_request_payload(action: str, value: str, salt: str) -> Dict[str, Any]:
    rpc_name, values = action_values(action, value)
    frame = build_inner_frame(rpc_name, values, salt)
    return {
        "research_only": True,
        "salt": salt,
        "action": action,
        "rpc_name": rpc_name,
        "rpc_index": rpc_index(rpc_name, salt),
        "inner_frame_hex": frame.hex(),
    }


def run_client(url: str, action: str, value: str, salt: str) -> None:
    payload = make_request_payload(action, value, salt)
    print("request:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\nresponse:")
    print(json.dumps(post_json(url, payload), ensure_ascii=False, indent=2))


def run_build(action: str, value: str, salt: str) -> None:
    payload = make_request_payload(action, value, salt)
    print(json.dumps({
        "action": action,
        "rpc_name": payload["rpc_name"],
        "rpc_index": payload["rpc_index"],
        "frame_id_hex": f"0x{FRAME_ID_ENTITY_METHOD:04x}",
        "inner_frame_hex": payload["inner_frame_hex"],
        "inner_frame_base64": base64.b64encode(bytes.fromhex(payload["inner_frame_hex"])).decode("ascii"),
    }, ensure_ascii=False, indent=2))


def run_demo(action: str, value: str, salt: str) -> None:
    payload = make_request_payload(action, value, salt)
    decoded = decode_inner_frame(bytes.fromhex(payload["inner_frame_hex"]))
    response = {
        "ok": True,
        "decoded": decoded,
        "mock_result": mock_response(decoded, salt),
    }
    print("request:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\nresponse:")
    print(json.dumps(response, ensure_ascii=False, indent=2))


def self_test() -> None:
    assert rpc_index("set_nickname") == 1648625260
    assert rpc_index("find_player_by_nid") == 1288662083
    assert rpc_index("find_player_by_name") == 1815379889
    frame = build_inner_frame("find_player_by_nid", [123456])
    decoded = decode_inner_frame(frame)
    assert decoded["method_index"] == 1288662083
    assert decoded["args"] == [123456]
    print("self-test: OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="NeoX old-game API mock demo")
    sub = parser.add_subparsers(dest="cmd", required=True)

    server = sub.add_parser("server", help="start your own mock HTTP server")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8787)

    client = sub.add_parser("client", help="send a recovered inner frame to your own server")
    client.add_argument("action", choices=sorted(RPC_ACTIONS))
    client.add_argument("value")
    client.add_argument("--url", default="http://127.0.0.1:8787/rpc")
    client.add_argument("--salt", default=DEFAULT_SALT)

    build = sub.add_parser("build", help="only print the inner frame, do not send")
    build.add_argument("action", choices=sorted(RPC_ACTIONS))
    build.add_argument("value")
    build.add_argument("--salt", default=DEFAULT_SALT)

    demo = sub.add_parser("demo", help="offline request/response demo without network")
    demo.add_argument("action", choices=sorted(RPC_ACTIONS))
    demo.add_argument("value")
    demo.add_argument("--salt", default=DEFAULT_SALT)

    sub.add_parser("self-test", help="run offline checks")
    args = parser.parse_args()

    if args.cmd == "server":
        run_server(args.host, args.port)
    elif args.cmd == "client":
        run_client(args.url, args.action, args.value, args.salt)
    elif args.cmd == "build":
        run_build(args.action, args.value, args.salt)
    elif args.cmd == "demo":
        run_demo(args.action, args.value, args.salt)
    elif args.cmd == "self-test":
        self_test()


if __name__ == "__main__":
    main()
