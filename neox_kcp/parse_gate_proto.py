#!/usr/bin/env python3
"""Parse the embedded (deobfuscated) client_gate.proto FileDescriptorProto
from libclient.so and print the message/service definition order."""
import sys

from so_disasm import So


def rol8(v, n):
    return ((v << n) | (v >> (8 - n))) & 0xFF


def deobfuscate(bs):
    out = bytearray()
    for b in bs:
        if b == 0xE6:
            out.append(0)
            continue
        out.append(rol8(b ^ 0xE6, 3))
    return bytes(out)


def rdvarint(b, i):
    v = s = 0
    while True:
        v |= (b[i] & 0x7F) << s
        i += 1
        if not b[i - 1] & 0x80:
            return v, i
        s += 7


def fields(b):
    i = 0
    while i < len(b):
        k, i = rdvarint(b, i)
        fn, wt = k >> 3, k & 7
        if wt == 0:
            v, i = rdvarint(b, i)
        elif wt == 2:
            l, i = rdvarint(b, i)
            v = b[i:i + l]
            i += l
        elif wt == 5:
            v = b[i:i + 4]
            i += 4
        elif wt == 1:
            v = b[i:i + 8]
            i += 8
        else:
            raise ValueError(f"wire type {wt}")
        yield fn, v


TYPES = {1: 'double', 2: 'float', 3: 'int64', 4: 'uint64', 5: 'int32',
         6: 'fixed64', 7: 'fixed32', 8: 'bool', 9: 'string', 10: 'group',
         11: 'message', 12: 'bytes', 13: 'uint32', 14: 'enum',
         15: 'sfixed32', 16: 'sfixed64', 17: 'sint32', 18: 'sint64'}
LABELS = {1: 'optional', 2: 'required', 3: 'repeated'}


def dump(data):
    msgs, svcs, fname, pkg = [], [], '', ''
    deps = []
    for fn, v in fields(data):
        if fn == 1:
            fname = v.decode()
        elif fn == 2:
            pkg = v.decode()
        elif fn == 3:
            deps.append(v.decode())
        elif fn == 4:
            msgs.append(v)
        elif fn == 6:
            svcs.append(v)
    print(f'file: {fname}  package: {pkg}  deps: {deps}')
    print('\n=== message_type order (registry index) ===')
    for idx, m in enumerate(msgs):
        name, fs, enum_vals = None, [], {}
        for fn, v in fields(m):
            if fn == 1:
                name = v.decode()
            elif fn == 2:
                fs.append(v)
            elif fn == 4:  # enum_type
                ename, vals = None, []
                for efn, ev in fields(v):
                    if efn == 1:
                        ename = ev.decode()
                    elif efn == 2:
                        vals.append(ev)
                enum_vals[ename] = vals
        fl = []
        for fb in fs:
            f_name = f_type = f_tname = None
            f_num = f_label = None
            for fn, v in fields(fb):
                if fn == 1:
                    f_name = v.decode()
                elif fn == 3:
                    f_num = v
                elif fn == 4:
                    f_label = LABELS.get(v, v)
                elif fn == 5:
                    f_type = TYPES.get(v, str(v))
                elif fn == 6:
                    f_tname = v.decode().lstrip('.')
            t = f_tname or f_type
            fl.append(f'{f_name}({f_num}){" repeated" if f_label == "repeated" else ""}: {t}')
        enums = ''
        for ename, vals in enum_vals.items():
            pairs = []
            for vb in vals:
                vn, vv = None, None
                for fn, v in fields(vb):
                    if fn == 1:
                        vn = v.decode()
                    elif fn == 2:
                        vv = v
                pairs.append(f'{vn}={vv}')
            enums += f'  enum {ename}: {", ".join(pairs)}\n'
        print(f'[{idx:3d}] {name}\n     {"; ".join(fl)}')
        if enums:
            print(enums, end='')
    for svc in svcs:
        sname, methods = None, []
        for fn, v in fields(svc):
            if fn == 1:
                sname = v.decode()
            elif fn == 2:
                methods.append(v)
        print(f'\n=== service {sname} ===')
        for m in methods:
            mname = inp = outp = None
            for fn, v in fields(m):
                if fn == 1:
                    mname = v.decode()
                elif fn == 2:
                    inp = v.decode()
                elif fn == 3:
                    outp = v.decode()
            print(f'  rpc {mname}({inp}) -> ({outp})')


if __name__ == '__main__':
    so = So(sys.argv[1] if len(sys.argv) > 1 else 'so_bundle/libclient.so')
    blob = so.read(0x31AAFE9, 0x804)
    dump(deobfuscate(blob))
