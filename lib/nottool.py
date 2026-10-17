#!/usr/bin/env python3

import struct
import sys

MAGIC = b"NOT\x10"

PROPS = {}


def load_prop_table(dol_path):
    d = open(dol_path, "rb").read()
    offs = struct.unpack_from(">18I", d, 0)
    addrs = struct.unpack_from(">18I", d, 0x48)
    sizes = struct.unpack_from(">18I", d, 0x90)
    for a, o, s in zip(addrs, offs, sizes):
        if s and a <= 0x8048E748 < a + s:
            p = o + 0x8048E748 - a
            for i in range(120):
                name = d[p:p + 0x20].split(b"\0")[0].decode()
                kind, typ = struct.unpack_from(">ii", d, p + 0x20)
                PROPS[i] = (name, typ)
                p += 0x28
            return
    raise SystemExit("property table not found in " + dol_path)


class Template:
    def __init__(self, raw_name, props, note):
        self.raw_name = raw_name
        self.props = props
        self.note = note

    @property
    def name(self):
        return self.raw_name.split(b"\0")[0].decode("latin-1")

    def get(self, pid):
        for i, v in self.props:
            if i == pid:
                return v
        return None

    def set(self, pid, value):
        for k, (i, _) in enumerate(self.props):
            if i == pid:
                self.props[k] = (pid, value)
                return
        self.props.append((pid, value))


def name32(s):
    b = s.encode("latin-1")
    if len(b) > 0x1F:
        raise ValueError("name longer than 31 characters: " + s)
    return b + b"\0" * (0x20 - len(b))


def v_str(s):
    return name32(s)


def v_int(n):
    return struct.pack("<I", n & 0xFFFFFFFF) + b"\0" * 0x1C


def v_float(f):
    return struct.pack("<f", f) + b"\0" * 0x1C


def parse(data):
    if data[:4] != MAGIC:
        raise ValueError("bad magic %r" % data[:4])
    version, count = struct.unpack_from("<II", data, 4)
    if version != 1:
        raise ValueError("version %d" % version)
    index = []
    p = 12
    for _ in range(count):
        index.append((data[p:p + 0x20], struct.unpack_from("<I", data, p + 0x20)[0]))
        p += 0x24
    out = []
    for raw, off in index:
        if off != p:
            raise ValueError("body of %r at 0x%X, expected 0x%X" % (raw, off, p))
        n = struct.unpack_from("<I", data, p)[0]
        p += 4
        props = []
        for _ in range(n):
            props.append((struct.unpack_from("<I", data, p)[0], data[p + 4:p + 0x24]))
            p += 0x24
        tn = struct.unpack_from("<I", data, p)[0]
        note = data[p + 4:p + 4 + tn]
        p += 4 + tn
        out.append(Template(raw, props, note))
    if p != len(data):
        raise ValueError("trailing data: 0x%X of 0x%X" % (p, len(data)))
    return out


def build(templates):
    head = bytearray(MAGIC + struct.pack("<II", 1, len(templates)))
    bodies = bytearray()
    base = 12 + 0x24 * len(templates)
    for t in templates:
        head += t.raw_name + struct.pack("<I", base + len(bodies))
        bodies += struct.pack("<I", len(t.props))
        for pid, v in t.props:
            assert len(v) == 0x20
            bodies += struct.pack("<I", pid) + v
        bodies += struct.pack("<I", len(t.note)) + t.note
    return bytes(head + bodies)


def fmt_value(pid, v):
    typ = PROPS.get(pid, ("", None))[1]
    if typ == 0:
        return repr(v.split(b"\0")[0].decode("latin-1"))
    if typ == 2:
        return "%g" % struct.unpack_from("<f", v)[0]
    if typ == 3:
        n = struct.unpack_from("<I", v)[0]
        return "%d (0x%X)" % (n, n)
    if typ == 4:
        return "(%g, %g, %g)" % struct.unpack_from("<3f", v)
    return v.rstrip(b"\0").hex() or "0"


def dump(templates, names):
    want = {n.lower() for n in names}
    for i, t in enumerate(templates):
        if want and t.name.lower() not in want:
            continue
        print("[%d] %s  (%d properties)%s" % (i, t.name, len(t.props),
                                               "" if t.note == b"\0" else "  note=%r" % t.note))
        for pid, v in t.props:
            print("    0x%02X %-18s %s" % (pid, PROPS.get(pid, ("?",))[0], fmt_value(pid, v)))


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    dol = os.environ.get("MNROI_DOL", os.path.join(here, "..", "project", "orig", "GVLE69", "sys", "main.dol"))
    if os.path.exists(dol):
        load_prop_table(dol)
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    data = open(sys.argv[2], "rb").read()
    ts = parse(data)
    if sys.argv[1] == "dump":
        dump(ts, sys.argv[3:])
    elif sys.argv[1] == "check":
        print("%d templates, round trip %s" % (len(ts), "identical" if build(ts) == data else "DIFFERS"))
    else:
        raise SystemExit(__doc__)
