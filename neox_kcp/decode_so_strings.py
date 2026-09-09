#!/usr/bin/env python3
"""Extract strings protected by the byte transform used in this libclient.so."""

import argparse
import re
from pathlib import Path


def ror8(value: int, count: int) -> int:
    count &= 7
    return ((value >> count) | (value << (8 - count))) & 0xFF


def decode_byte(value: int) -> int:
    return ror8(value ^ 0xE6, 5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("binary")
    ap.add_argument("--pattern", default="")
    ap.add_argument("--min-length", type=int, default=4)
    args = ap.parse_args()

    data = Path(args.binary).read_bytes()
    pattern = re.compile(args.pattern, re.I) if args.pattern else None
    start = 0
    for end, value in enumerate(data):
        if value != 0xE6:
            continue
        raw = data[start:end]
        start = end + 1
        if len(raw) < args.min_length:
            continue
        decoded = bytes(decode_byte(x) for x in raw)
        # Encoded strings in this build are mostly ASCII. Reject chunks that
        # clearly cross non-string binary data, but retain tabs/newlines.
        if not all(x in (9, 10, 13) or 32 <= x < 127 for x in decoded):
            continue
        text = decoded.decode("ascii")
        if pattern and not pattern.search(text):
            continue
        print(f"{end - len(raw):08x}\t{text}")


if __name__ == "__main__":
    main()
