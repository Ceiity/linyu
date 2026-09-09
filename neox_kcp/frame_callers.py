#!/usr/bin/env python3
"""Find callers of a function and report the w2/x2 immediate passed (frame ids)."""
import sys

from so_disasm import So


def callers_with_w2(so: So, target: int, start=0x1f00000, end=0x2300000) -> list:
    hits = []
    va = start
    step = 0x40000
    md = so.md
    while va < end:
        size = min(step, end - va)
        try:
            code = so.read(va, size)
        except ValueError:
            va += size
            continue
        insns = list(md.disasm(code, va))
        for idx, i in enumerate(insns):
            if i.mnemonic == "bl" and i.op_str.lstrip("#") == hex(target):
                # scan back up to 25 insns for the last def of w2/x2
                w2 = None
                for j in range(idx - 1, max(0, idx - 25), -1):
                    p = insns[j]
                    ops = p.op_str.split(", ")
                    if ops and ops[0] in ("w2", "x2"):
                        if p.mnemonic == "mov":
                            try:
                                w2 = int(ops[1].lstrip("#"), 0)
                            except (ValueError, IndexError):
                                w2 = "?"
                        else:
                            w2 = f"reg({p.mnemonic} {p.op_str})"
                        break
                hits.append((i.address, w2))
        va += size
    return hits


if __name__ == "__main__":
    so = So(sys.argv[1] if len(sys.argv) > 1 else "so_bundle/libclient.so")
    target = int(sys.argv[2], 0)
    start = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x1f00000
    end = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x2300000
    for addr, w2 in callers_with_w2(so, target, start, end):
        print(f"call 0x{addr:08x} -> 0x{target:08x}  w2/frame_id = {w2 if isinstance(w2,str) else hex(w2) if w2 is not None else 'None'}")
