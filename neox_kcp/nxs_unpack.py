#!/usr/bin/env python3
import argparse
import json
import struct
import zlib
from pathlib import Path


def random_func(key: bytes):
    mask = 0xFFFF
    x, y, z = 995, 576, 767
    for c in key:
        x = (((x << 3 | x >> 13) + c) & mask)
        y = (((y << 3 | y >> 13) ^ c) & mask)
        z = (((z << 3 | z >> 13) - c) & mask)
    maxpos = mask >> 1
    mask += 1
    if x > maxpos:
        x -= mask
    if y > maxpos:
        y -= mask
    if z > maxpos:
        z -= mask
    y |= 1
    x = 171 * (x % 177) - 2 * (x // 177)
    y = 172 * (y % 176) - 35 * (y // 176)
    z = 170 * (z % 178) - 63 * (z // 178)
    if x < 0:
        x += 30269
    if y < 0:
        y += 30307
    if z < 0:
        z += 30323

    def rand(n):
        nonlocal x, y, z
        old = x, y, z
        x, y, z = (171 * x) % 30269, (172 * y) % 30307, (170 * z) % 30323
        ox, oy, oz = old
        return int((ox / 30269.0 + oy / 30307.0 + oz / 30323.0) * n) % n

    return rand


class Rotor:
    def __init__(self, key: bytes, n_rotors=6):
        self.key = key
        self.n_rotors = n_rotors
        self.rotors = None
        self.positions = [None, None]

    def get_rotors(self, do_decrypt):
        nr = self.n_rotors
        positions = self.positions[do_decrypt]
        if positions is None:
            if self.rotors:
                positions = list(self.rotors[3])
            else:
                size = 256
                id_rotor = list(range(size + 1))
                rand = random_func(self.key)
                enc, dec, positions = [], [], []
                for _ in range(nr):
                    i = size
                    positions.append(rand(i))
                    erotor = id_rotor[:]
                    drotor = id_rotor[:]
                    drotor[i] = erotor[i] = 1 + 2 * rand(i // 2)
                    while i > 1:
                        r = rand(i)
                        i -= 1
                        er = erotor[r]
                        erotor[r] = erotor[i]
                        erotor[i] = er
                        drotor[er] = i
                    drotor[erotor[0]] = 0
                    enc.append(tuple(erotor))
                    dec.append(tuple(drotor))
                self.rotors = tuple(enc), tuple(dec), size, tuple(positions)
            self.positions[do_decrypt] = positions
        return self.rotors[2], nr, self.rotors[do_decrypt], positions

    def decrypt(self, buf: bytes):
        self.positions[1] = None
        size, nr, rotors, pos = self.get_rotors(1)
        out = bytearray()
        for c in buf:
            for i in range(nr - 1, -1, -1):
                c = pos[i] ^ rotors[i][c]
            out.append(c)
            pnew = 0
            for i in range(nr):
                pnew = ((pos[i] + (pnew >= size)) & 0xFF) + rotors[i][size]
                pos[i] = pnew % size
        return bytes(out)


def game_key():
    dn = "K7mP2xN9qR4vT"
    dt = "@z6Qp!."
    df = "|R8s=V3!#-7a2"
    return (dn * 4 + (dt + dn + df) * 5 + "!" + "#" + dt * 7 + df * 2 + "*" + "&" + "'").encode()


def decrypt_nxs(data: bytes):
    stage = Rotor(game_key()).decrypt(data)
    stage = zlib.decompress(stage)
    head = bytes(b ^ 154 for b in stage[:128])
    return (head + stage[128:])[::-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("npk")
    ap.add_argument("filelist")
    ap.add_argument("outdir")
    ap.add_argument("patterns", nargs="*")
    args = ap.parse_args()

    npk = Path(args.npk).read_bytes()
    entries = json.loads(Path(args.filelist).read_text())
    patterns = [p.lower() for p in args.patterns]
    outdir = Path(args.outdir)
    selected = [e for e in entries if not patterns or any(p in e["file_name"].lower() for p in patterns)]
    ok = 0
    for entry in selected:
        name = entry["file_name"]
        raw = npk[entry["pos"]:entry["pos"] + entry["compress_size"]]
        try:
            data = raw if name == "redirect.nxs" else decrypt_nxs(raw)
        except Exception as exc:
            print(f"FAIL\t{name}\t{exc}")
            continue
        target = outdir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"OK\t{name}\t{len(raw)}\t{len(data)}\t{data[:8].hex()}")
        ok += 1
    print(f"SUMMARY\tselected={len(selected)}\tok={ok}")


if __name__ == "__main__":
    main()
