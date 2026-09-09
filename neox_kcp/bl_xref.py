#!/usr/bin/env python3
"""Find BL (call) xrefs to target addresses in libclient.so."""
import struct
import sys

from so_disasm import So


def bl_xrefs(so: So, targets: set, start=0x2000000, end=0x2300000) -> dict:
    hits = {}
    va = start
    step = 0x100000
    md = so.md
    while va < end:
        size = min(step, end - va)
        try:
            code = so.read(va, size)
        except ValueError:
            va += size
            continue
        for i in md.disasm(code, va):
            if i.mnemonic == "bl":
                try:
                    dst = int(i.op_str.replace("#", ""), 0)
                except ValueError:
                    continue
                if dst in targets:
                    hits.setdefault(dst, []).append(i.address)
        va += size
    return hits


if __name__ == "__main__":
    so = So(sys.argv[1] if len(sys.argv) > 1 else "so_bundle/libclient.so")
    targets = {int(t, 0) for t in sys.argv[2:]}
    refs = bl_xrefs(so, targets)
    for dst, addrs in sorted(refs.items()):
        for a in addrs:
            print(f"call 0x{a:08x} -> 0x{dst:08x}")
