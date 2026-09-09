#!/usr/bin/env python3
"""
NeoX 游戏 RPC 离线研究工具。

依据旧客户端 script.npk 中恢复出的业务方法名，展示：
  1. 改名、搜索玩家、好友申请的调用参数；
  2. NeoX RpcIndex 中使用的 MD5 方法号算法；
  3. 模拟请求和响应字段的 JSON 结构；
  4. 构造未登录、未加密的 NeoX AreaMessage 内层研究帧。

重要：本程序不会联网。packet 子命令只复现已静态恢复出的 protobuf 内层
结构，不包含真实会话、压缩、加密、TCP/KCP 连接、seed/session key 握手、
Avatar area id/guid 上下文。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence


NEOX_ENTITY_METHOD_FRAME_ID = 0x8000


@dataclass(frozen=True)
class RpcSpec:
    name: str
    args: Sequence[str]
    purpose: str
    id_kind: Optional[str] = None


RPC_SPECS: Dict[str, RpcSpec] = {
    "rename": RpcSpec(
        "set_nickname", ("name",), "修改游戏角色昵称"
    ),
    "search-nid": RpcSpec(
        "find_player_by_nid", ("nid",), "按公开数字编号搜索玩家", "nid"
    ),
    "search-name": RpcSpec(
        "find_player_by_name", ("name",), "按昵称搜索玩家"
    ),
    "search-id": RpcSpec(
        "find_player_by_id", ("avatar_id",), "按内部角色 ID 查询玩家", "avatar_id/eid"
    ),
    "search-ids": RpcSpec(
        "find_player_by_ids", ("avatar_ids",), "批量查询内部角色 ID", "avatar_id/eid"
    ),
    "add-friend": RpcSpec(
        "friend_request", ("request_id",), "发送好友申请", "目标内部角色 ID"
    ),
    "agree-friend": RpcSpec(
        "agree_friend_request", ("avatar_id",), "同意好友申请", "申请者内部角色 ID"
    ),
    "reject-friend": RpcSpec(
        "reject_friend_request", ("applier_id",), "拒绝好友申请", "申请者内部角色 ID"
    ),
    "delete-friend": RpcSpec(
        "delete_friend", ("friend_id",), "删除好友", "好友内部角色 ID"
    ),
}


def rpc_index(name: str, salt: str) -> int:
    """复现 RpcIndex.calculate_rpc_index 的静态恢复结果。

    原逻辑对 name + salt 做 MD5，取摘要末 4 字节作为大端整数，并清掉
    最高符号位。实际会话可能下发不同的 SEND/RECV salt；默认值 ``0``
    只适合观察算法，不能据此认定正式会话的方法号。
    """

    digest = hashlib.md5((name + salt).encode("utf-8")).digest()
    return (
        ((digest[-4] & 0x7F) << 24)
        | (digest[-3] << 16)
        | (digest[-2] << 8)
        | digest[-1]
    )


def rpc_md5(name: str) -> bytes:
    """Md5OrIndexCodec 文档中的字符串 MD5，不带 RpcIndex salt。"""

    return hashlib.md5(name.encode("utf-8")).digest()


def _varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _sint32(value: int) -> bytes:
    return _varint((value << 1) ^ (value >> 31))


def _key(field_no: int, wire_type: int) -> bytes:
    return _varint((field_no << 3) | wire_type)


def _uvar_field(field_no: int, value: int) -> bytes:
    return _key(field_no, 0) + _varint(value)


def _sint32_field(field_no: int, value: int) -> bytes:
    return _key(field_no, 0) + _sint32(value)


def _bytes_field(field_no: int, value: bytes) -> bytes:
    return _key(field_no, 2) + _varint(len(value)) + value


def _message_field(field_no: int, value: bytes) -> bytes:
    return _bytes_field(field_no, value)


def _prop_value(value: Any) -> bytes:
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        # PropValue.ivalue = 1, int64
        return _uvar_field(1, value)
    if isinstance(value, str):
        # PropValue.svalue = 4, bytes
        return _bytes_field(4, value.encode("utf-8"))
    raise TypeError(f"暂不支持参数类型：{type(value).__name__}")


def _prop_item_value(value: Any) -> bytes:
    # PropItem.value = 3
    return _message_field(3, _prop_value(value))


def _tuple_param(values: Sequence[Any]) -> bytes:
    # Native tuple serializer sets PropItem.oper = 44 and stores each positional
    # argument as a repeated PropDict.item child PropItem.
    prop_dict = b"".join(_message_field(2, _prop_item_value(value)) for value in values)
    return _uvar_field(1, 44) + _message_field(4, prop_dict)


def _method_index_message(name: str, salt: str, include_md5: bool) -> bytes:
    payload = b""
    if include_md5:
        payload += _bytes_field(1, rpc_md5(name))
    payload += _sint32_field(2, rpc_index(name, salt))
    return payload


def make_area_message(
    rpc_name: str,
    values: Sequence[Any],
    salt: str = "0",
    area_id: bytes = b"",
    guid: Optional[int] = None,
    include_md5: bool = False,
) -> bytes:
    msg = b""
    if area_id:
        msg += _bytes_field(1, area_id)
    if guid is not None:
        msg += _uvar_field(2, guid)
    msg += _message_field(3, _method_index_message(rpc_name, salt, include_md5))
    msg += _message_field(4, _tuple_param(values))
    return msg


def make_inner_frame(area_message: bytes, frame_id: int = NEOX_ENTITY_METHOD_FRAME_ID) -> bytes:
    body = struct.pack("<H", frame_id) + area_message
    return struct.pack("<I", len(body)) + body


def make_call(action: str, values: Sequence[Any], salt: str) -> Dict[str, Any]:
    spec = RPC_SPECS[action]
    if len(values) != len(spec.args):
        raise ValueError(f"{action} 需要 {len(spec.args)} 个参数：{', '.join(spec.args)}")

    return {
        "research_only": True,
        "wire_packet": False,
        "direction": "client_to_avatar_server",
        "rpc_name": spec.name,
        "rpc_index_with_supplied_salt": rpc_index(spec.name, salt),
        "salt_used": salt,
        "arguments": dict(zip(spec.args, values)),
        "purpose": spec.purpose,
        "id_kind": spec.id_kind,
        "requirements_not_included": [
            "authenticated game session",
            "Avatar entity/mailbox",
            "runtime SEND/RECV salts",
            "connection seed/session-key handshake",
            "compression/encryption layer",
        ],
    }


def normalize_action_values(action: str, raw: Sequence[str]) -> List[Any]:
    if action == "search-nid":
        if len(raw) != 1 or not raw[0].isdigit():
            raise ValueError("search-nid 需要一个纯数字 nid")
        return [int(raw[0])]
    if action == "search-ids":
        if not raw:
            raise ValueError("search-ids 至少需要一个内部角色 ID")
        return [list(raw)]
    return list(raw)


def response_template(kind: str) -> Dict[str, Any]:
    templates: Dict[str, Dict[str, Any]] = {
        "rename": {
            "observed_callback": "on_set_nickname(result, msg)",
            "alternate_ui_callback_fields": ["result", "data"],
            "example": {"result": True, "msg": ""},
        },
        "player": {
            "observed_callback": "on_query_player_profile(info)",
            "top_level_fields": ["result", "errcode", "data"],
            "player_fields": [
                "id/eid", "nid", "nickname", "avatar_img_id",
                "avatar_img_url", "avatar_frame_id", "gender", "is_online",
                "login_time", "logout_time", "hall_space_id", "book_level",
                "qualify_level", "season_stats", "can_add", "can_chat",
            ],
        },
        "friend": {
            "observed_callback": "on_friend_request(result)",
            "top_level_fields": ["result", "data", "request_id", "apply_info"],
            "apply_info_fields": [
                "applier_id", "applier_nid", "applier_name", "applier_time",
                "avatar_img_id", "avatar_img_url",
            ],
        },
    }
    return templates[kind]


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def run_self_test() -> None:
    assert 0 <= rpc_index("set_nickname", "0") <= 0x7FFFFFFF
    assert rpc_index("set_nickname", "0") == rpc_index("set_nickname", "0")
    assert rpc_index("set_nickname", "0") != rpc_index("find_player_by_nid", "0")
    sample = make_call("search-nid", [123456], "0")
    assert sample["arguments"]["nid"] == 123456
    assert sample["wire_packet"] is False
    assert rpc_index("set_nickname", "0") == 1648625260
    assert rpc_index("find_player_by_nid", "0") == 1288662083
    assert rpc_index("find_player_by_name", "0") == 1815379889
    frame = make_inner_frame(make_area_message("find_player_by_nid", [123456], "0"))
    assert frame[:4] == struct.pack("<I", len(frame) - 4)
    assert frame[4:6] == struct.pack("<H", NEOX_ENTITY_METHOD_FRAME_ID)
    print("self-test: OK")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NeoX RPC 离线研究工具（不联网）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出恢复出的业务 RPC")

    index_parser = sub.add_parser("index", help="计算方法名在指定 salt 下的研究用 RPC index")
    index_parser.add_argument("rpc_name", help="例如 set_nickname")
    index_parser.add_argument("--salt", default="0", help="SEND/RECV salt，默认仅演示值 0")

    build_parser_ = sub.add_parser("build", help="生成离线模拟调用")
    build_parser_.add_argument("action", choices=sorted(RPC_SPECS))
    build_parser_.add_argument("values", nargs="*", help="动作参数")
    build_parser_.add_argument("--salt", default="0", help="研究用 salt")

    packet_parser = sub.add_parser("packet", help="生成未登录、未加密的 AreaMessage 内层研究帧")
    packet_parser.add_argument("action", choices=sorted(RPC_SPECS))
    packet_parser.add_argument("values", nargs="*", help="动作参数")
    packet_parser.add_argument("--salt", default="0", help="研究用 salt")
    packet_parser.add_argument("--area-id", default="", help="可选 AreaMessage.id，按 UTF-8 写入")
    packet_parser.add_argument("--area-id-hex", default="", help="可选 AreaMessage.id，十六进制优先")
    packet_parser.add_argument("--guid", type=int, default=None, help="可选 AreaMessage.guid")
    packet_parser.add_argument("--include-md5", action="store_true", help="同时写入 Md5OrIndex.md5")

    response_parser = sub.add_parser("response", help="查看已恢复的响应字段模板")
    response_parser.add_argument("kind", choices=("rename", "player", "friend"))

    sub.add_parser("self-test", help="运行本地自检")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "list":
            print_json({key: asdict(spec) for key, spec in RPC_SPECS.items()})
        elif args.command == "index":
            print_json({
                "rpc_name": args.rpc_name,
                "salt": args.salt,
                "rpc_index": rpc_index(args.rpc_name, args.salt),
                "warning": "该编号只有在 salt 与目标会话一致时才有意义",
            })
        elif args.command == "build":
            values = normalize_action_values(args.action, args.values)
            print_json(make_call(args.action, values, args.salt))
        elif args.command == "packet":
            values = normalize_action_values(args.action, args.values)
            spec = RPC_SPECS[args.action]
            area_id = bytes.fromhex(args.area_id_hex) if args.area_id_hex else args.area_id.encode("utf-8")
            area = make_area_message(
                spec.name,
                values,
                salt=args.salt,
                area_id=area_id,
                guid=args.guid,
                include_md5=args.include_md5,
            )
            frame = make_inner_frame(area)
            print_json({
                "research_only": True,
                "network_ready": False,
                "action": args.action,
                "rpc_name": spec.name,
                "rpc_index": rpc_index(spec.name, args.salt),
                "rpc_md5_hex": rpc_md5(spec.name).hex(),
                "frame_id_hex": f"0x{NEOX_ENTITY_METHOD_FRAME_ID:04x}",
                "frame_format": "uint32_le(length_after_prefix) + uint16_le(0x8000) + AreaMessage",
                "area_message_hex": area.hex(),
                "inner_frame_hex": frame.hex(),
                "inner_frame_base64": base64.b64encode(frame).decode("ascii"),
                "not_included": [
                    "login/auth token",
                    "seed/session key handshake",
                    "compression/encryption",
                    "TCP/KCP transport",
                    "live avatar area context unless --area-id/--guid are supplied",
                ],
            })
        elif args.command == "response":
            print_json(response_template(args.kind))
        elif args.command == "self-test":
            run_self_test()
        return 0
    except ValueError as exc:
        raise SystemExit(f"参数错误：{exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
