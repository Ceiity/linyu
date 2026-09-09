#!/usr/bin/env python3
"""
NeoX RpcDebug message research helper.

The old client contains a local WebSocket debug bridge under script/RpcDebug.
When enabled in-game by DebugHelper.start_rpc, it listens on port 8088 and
queues JSON messages that can call the current client's RPC proxy.

This helper is intentionally offline and private-server oriented. By default it
only prints the JSON messages and the evidence behind them. It does not connect
to old production services and does not implement login bypass.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from neox_rename_protocol_replay import DEFAULT_SALT, rpc_index


SERVER_METHOD = "0"
SOUL_METHOD = "1"
SERVICE_METHOD = "2"
ENTITY_MESSAGE = "3"
DEFAULT_PORT = 8088


RPCS: Dict[str, Dict[str, Any]] = {
    "rename": {
        "name": "set_nickname",
        "key": SERVER_METHOD,
        "arg_types": ["str"],
        "callback": "on_set_nickname",
        "status": "confirmed script-side RPC name; confirmed RpcDebug can call server proxy methods",
    },
    "search-nid": {
        "name": "find_player_by_nid",
        "key": SERVER_METHOD,
        "arg_types": ["int"],
        "callback": "on_query_player_profile",
        "status": "confirmed script-side RPC name; exact live server return unavailable",
    },
    "search-name": {
        "name": "find_player_by_name",
        "key": SERVER_METHOD,
        "arg_types": ["str"],
        "callback": "on_query_player_profile",
        "status": "confirmed script-side RPC name; exact live server return unavailable",
    },
    "friend-request": {
        "name": "friend_request",
        "key": SERVER_METHOD,
        "arg_types": ["str"],
        "callback": "on_friend_request",
        "status": "confirmed script-side RPC name; argument is internal avatar id, not public nid",
    },
}


def rpcdebug_send_message(rpc_name: str, args: List[Any], key: str = SERVER_METHOD, times: int = 1) -> Dict[str, Any]:
    # MyWebSocketServer.handleRPCMsg reads name/args/key/times and forwards the
    # same JSON string into RpcDebug's internal queue.
    return {
        "name": rpc_name,
        "args": args,
        "key": key,
        "times": times,
    }


def rpcdebug_intercept_message(names: List[str]) -> Dict[str, Any]:
    # HookManager.handlemessage dispatches type == "set_intercept" to
    # handleInterceptMsg, which reads intercept_msgs.
    return {
        "type": "set_intercept",
        "intercept_msgs": names,
    }


def capture_shape(rpc_name: str, args: List[Any], key: str = SERVER_METHOD, unit_id: str = "") -> Dict[str, Any]:
    # HookManager.MessageProxy.sent_message builds exactly these field names.
    return {
        "key": key,
        "name": rpc_name,
        "args": args,
        "unit_id": unit_id,
        "is_send": key in (SERVER_METHOD, SOUL_METHOD, SERVICE_METHOD),
        "is_recv": key in (ENTITY_MESSAGE,),
    }


def coerce_args(command: str, raw: str) -> List[Any]:
    if command == "search-nid":
        return [int(raw)]
    return [raw]


def build_output(command: str, value: str, salt: str, times: int) -> Dict[str, Any]:
    spec = RPCS[command]
    args = coerce_args(command, value)
    name = spec["name"]
    return {
        "research_only": True,
        "what_this_is": "JSON message shape for the old client's built-in local RpcDebug WebSocket bridge",
        "default_client_ws": f"ws://127.0.0.1:{DEFAULT_PORT}/",
        "command": command,
        "rpc_name": name,
        "rpc_index_salt": salt,
        "rpc_index": rpc_index(name, salt),
        "rpc_index_hex": f"0x{rpc_index(name, salt):08x}",
        "expected_callback": spec["callback"],
        "rpcdebug_send_json": rpcdebug_send_message(name, args, spec["key"], times),
        "rpcdebug_capture_json_shape": capture_shape(name, args, spec["key"]),
        "optional_intercept_json": rpcdebug_intercept_message([name, spec["callback"]]),
        "evidence": [
            "helper/DebugHelper.nxs: DebugHelper.start_rpc imports RpcDebug.MyWebSocketServer, starts it, default port 8088",
            "RpcDebug/MyWebSocketServer.nxs: handleMessage parses JSON and calls handleRPCMsg unless type == set_intercept",
            "RpcDebug/MyWebSocketServer.nxs: handleRPCMsg reads name,args,key,times and queue.put(json.dumps(message))",
            "RpcDebug/Hookers/HookManager.nxs: handleRPCMsg reads name,args,key,sleep and calls reSentRpc",
            "RpcDebug/Hookers/HookManager.nxs: reSentRpc calls hooker.send_rpc(methodname,args,key,unit_id)",
            "RpcDebug/Hookers/ClassHooker.nxs: send_rpc uses Keys.g_entity.server.__getattr__(methodname)(*args) for SERVER_METHOD",
            "RpcDebug/Hookers/ClassHooker.nxs: hook_send wraps AsioServerProxy.__getattr__ and captures outgoing RPCs",
            "RpcDebug/Keys.nxs: SERVER_METHOD=0, ENTITY_MESSAGE=3, proto='msgpack', MAX_COUNT_PER_TICK=10",
        ],
        "status": spec["status"],
        "important_limits": [
            "This requires the game client to run and DebugHelper.start_rpc to be reachable/enabled.",
            "This reuses the client's current login/session/entity context; it is not proof of unauthenticated rename.",
            "If the original game server is gone, this is mainly useful for private-server/mock-server research.",
            "The exact WebSocket path is not visible in code object metadata; the bundled SimpleWebSocketServer usually accepts the root path.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build offline NeoX RpcDebug JSON research messages")
    parser.add_argument("command", choices=sorted(RPCS))
    parser.add_argument("value")
    parser.add_argument("--salt", default=DEFAULT_SALT)
    parser.add_argument("--times", type=int, default=1)
    args = parser.parse_args()

    if args.times < 1:
        raise SystemExit("--times must be >= 1")
    print(json.dumps(build_output(args.command, args.value, args.salt, args.times), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
