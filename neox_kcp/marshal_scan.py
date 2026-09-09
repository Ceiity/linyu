#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

from xdis.unmarshal import load_code


MAGIC_27 = 62211


def children(code):
    for item in code.co_consts:
        if hasattr(item, "co_code"):
            yield item


def constants(code):
    return [item for item in code.co_consts if not hasattr(item, "co_code") and item is not None]


def walk(code, prefix=""):
    name = code.co_name
    qualname = f"{prefix}.{name}" if prefix else name
    yield qualname, code
    for child in children(code):
        yield from walk(child, qualname)


def render(path, qualname, code):
    print(f"FILE {path}")
    print(f"  FUNC {qualname}")
    print(f"  ARGS {code.co_varnames[:code.co_argcount]}")
    print(f"  VARS {code.co_varnames}")
    print(f"  NAMES {code.co_names}")
    print(f"  CONST {constants(code)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("pattern")
    ap.add_argument("--path", default="")
    args = ap.parse_args()
    rx = re.compile(args.pattern, re.I)
    path_rx = re.compile(args.path, re.I) if args.path else None
    root = Path(args.root)
    count = 0
    for path in sorted(root.rglob("*.nxs")):
        rel = str(path.relative_to(root))
        if path_rx and not path_rx.search(rel):
            continue
        try:
            code = load_code(path.read_bytes(), MAGIC_27, bytes_for_s=False)
        except Exception as exc:
            print(f"ERROR {rel}: {exc}")
            continue
        for qualname, child in walk(code):
            haystack = "\n".join([
                rel,
                qualname,
                *map(str, child.co_varnames),
                *map(str, child.co_names),
                *map(str, constants(child)),
            ])
            if rx.search(haystack):
                render(rel, qualname, child)
                count += 1
    print(f"MATCHED {count}")


if __name__ == "__main__":
    main()
