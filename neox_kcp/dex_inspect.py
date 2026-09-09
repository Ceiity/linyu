#!/usr/bin/env python3
import argparse
import struct
from pathlib import Path


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def uleb(data, off):
    value = 0
    shift = 0
    while True:
        byte = data[off]
        off += 1
        value |= (byte & 0x7f) << shift
        if not byte & 0x80:
            return value, off
        shift += 7


WIDTHS = [1] * 256
for op, width in {
    0x02: 2, 0x03: 3, 0x05: 2, 0x06: 3, 0x08: 2, 0x09: 3,
    0x13: 2, 0x14: 3, 0x15: 2, 0x16: 2, 0x17: 3, 0x18: 5,
    0x19: 2, 0x1a: 2, 0x1b: 3, 0x1c: 2, 0x1f: 2, 0x20: 2,
    0x22: 2, 0x23: 2, 0x24: 3, 0x25: 3, 0x26: 3, 0x29: 2,
    0x2a: 3, 0x2b: 3, 0x2c: 3,
    **{op: 2 for op in range(0x2d, 0x3e)},
    **{op: 2 for op in range(0x44, 0x6e)},
    **{op: 3 for op in range(0x6e, 0x73)},
    **{op: 3 for op in range(0x74, 0x79)},
    **{op: 2 for op in range(0x90, 0xb0)},
    **{op: 2 for op in range(0xd0, 0xe3)},
}.items():
    WIDTHS[op] = width


class Dex:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if not self.data.startswith(b"dex\n"):
            raise ValueError(f"not a dex file: {path}")
        self.strings = self._strings()
        self.types = self._types()
        self.protos = self._protos()
        self.fields = self._fields()
        self.method_ids = self._method_ids()
        self.class_defs = self._class_defs()
        self.methods = self._class_methods()
        self.code_by_method = {m["method_idx"]: m["code_off"] for m in self.methods}

    def _strings(self):
        size, off = u32(self.data, 0x38), u32(self.data, 0x3c)
        result = []
        for i in range(size):
            pos = u32(self.data, off + i * 4)
            _, pos = uleb(self.data, pos)
            end = self.data.find(b"\0", pos)
            result.append(self.data[pos:end].decode("utf-8", "replace"))
        return result

    def _types(self):
        size, off = u32(self.data, 0x40), u32(self.data, 0x44)
        return [self.strings[u32(self.data, off + i * 4)] for i in range(size)]

    def _type_list(self, off):
        if not off:
            return []
        size = u32(self.data, off)
        return [self.types[u16(self.data, off + 4 + i * 2)] for i in range(size)]

    def _protos(self):
        size, off = u32(self.data, 0x48), u32(self.data, 0x4c)
        result = []
        for i in range(size):
            shorty, ret, params = struct.unpack_from("<III", self.data, off + i * 12)
            result.append((self.types[ret], self._type_list(params)))
        return result

    def _fields(self):
        size, off = u32(self.data, 0x50), u32(self.data, 0x54)
        result = []
        for i in range(size):
            cls, typ, name = struct.unpack_from("<HHI", self.data, off + i * 8)
            result.append(f"{self.types[cls]}->{self.strings[name]}:{self.types[typ]}")
        return result

    def _method_ids(self):
        size, off = u32(self.data, 0x58), u32(self.data, 0x5c)
        result = []
        for i in range(size):
            cls, proto, name = struct.unpack_from("<HHI", self.data, off + i * 8)
            ret, params = self.protos[proto]
            result.append({
                "class": self.types[cls], "name": self.strings[name],
                "params": params, "ret": ret,
            })
        return result

    def _class_defs(self):
        size, off = u32(self.data, 0x60), u32(self.data, 0x64)
        result = []
        for i in range(size):
            values = struct.unpack_from("<IIIIIIII", self.data, off + i * 32)
            result.append({
                "class_idx": values[0], "annotations_off": values[5],
                "class_data_off": values[6], "static_values_off": values[7],
            })
        return result

    def method_name(self, idx):
        m = self.method_ids[idx]
        return f'{m["class"]}->{m["name"]}({"".join(m["params"])}){m["ret"]}'

    def _encoded_methods(self, pos, count, cls):
        methods = []
        idx = 0
        for _ in range(count):
            diff, pos = uleb(self.data, pos)
            access, pos = uleb(self.data, pos)
            code_off, pos = uleb(self.data, pos)
            idx += diff
            methods.append({"method_idx": idx, "access": access, "code_off": code_off, "class": cls})
        return methods, pos

    def _class_methods(self):
        result = []
        for class_def in self.class_defs:
            cls_idx = class_def["class_idx"]
            class_data_off = class_def["class_data_off"]
            if not class_data_off:
                continue
            pos = class_data_off
            static_n, pos = uleb(self.data, pos)
            instance_n, pos = uleb(self.data, pos)
            direct_n, pos = uleb(self.data, pos)
            virtual_n, pos = uleb(self.data, pos)
            for count in (static_n, instance_n):
                for _ in range(count):
                    _, pos = uleb(self.data, pos)
                    _, pos = uleb(self.data, pos)
            direct, pos = self._encoded_methods(pos, direct_n, self.types[cls_idx])
            virtual, pos = self._encoded_methods(pos, virtual_n, self.types[cls_idx])
            result.extend(direct)
            result.extend(virtual)
        return result

    def _encoded_value(self, pos):
        header = self.data[pos]
        pos += 1
        value_type, value_arg = header & 0x1f, header >> 5
        if value_type == 0x1e:
            return None, pos
        if value_type == 0x1f:
            return bool(value_arg), pos
        if value_type == 0x1c:
            size, pos = uleb(self.data, pos)
            values = []
            for _ in range(size):
                value, pos = self._encoded_value(pos)
                values.append(value)
            return values, pos
        if value_type == 0x1d:
            value, pos = self._encoded_annotation(pos)
            return value, pos
        raw = 0
        for i in range(value_arg + 1):
            raw |= self.data[pos + i] << (i * 8)
        pos += value_arg + 1
        if value_type == 0x17 and raw < len(self.strings):
            return self.strings[raw], pos
        if value_type == 0x18 and raw < len(self.types):
            return self.types[raw], pos
        if value_type == 0x19 and raw < len(self.fields):
            return self.fields[raw], pos
        if value_type == 0x1a and raw < len(self.method_ids):
            return self.method_name(raw), pos
        if value_type == 0x1b and raw < len(self.fields):
            return self.fields[raw], pos
        return raw, pos

    def _encoded_annotation(self, pos):
        type_idx, pos = uleb(self.data, pos)
        size, pos = uleb(self.data, pos)
        values = {}
        for _ in range(size):
            name_idx, pos = uleb(self.data, pos)
            value, pos = self._encoded_value(pos)
            values[self.strings[name_idx]] = value
        return {"type": self.types[type_idx], "values": values}, pos

    def _annotation_set(self, off):
        if not off:
            return []
        size = u32(self.data, off)
        result = []
        for i in range(size):
            annotation_off = u32(self.data, off + 4 + i * 4)
            value, _ = self._encoded_annotation(annotation_off + 1)
            result.append(value)
        return result

    def annotations(self):
        class_result = {}
        method_result = {}
        for class_def in self.class_defs:
            off = class_def["annotations_off"]
            if not off:
                continue
            class_off, fields_n, methods_n, params_n = struct.unpack_from("<IIII", self.data, off)
            cls = self.types[class_def["class_idx"]]
            class_result[cls] = self._annotation_set(class_off)
            pos = off + 16 + fields_n * 8
            for _ in range(methods_n):
                method_idx, annotations_off = struct.unpack_from("<II", self.data, pos)
                pos += 8
                method_result[method_idx] = self._annotation_set(annotations_off)
        return class_result, method_result

    def class_fields(self, class_desc):
        return [f for f in self.fields if f.startswith(class_desc + "->")]

    def refs(self, method_idx):
        code_off = self.code_by_method.get(method_idx, 0)
        if not code_off:
            return {"strings": [], "methods": [], "fields": [], "types": []}
        insns_size = u32(self.data, code_off + 12)
        units = struct.unpack_from(f"<{insns_size}H", self.data, code_off + 16)
        refs = {"strings": [], "methods": [], "fields": [], "types": []}
        i = 0
        while i < len(units):
            first = units[i]
            op = first & 0xff
            if op == 0 and first >> 8 in (1, 2, 3):
                ident = first >> 8
                if ident == 1 and i + 1 < len(units):
                    width = 4 + units[i + 1] * 2
                elif ident == 2 and i + 1 < len(units):
                    width = 2 + units[i + 1] * 4
                elif ident == 3 and i + 3 < len(units):
                    width = 4 + ((units[i + 1] * units[i + 2] * units[i + 3] + 1) // 2)
                else:
                    width = 1
                i += width
                continue
            width = WIDTHS[op]
            if i + width > len(units):
                break
            if op == 0x1a:
                idx = units[i + 1]
                if idx < len(self.strings):
                    refs["strings"].append(self.strings[idx])
            elif op == 0x1b:
                idx = units[i + 1] | units[i + 2] << 16
                if idx < len(self.strings):
                    refs["strings"].append(self.strings[idx])
            elif op in (0x1c, 0x1f, 0x20, 0x22, 0x23, 0x24, 0x25):
                idx = units[i + 1]
                if idx < len(self.types):
                    refs["types"].append(self.types[idx])
            elif 0x52 <= op <= 0x6d:
                idx = units[i + 1]
                if idx < len(self.fields):
                    refs["fields"].append(self.fields[idx])
            elif 0x6e <= op <= 0x72 or 0x74 <= op <= 0x78:
                idx = units[i + 1]
                if idx < len(self.method_ids):
                    refs["methods"].append(idx)
            i += width
        for key in refs:
            refs[key] = list(dict.fromkeys(refs[key]))
        return refs

    def matching_methods(self, needle):
        needle = needle.lower()
        return [i for i in self.code_by_method if needle in self.method_name(i).lower()]

    def callers(self, target_idxs):
        targets = set(target_idxs)
        result = []
        for idx in self.code_by_method:
            refs = self.refs(idx)
            hits = targets.intersection(refs["methods"])
            if hits:
                result.append((idx, sorted(hits)))
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dex", nargs="+")
    parser.add_argument("--query", required=True)
    parser.add_argument("--callers", action="store_true")
    parser.add_argument("--fields", action="store_true")
    parser.add_argument("--annotations", action="store_true")
    args = parser.parse_args()
    for path in args.dex:
        dex = Dex(path)
        matches = dex.matching_methods(args.query)
        class_matches = sorted({t for t in dex.types if args.query.lower() in t.lower()})
        if not matches and not class_matches:
            continue
        print(f"\n=== {path} ===")
        class_annotations, method_annotations = dex.annotations() if args.annotations else ({}, {})
        for cls in class_matches:
            print(f"CLASS {cls}")
            if args.fields:
                for field in dex.class_fields(cls):
                    print(f"  FIELD {field}")
            for annotation in class_annotations.get(cls, []):
                print(f"  ANNOTATION {annotation}")
        for idx in matches:
            print(f"METHOD [{idx}] {dex.method_name(idx)}")
            for annotation in method_annotations.get(idx, []):
                print(f"  ANNOTATION {annotation}")
            refs = dex.refs(idx)
            for value in refs["strings"]:
                print(f"  STRING {value!r}")
            for value in refs["types"]:
                print(f"  TYPE   {value}")
            for value in refs["fields"]:
                print(f"  FIELD  {value}")
            for value in refs["methods"]:
                print(f"  CALL   [{value}] {dex.method_name(value)}")
        if args.callers and matches:
            print("CALLERS")
            for idx, hits in dex.callers(matches):
                print(f"  [{idx}] {dex.method_name(idx)}")
                for hit in hits:
                    print(f"    -> [{hit}] {dex.method_name(hit)}")


if __name__ == "__main__":
    main()
