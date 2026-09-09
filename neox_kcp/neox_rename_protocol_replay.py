#!/usr/bin/env python3
"""
NeoX rename protocol replay helper for offline/private-server research.

This reproduces the client-side pieces recovered from the old APK:

  * RpcIndex(name + salt) calculation.
  * AreaMessage carrying set_nickname(name) or find_player_by_nid(nid).
  * Native inner frame: uint32_le(length) + uint16_le(0x8000) + AreaMessage.
  * Optional zlib Z_SYNC_FLUSH compression.
  * Stream crypto modes seen in libclient.so:
      0 = RC4
      1 = AES-CFB128, with 128/192/256-bit key selected by key length
      2 = AES-OFB128, with 128/192/256-bit key selected by key length
  * RSA-OAEP wrapping of the SessionKey protobuf.

It is intentionally aimed at your own mock/private server or offline study.
It does not implement account login, old production server auth, KCP itself,
or any bypass for a live service.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import struct
import zlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


FRAME_ID_ENTITY_METHOD = 0x8000
DEFAULT_SALT = "0"
# Static package default: asiocore.set_crypto/get_crypto reads a native global
# whose BSS default is 0, and the recovered script does not call set_crypto.
DEFAULT_CRYPTO_MODE = 0
KCP_CONNECT_HI_CMD = 0x7D
KCP_CONNECT_HI_MAGIC = 0x8FAFD21E25C5E09B

OLD_LOGIN_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA7ax5CGFu8KKAXGUuRbks
bUHSaNvm91DS7qRLOhhNs1j0rSC+O94bfhY84DmCEuyLWwrCXe4Rq0FYatktqksG
RM5buCM/pRwJhcT+GAyJPozM+vkend7jxxScbi8/ojVnAUSD9dBP1TT3DBRta5gb
X10R/XsVTgPDNkH8vP+kqW6dYYUb9TnRtdl+HYz0trOTR7DTdi/BuOkOTrC6azq1
yYQY2HfQOdjiH5oZ8nYaeFnaFfd6FfqmuUV/d0Z2kFRadq02ZwgiL/Xak17vdpOp
U+UIxWAy0N/bE+PL5OycVNh51KUuVHyTF6H3iwXqq0iW8KxQq0/8Gqxhc3lDtl04
fwIDAQAB
-----END PUBLIC KEY-----
"""


@dataclass(frozen=True)
class CryptoMode:
    mode: int
    name: str
    openssl_call: str


CRYPTO_MODES: Dict[int, CryptoMode] = {
    0: CryptoMode(0, "rc4", "RC4_set_key + RC4"),
    1: CryptoMode(1, "aes-cfb128", "AES_set_encrypt_key + AES_cfb128_encrypt"),
    2: CryptoMode(2, "aes-ofb128", "AES_set_encrypt_key + AES_ofb128_encrypt"),
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


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
            raise ValueError(f"unsupported protobuf wire type: {wire_type}")
        fields.append((field_no, wire_type, value))
    return fields


def rpc_index(name: str, salt: str = DEFAULT_SALT) -> int:
    digest = hashlib.md5((name + salt).encode("utf-8")).digest()
    return (
        ((digest[-4] & 0x7F) << 24)
        | (digest[-3] << 16)
        | (digest[-2] << 8)
        | digest[-1]
    )


def rpc_md5(name: str) -> bytes:
    return hashlib.md5(name.encode("utf-8")).digest()


def prop_value(value: Any) -> bytes:
    if isinstance(value, bool):
        return uvar_field(2, int(value))
    if isinstance(value, int):
        return uvar_field(1, value)
    if isinstance(value, str):
        return bytes_field(4, value.encode("utf-8"))
    raise TypeError(f"unsupported argument type: {type(value).__name__}")


def prop_item_value(value: Any) -> bytes:
    return message_field(3, prop_value(value))


def tuple_param(values: Sequence[Any]) -> bytes:
    prop_dict = b"".join(message_field(2, prop_item_value(value)) for value in values)
    return uvar_field(1, 44) + message_field(4, prop_dict)


def method_index_message(name: str, salt: str, include_md5: bool = False) -> bytes:
    payload = b""
    if include_md5:
        payload += bytes_field(1, rpc_md5(name))
    payload += sint32_field(2, rpc_index(name, salt))
    return payload


def area_message(
    rpc_name: str,
    values: Sequence[Any],
    *,
    salt: str = DEFAULT_SALT,
    area_id: bytes = b"",
    guid: Optional[int] = None,
    include_md5: bool = False,
) -> bytes:
    payload = b""
    if area_id:
        payload += bytes_field(1, area_id)
    if guid is not None:
        payload += uvar_field(2, guid)
    payload += message_field(3, method_index_message(rpc_name, salt, include_md5))
    payload += message_field(4, tuple_param(values))
    return payload


def inner_frame(area: bytes) -> bytes:
    body = struct.pack("<H", FRAME_ID_ENTITY_METHOD) + area
    return struct.pack("<I", len(body)) + body


def rename_inner_frame(
    nickname: str,
    *,
    salt: str = DEFAULT_SALT,
    area_id: bytes = b"",
    guid: Optional[int] = None,
    include_md5: bool = False,
) -> bytes:
    return inner_frame(
        area_message(
            "set_nickname",
            [nickname],
            salt=salt,
            area_id=area_id,
            guid=guid,
            include_md5=include_md5,
        )
    )


def rpc_inner_frame(
    rpc_name: str,
    values: Sequence[Any],
    *,
    salt: str = DEFAULT_SALT,
    area_id: bytes = b"",
    guid: Optional[int] = None,
    include_md5: bool = False,
) -> bytes:
    return inner_frame(
        area_message(
            rpc_name,
            values,
            salt=salt,
            area_id=area_id,
            guid=guid,
            include_md5=include_md5,
        )
    )


def search_nid_inner_frame(
    nid: int,
    *,
    salt: str = DEFAULT_SALT,
    area_id: bytes = b"",
    guid: Optional[int] = None,
    include_md5: bool = False,
) -> bytes:
    return rpc_inner_frame(
        "find_player_by_nid",
        [nid],
        salt=salt,
        area_id=area_id,
        guid=guid,
        include_md5=include_md5,
    )


def decode_prop_value(data: bytes) -> Any:
    for field_no, wire_type, value in parse_fields(data):
        if field_no == 1 and wire_type == 0:
            return value
        if field_no == 2 and wire_type == 0:
            return bool(value)
        if field_no == 4 and wire_type == 2:
            return value.decode("utf-8", errors="replace")
    return None


def decode_prop_item(data: bytes) -> Any:
    for field_no, wire_type, value in parse_fields(data):
        if field_no == 3 and wire_type == 2:
            return decode_prop_value(value)
    return None


def decode_tuple_param(data: bytes) -> List[Any]:
    args: List[Any] = []
    for field_no, wire_type, value in parse_fields(data):
        if field_no != 4 or wire_type != 2:
            continue
        for child_no, child_wire, child_value in parse_fields(value):
            if child_no == 2 and child_wire == 2:
                args.append(decode_prop_item(child_value))
    return args


def decode_area_message(data: bytes) -> Dict[str, Any]:
    result: Dict[str, Any] = {"area_id_hex": "", "guid": None, "method_index": None, "args": []}
    for field_no, wire_type, value in parse_fields(data):
        if field_no == 1 and wire_type == 2:
            result["area_id_hex"] = value.hex()
        elif field_no == 2 and wire_type == 0:
            result["guid"] = value
        elif field_no == 3 and wire_type == 2:
            for method_no, method_wire, method_value in parse_fields(value):
                if method_no == 1 and method_wire == 2:
                    result["method_md5_hex"] = method_value.hex()
                elif method_no == 2 and method_wire == 0:
                    result["method_index"] = unzigzag32(method_value)
        elif field_no == 4 and wire_type == 2:
            result["args"] = decode_tuple_param(value)
    return result


def decode_inner_frame(data: bytes) -> Dict[str, Any]:
    if len(data) < 6:
        raise ValueError("inner frame too short")
    size = struct.unpack("<I", data[:4])[0]
    frame_id = struct.unpack("<H", data[4:6])[0]
    if size != len(data) - 4:
        raise ValueError(f"bad length: header={size}, actual={len(data) - 4}")
    if frame_id != FRAME_ID_ENTITY_METHOD:
        raise ValueError(f"bad frame id: 0x{frame_id:04x}")
    decoded = decode_area_message(data[6:])
    decoded["frame_id_hex"] = f"0x{frame_id:04x}"
    return decoded


def zlib_compress_sync(data: bytes) -> bytes:
    compressor = zlib.compressobj()
    return compressor.compress(data) + compressor.flush(zlib.Z_SYNC_FLUSH)


def zlib_decompress(data: bytes) -> bytes:
    return zlib.decompressobj().decompress(data)


class RC4Stream:
    def __init__(self, key_bytes: bytes):
        if not key_bytes:
            raise ValueError("RC4 key must not be empty")
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + key_bytes[i % len(key_bytes)]) & 0xFF
            s[i], s[j] = s[j], s[i]
        self._s = s
        self._i = 0
        self._j = 0

    def update(self, data: bytes) -> bytes:
        out = bytearray()
        s = self._s
        i = self._i
        j = self._j
        for byte in data:
            i = (i + 1) & 0xFF
            j = (j + s[i]) & 0xFF
            s[i], s[j] = s[j], s[i]
            out.append(byte ^ s[(s[i] + s[j]) & 0xFF])
        self._i = i
        self._j = j
        return bytes(out)


class CryptoStream:
    def __init__(self, mode_id: int, session_key: bytes, *, encrypt: bool):
        if mode_id not in CRYPTO_MODES:
            raise ValueError(f"unsupported crypto mode: {mode_id}")
        self.mode_id = mode_id
        self.session_key = session_key
        self.encrypt = encrypt
        if mode_id == 0:
            self._stream = RC4Stream(session_key)
        else:
            key_material, key_bits = native_aes_key_material(session_key)
            if key_material is None:
                # libclient.so logs "will degenerate to rc4" when the selected
                # AES mode/key length cannot be initialized.
                self._stream = RC4Stream(session_key)
                self.effective_mode = "rc4-fallback"
                self.key_bits = None
                return
            iv = b"\x00" * 16
            cipher_mode = modes.CFB(iv) if mode_id == 1 else modes.OFB(iv)
            cipher = Cipher(algorithms.AES(key_material), cipher_mode)
            self._stream = cipher.encryptor() if encrypt else cipher.decryptor()
            self.effective_mode = CRYPTO_MODES[mode_id].name
            self.key_bits = key_bits

    def update(self, data: bytes) -> bytes:
        return self._stream.update(data)


def native_aes_key_material(key_bytes: bytes) -> Tuple[Optional[bytes], Optional[int]]:
    """Approximate libclient.so algorithm_aes::init_key key sizing.

    Static evidence:
      * len <= 23 selects 128 bits
      * 24 <= len <= 31 selects 192 bits
      * len >= 32 selects 256 bits
      * if available bytes are shorter than the selected AES key size, native
        code logs "will degenerate to rc4"

    The production session_key path generates 32 bytes, so it lands on AES-256.
    """
    key_len = len(key_bytes)
    if key_len <= 23:
        needed, bits = 16, 128
    elif key_len <= 31:
        needed, bits = 24, 192
    else:
        needed, bits = 32, 256
    if key_len < needed:
        return None, None
    return key_bytes[:needed].ljust(needed, b"\x00"), bits


def seal_payload(data: bytes, session_key: bytes, mode_id: int, *, compress: bool = False) -> bytes:
    plain = zlib_compress_sync(data) if compress else data
    return CryptoStream(mode_id, session_key, encrypt=True).update(plain)


def open_payload(data: bytes, session_key: bytes, mode_id: int, *, compressed: bool = False) -> bytes:
    plain = CryptoStream(mode_id, session_key, encrypt=False).update(data)
    return zlib_decompress(plain) if compressed else plain


def public_key_from_pem(pem: bytes):
    return serialization.load_pem_public_key(pem)


def private_key_from_pem(pem: bytes):
    return serialization.load_pem_private_key(pem, password=None)


def rsa_oaep_encrypt(public_key_pem: bytes, data: bytes) -> bytes:
    public_key = public_key_from_pem(public_key_pem)
    return public_key.encrypt(
        data,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None,
        ),
    )


def rsa_oaep_decrypt(private_key_pem: bytes, data: bytes) -> bytes:
    private_key = private_key_from_pem(private_key_pem)
    return private_key.decrypt(
        data,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None,
        ),
    )


def make_encrypt_string(ciphertext: bytes) -> bytes:
    return bytes_field(1, ciphertext)


def parse_encrypt_string(data: bytes) -> bytes:
    for field_no, wire_type, value in parse_fields(data):
        if field_no == 1 and wire_type == 2:
            return value
    raise ValueError("EncryptString.field1 missing")


def seed_session_digest(seed: int, session_key: bytes, layout: str) -> bytes:
    if layout == "seed-key":
        material = str(seed).encode("ascii") + session_key
    elif layout == "key-seed":
        material = session_key + str(seed).encode("ascii")
    elif layout == "key-only":
        material = session_key
    else:
        raise ValueError(f"unsupported digest layout: {layout}")
    return hashlib.sha1(material).digest()


def digest64(digest: bytes) -> int:
    return int.from_bytes(digest[:8], "big", signed=False)


def make_session_key_message(
    *,
    session_key: bytes,
    seed: int,
    crypto_mode: int,
    padding_header: bytes,
    padding_tail: bytes,
    digest_layout: str = "seed-key",
    session_layout: str = "key-in-field2",
) -> bytes:
    digest = seed_session_digest(seed, session_key, digest_layout)

    if session_layout == "key-in-field2":
        # Most useful private-server layout: the RSA-protected message contains
        # the stream key in field 2, while field 3 carries a SHA1-derived check.
        field2 = session_key
        field3 = digest64(digest)
    elif session_layout == "digest-in-field2":
        # Alternate layout suggested by one reading of the obfuscated script.
        # Keep it available for packet/log comparison.
        field2 = digest
        field3 = seed
    else:
        raise ValueError(f"unsupported session layout: {session_layout}")

    msg = b""
    msg += bytes_field(1, padding_header)
    msg += bytes_field(2, field2)
    msg += uvar_field(3, field3)
    msg += bytes_field(4, padding_tail)
    if crypto_mode >= 1:
        msg += uvar_field(5, crypto_mode)
    return msg


def parse_session_key_message(data: bytes) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for field_no, wire_type, value in parse_fields(data):
        if field_no in (1, 2, 4) and wire_type == 2:
            result[f"field{field_no}_hex"] = value.hex()
            result[f"field{field_no}_len"] = len(value)
        elif field_no in (3, 5) and wire_type == 0:
            result[f"field{field_no}"] = value
    return result


def generate_demo_private_key() -> bytes:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def public_pem_from_private(private_key_pem: bytes) -> bytes:
    private_key = private_key_from_pem(private_key_pem)
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def make_random_session_material(
    *,
    seed: Optional[int],
    session_key_hex: str,
    crypto_mode: int,
    digest_layout: str,
    session_layout: str,
) -> Dict[str, Any]:
    if seed is None:
        seed = secrets.randbits(63)
    session_key = bytes.fromhex(session_key_hex) if session_key_hex else secrets.token_bytes(32)
    if len(session_key) != 32:
        raise ValueError("session_key must be exactly 32 bytes for AES-compatible replay")
    padding_header = secrets.token_bytes(2)
    padding_tail = secrets.token_bytes(9)
    msg = make_session_key_message(
        session_key=session_key,
        seed=seed,
        crypto_mode=crypto_mode,
        padding_header=padding_header,
        padding_tail=padding_tail,
        digest_layout=digest_layout,
        session_layout=session_layout,
    )
    return {
        "seed": seed,
        "session_key": session_key,
        "padding_header": padding_header,
        "padding_tail": padding_tail,
        "session_key_message": msg,
    }


def known_indices(salt: str) -> Dict[str, int]:
    return {
        "set_nickname": rpc_index("set_nickname", salt),
        "on_set_nickname": rpc_index("on_set_nickname", salt),
        "find_player_by_nid": rpc_index("find_player_by_nid", salt),
        "find_player_by_name": rpc_index("find_player_by_name", salt),
        "on_query_player_profile": rpc_index("on_query_player_profile", salt),
        "friend_request": rpc_index("friend_request", salt),
    }


def callback_payload(
    callback_name: str,
    values: Sequence[Any],
    *,
    salt: str = DEFAULT_SALT,
    entity_id: bytes = b"",
    guid: Optional[int] = None,
    include_md5: bool = False,
) -> bytes:
    """Build the business callback payload before the gate-client wrapper.

    Static evidence confirms the final Python entry as
    ClientEntity.entity_method(md5, index, args). The exact server->client
    gate service frame number still needs a live trace or deeper native
    disassembly, so this helper deliberately returns the EntityMessage-like
    payload only, without claiming to be a complete wire packet.
    """

    return area_message(
        callback_name,
        values,
        salt=salt,
        area_id=entity_id,
        guid=guid,
        include_md5=include_md5,
    )


def print_hex_block(label: str, data: bytes) -> None:
    print(f"{label}_hex={data.hex()}")
    print(f"{label}_base64={base64.b64encode(data).decode('ascii')}")


def cmd_info(args: argparse.Namespace) -> None:
    print(_json({
        "purpose": "offline/private-server NeoX rename protocol study",
        "inner_frame": "uint32_le(length) + uint16_le(0x8000) + AreaMessage",
        "rename_rpc": {
            "name": "set_nickname",
            "index_salt_0": rpc_index("set_nickname", "0"),
            "index_salt_0_hex": f"0x{rpc_index('set_nickname', '0'):08x}",
        },
        "crypto_modes": {mode: mode_info.__dict__ for mode, mode_info in CRYPTO_MODES.items()},
        "native_crypto_details": {
            "static_default_mode": {
                "value": DEFAULT_CRYPTO_MODE,
                "name": CRYPTO_MODES[DEFAULT_CRYPTO_MODE].name,
                "evidence": "get_crypto reads native global 0x515a89c; set_crypto writes it; BSS default is 0; recovered scripts do not call set_crypto",
                "status": "high probability for this APK, unless patched or changed by startup code not present in recovered scripts",
            },
            "mode_selector": "0x212efc8 returns AES-CFB table for mode=1, AES-OFB table for mode=2, RC4 table otherwise",
            "aes_cfb_function": "0x212fa80 -> AES_cfb128_encrypt",
            "aes_ofb_function": "0x212fac0 -> AES_ofb128_encrypt",
            "rc4_function": "0x212fafc -> RC4",
            "key_init_function": "0x212eff4",
            "key_bits_by_length": {
                "<16": "RC4 fallback when AES mode requested",
                "16..23": "AES-128",
                "24..31": "AES-192",
                "32+": "AES-256",
            },
            "session_key_path": "seed_reply creates a 32-byte session_key, so AES mode uses AES-256",
            "iv_status": "AES IV pointer is this+8 in native; initial IV bytes still need runtime trace, this helper uses zero IV for offline comparison",
        },
        "compression": {
            "name": "zlib",
            "flush": "Z_SYNC_FLUSH",
            "default_zipped_channel": 0,
        },
        "rsa": {
            "key_bits": 2048,
            "padding": "RSA_PKCS1_OAEP_PADDING / SHA1 OAEP",
            "public_exponent": 65537,
            "modulus_sha256": "fe70e796776441fc0ac1ae1010d4761c2edc558621f1fc443aadbc5670dae37c",
            "public_key_pem": OLD_LOGIN_PUBLIC_KEY_PEM.decode("ascii"),
        },
        "transport_outer_header": {
            "status": "partially recovered",
            "confirmed_inner_business_frame": "uint32_le(length) + uint16_le(0x8000) + AreaMessage",
            "confirmed_raw_control_send": {
                "send_function": "0x20696d4",
                "send_sink": "sendmsg when connection fd/socket is ready; queued virtual path otherwise",
                "control_packet_size": 0x1E,
                "builders": {
                    "0x214d214": "builds 30-byte control packet with byte[5]=0x09",
                    "0x214d284": "builds 30-byte control packet with byte[5]=0x10",
                },
                "partial_layout": {
                    "+0x00": "uint32 masked(this+0x200) | global bits | 0x80000001",
                    "+0x04": "uint8 copied from this+0x2ac",
                    "+0x05": "uint8 phase/code, observed 0x09 or 0x10",
                    "+0x06": "uint64 copied from this+0x278 in 0x09 path",
                    "+0x0e": "uint16 copied from this+0x280 in 0x09 path",
                    "+0x10..+0x1d": "not yet recovered",
                },
            },
            "confirmed_handshake_header_sizes": {
                "selector": "first halfword == 2",
                "if_equal": "0x10 bytes",
                "else": "0x1c bytes",
                "second_halfword": "compared against this+0x28e in one path",
                "status": "field names unknown; sizes confirmed from csel logic",
            },
            "kcp_connect_hi_candidate": {
                "function": "0x214c2f0",
                "internal_cmd_marker": f"0x{KCP_CONNECT_HI_CMD:02x}",
                "internal_magic": f"0x{KCP_CONNECT_HI_MAGIC:016x}",
                "magic_little_endian_bytes": KCP_CONNECT_HI_MAGIC.to_bytes(8, "little").hex(),
                "status": "confirmed as internal parsed-structure comparison; raw socket byte layout still unconfirmed",
            },
            "native_error_strings": [
                "invalid magic",
                "invalid cmd",
                "unsupported version",
                "invalid len",
                "bad size()",
                "invalid size()",
                "need_bytes_",
            ],
            "not_yet_confirmed": [
                "raw-wire offset of the internal magic constant",
                "official names for 0x09/0x10 control packet codes",
                "connection header byte order beyond observed native stores",
                "server-to-client gate method frame id",
            ],
        },
        "important_note": (
            "The old public key can encrypt the SessionKey, but a private server "
            "needs the matching private key. For your own server, replace the APK "
            "public key with your own public key."
        ),
    }))


def cmd_kcp_info(args: argparse.Namespace) -> None:
    print(_json({
        "status": "outer KCP/TCP handshake partially recovered",
        "confirmed_from_native_disassembly": {
            "function": "0x214c2f0",
            "comparison_1": "ldr w8, [x1]; cmp w8, #0x7d",
            "comparison_2": "ldr x8, [x1+8]; ldr x8, [x8+8]; cmp x8, #0x8fafd21e25c5e09b",
            "cmd_or_marker": KCP_CONNECT_HI_CMD,
            "cmd_or_marker_hex": f"0x{KCP_CONNECT_HI_CMD:02x}",
            "magic": KCP_CONNECT_HI_MAGIC,
            "magic_hex": f"0x{KCP_CONNECT_HI_MAGIC:016x}",
            "magic_little_endian_bytes": KCP_CONNECT_HI_MAGIC.to_bytes(8, "little").hex(),
            "related_strings": [
                "handle_connect_hi",
                "invalid magic:",
                "invalid cmd:",
                "handle_connect_mh_common",
                "handle_connect_mh_1",
                "handle_connect_mh_2",
                "handle_connect_1",
                "kcp sync code error:",
                "handle_connect_2",
            ],
        },
        "partially_confirmed": {
            "raw_send": {
                "function": "0x20696d4",
                "arguments": "x0=this, x1=buffer, w2=size",
                "confirmed_sink": "PLT/GOT maps 0x990000 to sendmsg",
                "nonblocking_helper": "PLT/GOT maps 0x983b60 to poll",
            },
            "thirty_byte_control_packets": {
                "size": 30,
                "0x214d214": {
                    "buffer": "this+0x248",
                    "byte_5": "0x09",
                    "tail_call": "0x20696d4",
                    "known_fields": {
                        "+0x00": "uint32 masked(this+0x200) | global bits | 0x80000001",
                        "+0x04": "uint8 copied from this+0x2ac",
                        "+0x05": "0x09",
                        "+0x06": "uint64 copied from this+0x278",
                        "+0x0e": "uint16 copied from this+0x280",
                    },
                },
                "0x214d284": {
                    "buffer": "this+0x248",
                    "byte_5": "0x10",
                    "call": "0x20696d4",
                    "known_fields": {
                        "+0x00": "uint32 masked(this+0x200) | global bits | 0x80000001",
                        "+0x04": "uint8 copied from this+0x2ac",
                        "+0x05": "0x10",
                    },
                },
            },
            "handshake_header_sizes": {
                "selector": "first halfword == 2",
                "length_if_selector_2": "0x10",
                "length_otherwise": "0x1c",
                "comparison": "remote +2 halfword compared with local this+0x28e",
            },
            "connect_buffer_state_offsets": {
                "this+0x28c": "halfword used to choose 0x10 or 0x1c byte operation length",
                "this+0x28e": "halfword compared with received header +2 in 0x214e720",
                "this+0x290": "word copied into a stack structure during mode==2 path",
                "this+0x2b4": "retry/counter, stops at 0x10",
                "this+0x2b8": "seen-hi flag used by handle_connect_hi",
            },
            "send_recv_chunk": "socket path uses a 0x4000 buffer around 0x20696e4",
        },
        "not_yet_confirmed": [
            "raw-wire offset of internal 0x7d marker and 0x8fafd21e25c5e09b magic",
            "endianness and exact field order for the remaining outer connection header bytes",
            "official names for 0x09/0x10 control packet codes",
            "KCP conv/token/sync-code raw placement",
        ],
    }))


def cmd_salt_info(args: argparse.Namespace) -> None:
    send = known_indices(args.send_salt)
    recv = {
        "on_set_nickname": rpc_index("on_set_nickname", args.recv_salt),
        "on_query_player_profile": rpc_index("on_query_player_profile", args.recv_salt),
        "on_friend_request": rpc_index("on_friend_request", args.recv_salt),
    }
    print(_json({
        "status": "salt defaults confirmed; nonzero runtime salt not found in static package",
        "evidence": {
            "RpcIndex.nxs": [
                "DEFAULT_RECV_RPC_SALT = '0'",
                "DEFAULT_SEND_RPC_SALT = '0'",
                "send_rpc_index(name) uses SEND_RPC_SALT",
                "recv_rpc_index(name) uses RECV_RPC_SALT",
                "optional _PRESET_RPC_INDEXES.py can override cached indexes/salts",
            ],
            "package_search": "_PRESET_RPC_INDEXES.py not found in recovered nxs tree",
            "Md5OrIndexCodec.nxs": "dynamic exchange is md5<->index mapping, not proven to be a random per-session salt",
            "native_strings": ["set_rpc_index", "clear_rpc_index", "send_reg_md5_index"],
        },
        "algorithm": "index = big_endian_last4(md5(name + salt)) & 0x7fffffff",
        "send_salt": args.send_salt,
        "recv_salt": args.recv_salt,
        "client_to_server_indexes": send,
        "server_to_client_callback_indexes": recv,
        "md5_without_salt": {
            name: rpc_md5(name).hex()
            for name in (
                "set_nickname",
                "on_set_nickname",
                "find_player_by_nid",
                "on_query_player_profile",
            )
        },
    }))


def cmd_rename_callback(args: argparse.Namespace) -> None:
    payload = callback_payload(
        "on_set_nickname",
        [args.result, args.msg],
        salt=args.recv_salt,
        entity_id=bytes.fromhex(args.entity_id_hex) if args.entity_id_hex else b"",
        guid=args.guid,
        include_md5=args.include_md5,
    )
    output: Dict[str, Any] = {
        "wire_packet": False,
        "status": "business callback payload recovered; gate-client wrapper still unverified",
        "python_entry": "ClientEntity.entity_method(md5, index, args)",
        "callback": "on_set_nickname(result, msg)",
        "recv_salt": args.recv_salt,
        "callback_index": rpc_index("on_set_nickname", args.recv_salt),
        "callback_index_hex": f"0x{rpc_index('on_set_nickname', args.recv_salt):08x}",
        "callback_md5_hex": rpc_md5("on_set_nickname").hex(),
        "args": [args.result, args.msg],
        "payload_hex": payload.hex(),
        "payload_base64": base64.b64encode(payload).decode("ascii"),
        "decoded_as_area_like_payload": decode_area_message(payload),
        "not_yet_confirmed": [
            "server-to-client gate service frame id",
            "whether this payload is carried as EntityMessage with extra route/id fields in this build",
            "encrypted outer connection header bytes",
        ],
    }
    if args.candidate_frame:
        candidate = inner_frame(payload)
        output["candidate_0x8000_frame_warning"] = (
            "0x8000 is confirmed for client->server entity_method; "
            "using it for server->client callbacks is only a comparison aid."
        )
        output["candidate_0x8000_frame_hex"] = candidate.hex()
    print(_json(output))


def cmd_wire_layout(args: argparse.Namespace) -> None:
    print(_json({
        "confirmed": [
            "network_config.nxs sets protocol='KCP', enforce_encryption=1, zipped_channel=0",
            "client on connect sends send_seed_request when encryption is enforced",
            "seed_reply(seed) creates 32-byte session_key material and sends send_session_key",
            "native has RSA login_key_encrypter, zlib_compressor, arc4_crypter, aes_crypter",
            "after session_key_ok/connect_reply, business RPC goes through area.call_server",
            "set_nickname(name) inner frame is uint32_le(length) + uint16_le(0x8000) + AreaMessage",
        ],
        "partially_confirmed": [
            "stream order is compress before encrypt on output, decrypt before decompress on input",
            "AES path uses AES_set_encrypt_key + AES_cfb128_encrypt/AES_ofb128_encrypt with 32-byte key",
            "RC4 path exists and logs 'enable rc4 crypter'; AES failure can degenerate to RC4",
            "default mode for this static APK is likely 0/RC4 because set_crypto global defaults to 0 and scripts do not call set_crypto",
            "native connection layer checks magic/cmd/version/len before normal traffic",
        ],
        "not_confirmed_yet": [
            "exact KCP/TCP connection handshake magic bytes",
            "exact magic/cmd/version/len field offsets and byte order",
            "server-to-client outer frame id for send_entity_message/entity_method",
            "whether production server ever changed SEND/RECV salt away from '0'",
        ],
        "client_to_server_rename_stack": [
            "set_nickname(name)",
            "send_rpc_index('set_nickname')",
            "AreaMessage.method.index + tuple parameters",
            "uint32_le length + uint16_le 0x8000",
            "optional zlib Z_SYNC_FLUSH if zipped_channel enabled",
            "RC4 or AES stream encryption after enable_encrypter",
            "KCP/TCP connection wrapper with still-unrecovered magic/cmd/version/len handshake",
        ],
    }))


def cmd_rename_frame(args: argparse.Namespace) -> None:
    area_id = bytes.fromhex(args.area_id_hex) if args.area_id_hex else args.area_id.encode("utf-8")
    frame = rename_inner_frame(
        args.nickname,
        salt=args.salt,
        area_id=area_id,
        guid=args.guid,
        include_md5=args.include_md5,
    )
    print(_json({
        "network_ready": False,
        "rpc_name": "set_nickname",
        "rpc_index": rpc_index("set_nickname", args.salt),
        "rpc_index_hex": f"0x{rpc_index('set_nickname', args.salt):08x}",
        "frame_id_hex": f"0x{FRAME_ID_ENTITY_METHOD:04x}",
        "inner_frame_hex": frame.hex(),
        "inner_frame_base64": base64.b64encode(frame).decode("ascii"),
        "decoded": decode_inner_frame(frame),
    }))


def cmd_search_nid_frame(args: argparse.Namespace) -> None:
    area_id = bytes.fromhex(args.area_id_hex) if args.area_id_hex else args.area_id.encode("utf-8")
    frame = search_nid_inner_frame(
        args.nid,
        salt=args.salt,
        area_id=area_id,
        guid=args.guid,
        include_md5=args.include_md5,
    )
    print(_json({
        "network_ready": False,
        "rpc_name": "find_player_by_nid",
        "rpc_index": rpc_index("find_player_by_nid", args.salt),
        "rpc_index_hex": f"0x{rpc_index('find_player_by_nid', args.salt):08x}",
        "rpc_md5_hex": rpc_md5("find_player_by_nid").hex(),
        "argument": {"nid": args.nid, "type": "int"},
        "frame_id_hex": f"0x{FRAME_ID_ENTITY_METHOD:04x}",
        "inner_frame_hex": frame.hex(),
        "inner_frame_base64": base64.b64encode(frame).decode("ascii"),
        "decoded": decode_inner_frame(frame),
        "not_included": [
            "login/auth token",
            "seed/session key handshake",
            "compression/encryption",
            "TCP/KCP transport",
            "live avatar area context unless --area-id/--guid are supplied",
        ],
    }))


def cmd_profile_callback_shape(args: argparse.Namespace) -> None:
    callback = "on_query_player_profile"
    example_avatar = {
        "id": args.avatar_id,
        "eid": args.avatar_id,
        "nid": args.nid,
        "nickname": args.nickname,
        "default_name": args.default_name,
        "avatar_img_id": args.avatar_img_id,
        "avatar_img_url": args.avatar_img_url,
        "avatar_frame_id": args.avatar_frame_id,
        "nickname_frame_id": args.nickname_frame_id,
        "pvp_status": args.pvp_status,
        "logout_time": args.logout_time,
        "login_time": args.login_time,
        "hall_space_id": args.hall_space_id,
        "gender": args.gender,
        "is_info_pub": args.is_info_pub,
        "qualify_level": args.qualify_level,
        "can_add": args.can_add,
        "can_chat": args.can_chat,
    }
    info = {
        "result": args.result,
        "errcode": args.errcode,
        "data": {
            "avatar_info": {
                str(args.avatar_id): example_avatar,
            },
        },
    }
    ui_search_item = {
        "id": example_avatar["id"],
        "nid": example_avatar["nid"],
        "name": example_avatar["nickname"] or example_avatar["default_name"],
        "head_id": example_avatar["avatar_img_id"],
        "head_url": example_avatar["avatar_img_url"],
        "head_frame_id": example_avatar["avatar_frame_id"],
        "situation": "ui_helper.get_social_state(pvp_status)",
        "can_add": example_avatar["can_add"],
        "can_chat": example_avatar["can_chat"],
        "offline_time": example_avatar["logout_time"],
    }
    print(_json({
        "wire_packet": False,
        "status": "callback data shape for private-server/mock research; exact raw server wrapper still unverified",
        "callback": "on_query_player_profile(info)",
        "recv_salt": args.recv_salt,
        "callback_index": rpc_index(callback, args.recv_salt),
        "callback_index_hex": f"0x{rpc_index(callback, args.recv_salt):08x}",
        "callback_md5_hex": rpc_md5(callback).hex(),
        "confirmed_script_chain": [
            "AvatarMember.on_query_player_profile(info)",
            "Globals.model.handle_query_player_profile(result, data/info)",
            "Globals.g_ui_manager.receive_msg(UIData.PLAYER_PROFILE, result, info)",
            "SocialSearchResultPanel.on_search_result_arrived(...)",
            "SocialSearchResultPanel.convert_data_to_format_data(ori_data)",
            "SearchResultItem.set_data(data)",
        ],
        "server_info_shape": info,
        "nickname_to_ui_name_mapping": {
            "server_field": "data.avatar_info[*].nickname",
            "fallback_field": "data.avatar_info[*].default_name",
            "ui_field": "name",
            "ui_display_consumer": "SearchResultItem.set_data -> node.root.name.setString(name)",
        },
        "search_result_item_shape": ui_search_item,
        "field_status": {
            "result_errcode_data": "field names confirmed from ImpPersonal.on_query_player_profile metadata; exact branch logic not fully disassembled",
            "avatar_info": "field name confirmed from SocialSearchResultPanel/SocialPersonalInfoPanel metadata; exact nesting requires real packet or full custom-opcode decompile",
            "nickname_default_name_to_name": "field names confirmed in one converter function; exact fallback branch is high probability, not fully verified",
            "id_nid_head_fields_can_add_can_chat": "field names confirmed as SearchResultItem.set_data metadata; precise control flow still limited by custom NXS opcode",
            "exact raw server-to-client outer frame": "not yet confirmed",
            "whether data.avatar_info is keyed by id/eid in every server response": "high probability, but not fully verified by live packet",
        },
    }))


def cmd_session_key(args: argparse.Namespace) -> None:
    material = make_random_session_material(
        seed=args.seed,
        session_key_hex=args.session_key_hex,
        crypto_mode=args.crypto_mode,
        digest_layout=args.digest_layout,
        session_layout=args.session_layout,
    )
    public_key_pem = (
        open(args.public_key_pem, "rb").read()
        if args.public_key_pem
        else OLD_LOGIN_PUBLIC_KEY_PEM
    )
    session_msg = material["session_key_message"]
    encrypted = rsa_oaep_encrypt(public_key_pem, session_msg)
    encrypt_string = make_encrypt_string(encrypted)
    print(_json({
        "seed": material["seed"],
        "crypto_mode": args.crypto_mode,
        "crypto_name": CRYPTO_MODES[args.crypto_mode].name,
        "session_layout": args.session_layout,
        "digest_layout": args.digest_layout,
        "session_key_hex": material["session_key"].hex(),
        "session_key_message_hex": session_msg.hex(),
        "session_key_fields": parse_session_key_message(session_msg),
        "rsa_padding": "OAEP(SHA1, MGF1-SHA1)",
        "encrypt_string_hex": encrypt_string.hex(),
        "encrypt_string_base64": base64.b64encode(encrypt_string).decode("ascii"),
        "note": "This is the RSA-protected send_session_key payload, not the later stream ciphertext.",
    }))


def cmd_encrypt_rename(args: argparse.Namespace) -> None:
    session_key = bytes.fromhex(args.session_key_hex) if args.session_key_hex else b"A" * 32
    frame = rename_inner_frame(args.nickname, salt=args.salt)
    sealed = seal_payload(frame, session_key, args.crypto_mode, compress=args.compress)
    opened = open_payload(sealed, session_key, args.crypto_mode, compressed=args.compress)
    print(_json({
        "rpc_name": "set_nickname",
        "crypto_mode": args.crypto_mode,
        "crypto_name": CRYPTO_MODES[args.crypto_mode].name,
        "compressed_before_encrypt": args.compress,
        "session_key_hex": session_key.hex(),
        "plain_inner_frame_hex": frame.hex(),
        "ciphertext_hex": sealed.hex(),
        "ciphertext_base64": base64.b64encode(sealed).decode("ascii"),
        "roundtrip_ok": opened == frame,
        "decoded_after_decrypt": decode_inner_frame(opened),
    }))


def cmd_mock_demo(args: argparse.Namespace) -> None:
    private_key_pem = generate_demo_private_key()
    public_key_pem = public_pem_from_private(private_key_pem)
    material = make_random_session_material(
        seed=args.seed,
        session_key_hex=args.session_key_hex,
        crypto_mode=args.crypto_mode,
        digest_layout=args.digest_layout,
        session_layout="key-in-field2",
    )

    client_session_msg = material["session_key_message"]
    client_encrypt_string = make_encrypt_string(rsa_oaep_encrypt(public_key_pem, client_session_msg))

    server_ciphertext = parse_encrypt_string(client_encrypt_string)
    server_session_msg = rsa_oaep_decrypt(private_key_pem, server_ciphertext)
    server_fields = parse_session_key_message(server_session_msg)
    server_session_key = bytes.fromhex(server_fields["field2_hex"])

    plain_frame = rename_inner_frame(args.nickname, salt=args.salt)
    client_ciphertext = seal_payload(
        plain_frame,
        material["session_key"],
        args.crypto_mode,
        compress=args.compress,
    )
    server_plain = open_payload(
        client_ciphertext,
        server_session_key,
        args.crypto_mode,
        compressed=args.compress,
    )
    decoded = decode_inner_frame(server_plain)
    index_to_name = {value: key for key, value in known_indices(args.salt).items()}
    decoded["rpc_name_guess"] = index_to_name.get(decoded["method_index"], "unknown")

    print(_json({
        "demo": "client -> RSA-OAEP SessionKey -> enable crypto -> encrypted set_nickname -> server decrypts",
        "uses_demo_rsa_key": True,
        "why_demo_key": "The old APK only contains the public key; your server needs its own private key.",
        "seed": material["seed"],
        "crypto_mode": args.crypto_mode,
        "crypto_name": CRYPTO_MODES[args.crypto_mode].name,
        "compressed_before_encrypt": args.compress,
        "client_session_key_hex": material["session_key"].hex(),
        "send_session_key_encrypt_string_hex": client_encrypt_string.hex(),
        "server_recovered_session_key_ok": server_session_key == material["session_key"],
        "encrypted_rename_payload_hex": client_ciphertext.hex(),
        "server_decoded_rename": decoded,
        "mock_callback": {
            "name": "on_set_nickname",
            "result": True,
            "msg": "",
            "new_name": args.nickname,
        },
    }))


def cmd_self_test(args: argparse.Namespace) -> None:
    assert rpc_index("set_nickname", "0") == 1648625260
    assert rpc_index("find_player_by_nid", "0") == 1288662083
    assert rpc_index("find_player_by_name", "0") == 1815379889

    frame = rename_inner_frame("test")
    decoded = decode_inner_frame(frame)
    assert decoded["method_index"] == 1648625260
    assert decoded["args"] == ["test"]

    search_frame = search_nid_inner_frame(123456)
    search_decoded = decode_inner_frame(search_frame)
    assert search_decoded["method_index"] == 1288662083
    assert search_decoded["args"] == [123456]

    for mode_id in (0, 1, 2):
        session_key = bytes(range(32))
        sealed = seal_payload(frame, session_key, mode_id, compress=False)
        opened = open_payload(sealed, session_key, mode_id, compressed=False)
        assert opened == frame

        sealed_z = seal_payload(frame, session_key, mode_id, compress=True)
        opened_z = open_payload(sealed_z, session_key, mode_id, compressed=True)
        assert opened_z == frame

    private_key = generate_demo_private_key()
    public_key = public_pem_from_private(private_key)
    msg = make_session_key_message(
        session_key=bytes(range(32)),
        seed=123456,
        crypto_mode=1,
        padding_header=b"ab",
        padding_tail=b"123456789",
    )
    enc = rsa_oaep_encrypt(public_key, msg)
    assert rsa_oaep_decrypt(private_key, enc) == msg
    print("self-test: OK")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline NeoX rename protocol replay helper",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="print recovered protocol and crypto facts").set_defaults(func=cmd_info)
    sub.add_parser("wire-layout", help="print confirmed and unresolved wire layers").set_defaults(func=cmd_wire_layout)
    sub.add_parser("kcp-info", help="print partially recovered KCP outer handshake facts").set_defaults(func=cmd_kcp_info)

    p = sub.add_parser("salt-info", help="print RpcIndex salt/index facts")
    p.add_argument("--send-salt", default=DEFAULT_SALT)
    p.add_argument("--recv-salt", default=DEFAULT_SALT)
    p.set_defaults(func=cmd_salt_info)

    p = sub.add_parser("rename-frame", help="build plaintext set_nickname inner frame")
    p.add_argument("nickname")
    p.add_argument("--salt", default=DEFAULT_SALT)
    p.add_argument("--area-id", default="")
    p.add_argument("--area-id-hex", default="")
    p.add_argument("--guid", type=int)
    p.add_argument("--include-md5", action="store_true")
    p.set_defaults(func=cmd_rename_frame)

    p = sub.add_parser("search-nid-frame", help="build plaintext find_player_by_nid inner frame")
    p.add_argument("nid", type=int)
    p.add_argument("--salt", default=DEFAULT_SALT)
    p.add_argument("--area-id", default="")
    p.add_argument("--area-id-hex", default="")
    p.add_argument("--guid", type=int)
    p.add_argument("--include-md5", action="store_true")
    p.set_defaults(func=cmd_search_nid_frame)

    p = sub.add_parser("rename-callback", help="build on_set_nickname callback payload template")
    p.add_argument("--recv-salt", default=DEFAULT_SALT)
    p.add_argument("--result", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--msg", default="")
    p.add_argument("--entity-id-hex", default="")
    p.add_argument("--guid", type=int)
    p.add_argument("--include-md5", action="store_true")
    p.add_argument("--candidate-frame", action="store_true")
    p.set_defaults(func=cmd_rename_callback)

    p = sub.add_parser("profile-callback-shape", help="print on_query_player_profile(info) callback shape")
    p.add_argument("--recv-salt", default=DEFAULT_SALT)
    p.add_argument("--result", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--errcode", type=int, default=0)
    p.add_argument("--avatar-id", default="avatar_123456")
    p.add_argument("--nid", type=int, default=123456)
    p.add_argument("--nickname", default="淋雨大佬")
    p.add_argument("--default-name", default="")
    p.add_argument("--avatar-img-id", type=int, default=520)
    p.add_argument("--avatar-img-url", default="")
    p.add_argument("--avatar-frame-id", type=int, default=6)
    p.add_argument("--nickname-frame-id", type=int, default=0)
    p.add_argument("--pvp-status", type=int, default=0)
    p.add_argument("--logout-time", type=int, default=0)
    p.add_argument("--login-time", type=int, default=0)
    p.add_argument("--hall-space-id", default="")
    p.add_argument("--gender", type=int, default=0)
    p.add_argument("--is-info-pub", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--qualify-level", type=int, default=0)
    p.add_argument("--can-add", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--can-chat", action=argparse.BooleanOptionalAction, default=True)
    p.set_defaults(func=cmd_profile_callback_shape)

    p = sub.add_parser("session-key", help="build RSA-OAEP send_session_key payload")
    p.add_argument("--seed", type=int)
    p.add_argument("--crypto-mode", type=int, choices=sorted(CRYPTO_MODES), default=DEFAULT_CRYPTO_MODE)
    p.add_argument("--session-key-hex", default="")
    p.add_argument("--public-key-pem", default="")
    p.add_argument("--digest-layout", choices=("seed-key", "key-seed", "key-only"), default="seed-key")
    p.add_argument("--session-layout", choices=("key-in-field2", "digest-in-field2"), default="key-in-field2")
    p.set_defaults(func=cmd_session_key)

    p = sub.add_parser("encrypt-rename", help="encrypt a set_nickname inner frame with RC4/AES")
    p.add_argument("nickname")
    p.add_argument("--salt", default=DEFAULT_SALT)
    p.add_argument("--crypto-mode", type=int, choices=sorted(CRYPTO_MODES), default=DEFAULT_CRYPTO_MODE)
    p.add_argument("--session-key-hex", default="")
    p.add_argument("--compress", action="store_true")
    p.set_defaults(func=cmd_encrypt_rename)

    p = sub.add_parser("mock-demo", help="one-shot private-server style rename demo")
    p.add_argument("nickname")
    p.add_argument("--salt", default=DEFAULT_SALT)
    p.add_argument("--seed", type=int)
    p.add_argument("--crypto-mode", type=int, choices=sorted(CRYPTO_MODES), default=DEFAULT_CRYPTO_MODE)
    p.add_argument("--session-key-hex", default="")
    p.add_argument("--digest-layout", choices=("seed-key", "key-seed", "key-only"), default="seed-key")
    p.add_argument("--compress", action="store_true")
    p.set_defaults(func=cmd_mock_demo)

    sub.add_parser("self-test", help="run local checks").set_defaults(func=cmd_self_test)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.func(args)
        return 0
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
