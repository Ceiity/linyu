#!/usr/bin/env python3
"""Capstone-based disassembly helpers for libclient.so (NeoX research).

Strings in this .so are encoded byte-wise: cipher = ROL8(plain, 5) ^ 0xE6,
0x00 encoded as 0xE6. This script resolves ADRP+ADD string references and
annotates disassembly with decoded strings.
"""
from __future__ import annotations

import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from elftools.elf.elffile import ELFFile


def rol8(v: int, n: int) -> int:
    return ((v << n) | (v >> (8 - n))) & 0xFF


def decode_str(raw: bytes) -> str:
    out = bytearray()
    for b in raw:
        if b == 0xE6:
            out.append(0)
            continue
        x = b ^ 0xE6
        out.append(rol8(x, 3))  # ROR8(cipher^0xE6, 5) == ROL8(x, 3)
    return out.decode("utf-8", errors="replace")


class So:
    def __init__(self, path: str):
        self.f = open(path, "rb")
        self.elf = ELFFile(self.f)
        self.segs = []
        for seg in self.elf.iter_segments():
            if seg["p_type"] == "PT_LOAD":
                self.segs.append((seg["p_vaddr"], seg["p_filesz"], seg["p_offset"]))
        self.md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
        self.md.detail = True

    def read(self, vaddr: int, size: int) -> bytes:
        for va, fsz, off in self.segs:
            if va <= vaddr < va + fsz:
                delta = vaddr - va
                self.f.seek(off + delta)
                return self.f.read(size)
        raise ValueError(f"vaddr 0x{vaddr:x} not mapped")

    def cstr(self, vaddr: int, maxlen: int = 200) -> bytes:
        for va, fsz, off in self.segs:
            if va <= vaddr < va + fsz:
                self.f.seek(off + (vaddr - va))
                return self.f.read(maxlen).split(b"\x00")[0]
        return b""

    def decode_at(self, vaddr: int, maxlen: int = 200) -> str:
        try:
            return decode_str(self.cstr(vaddr, maxlen))
        except Exception:
            return "?"

    def disasm(self, vaddr: int, size: int):
        code = self.read(vaddr, size)
        yield from self.md.disasm(code, vaddr)


def adrp_add_strings(insns):
    """Map vaddr -> decoded string for ADRP+ADD/LDR pairs in an insn list."""
    refs = {}
    pending = {}
    for i in insns:
        m = i.op_str
        if i.mnemonic == "adrp":
            try:
                reg, imm = m.split(", ")
                pending[reg] = (i.address, int(imm, 0) if imm.startswith("0x") else int(imm))
            except ValueError:
                pass
        elif i.mnemonic in ("add", "ldr") and "x" in m:
            # add x0, x0, #0x123 / ldr x0, [x0, #0x123]
            parts = [p.strip() for p in m.split(",")]
            if len(parts) >= 3 and parts[0] in pending and parts[1] == parts[0]:
                imm = parts[2]
                if imm.startswith("#"):
                    try:
                        delta = int(imm[1:], 0)
                        base_va = pending[parts[0]][1]
                        refs[i.address] = base_va + delta
                    except ValueError:
                        pass
    return refs


def annotate(so: So, start: int, size: int) -> None:
    insns = list(so.disasm(start, size))
    refs = adrp_add_strings(insns)
    for i in insns:
        line = f"0x{i.address:08x}: {i.mnemonic:10s} {i.op_str}"
        if i.address in refs:
            s = so.decode_at(refs[i.address])
            if s.isprintable() and len(s) >= 3:
                line += f"   ; str@0x{refs[i.address]:x} \"{s}\""
        print(line)


def xrefs_to(so: So, target: int, scan_start: int, scan_end: int) -> list:
    """Find ADRP+ADD pairs whose computed address == target."""
    hits = []
    step = 0x100000
    va = scan_start
    while va < scan_end:
        size = min(step, scan_end - va)
        try:
            insns = list(so.disasm(va, size))
        except Exception:
            va += size
            continue
        refs = adrp_add_strings(insns)
        for addr, ref in refs.items():
            if ref == target:
                hits.append(addr)
        va += size
    return hits


if __name__ == "__main__":
    so_path = sys.argv[1] if len(sys.argv) > 1 else "so_bundle/libclient.so"
    so = So(so_path)
    if len(sys.argv) >= 4 and sys.argv[2] == "disasm":
        annotate(so, int(sys.argv[3], 0), int(sys.argv[4], 0))
    elif len(sys.argv) >= 5 and sys.argv[2] == "xref":
        for h in xrefs_to(so, int(sys.argv[3], 0), int(sys.argv[4], 0), int(sys.argv[5], 0)):
            print(f"0x{h:08x}")
    elif len(sys.argv) >= 3 and sys.argv[2] == "str":
        print(so.decode_at(int(sys.argv[3], 0)))
