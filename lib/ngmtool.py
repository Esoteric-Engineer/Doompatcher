#!/usr/bin/env python3

import struct
import sys

ELEM = [12, 16, 28, 12, 16, 28]


class R:
    def __init__(self, d, o=0):
        self.d, self.o = d, o

    def take(self, n):
        b = self.d[self.o:self.o + n]
        if len(b) != n:
            raise EOFError("read past end at 0x%X" % self.o)
        self.o += n
        return b

    def u8(self): return self.take(1)[0]
    def u16(self): return struct.unpack(">H", self.take(2))[0]
    def u32(self): return struct.unpack(">I", self.take(4))[0]
    def s32(self): return struct.unpack(">i", self.take(4))[0]
    def f(self, n): return struct.unpack(">%df" % n, self.take(4 * n))
    def name(self, n=0x20): return self.take(n).split(b"\0")[0].decode("latin-1")


def parse_model(r):
    m = {"off": r.o}
    m["index"] = r.s32()
    m["nmat"], m["nbone"], m["npart"] = r.u8(), r.u8(), r.u8()
    m["nmtx"] = r.u16()
    m["name"] = r.name()
    m["nstream"] = r.u8()
    m["flags"] = r.u32()
    m["bbox"] = r.f(8)
    m["streams"] = []
    for _ in range(m["nstream"]):
        s = {"type": r.u8()}
        s["nmap"] = r.u32()
        s["map"] = r.take(6 * s["nmap"])
        s["n"] = r.u16()
        s["data_off"] = r.o
        s["data"] = r.take(s["n"] * ELEM[s["type"]])
        if s["type"] > 2:
            s["map2"] = r.take(6 * s["nmap"])
        m["streams"].append(s)
    n = r.u16()
    m["tab32"] = struct.unpack(">%dI" % n, r.take(4 * n))
    k = r.u32()
    m["idx_off"] = r.o
    m["idx"] = struct.unpack(">%dH" % k, r.take(2 * k))
    m["materials"] = [r.name() for _ in range(m["nmat"])]
    m["bones"] = []
    for _ in range(m["nbone"]):
        b = {"q": r.f(4), "t": r.f(4), "parent": r.u8(), "b21": r.u8()}
        m["bones"].append(b)
    m["u158"], m["u15a"] = r.u16(), r.u16()
    m["parts"] = []
    for _ in range(m["npart"]):
        p = {"mat": r.u32(), "stream": r.u8(), "n14": r.u16(), "n16": r.u16(), "n18": r.u16(),
             "b3e": r.u8(), "b3f": r.u8(), "b40": r.u8()}
        nb = r.u8()
        p["bones"] = list(r.take(nb))
        m["parts"].append(p)
    m["mtx"] = []
    for _ in range(m["nmtx"]):
        a, b, c = r.u8(), r.u8(), r.u16()
        m["mtx"].append({"b40": a, "b41": b, "h42": c, "m": r.f(16)})
    m["end"] = r.o
    return m


def parse(d):
    r = R(d)
    hdr = {"version": r.u32(), "u1": r.u32(), "u2": r.u32(), "count": r.u32(), "n30": r.u32(), "pool": r.u32()}
    if hdr["version"] != 5:
        raise SystemExit("not a version-5 .ngm")
    models = [parse_model(r) for _ in range(hdr["count"])]
    return hdr, models, r.o


def write_model(m):
    o = bytearray()
    o += struct.pack(">iBBBH", m["index"], m["nmat"], m["nbone"], m["npart"], m["nmtx"])
    o += m["name"].encode("latin-1").ljust(0x20, b"\0")
    o += struct.pack(">BI", len(m["streams"]), m["flags"])
    o += struct.pack(">8f", *m["bbox"])
    for s in m["streams"]:
        o += struct.pack(">BI", s["type"], s["nmap"]) + s["map"]
        o += struct.pack(">H", s["n"]) + s["data"]
        if s["type"] > 2:
            o += s["map2"]
    o += struct.pack(">H%dI" % len(m["tab32"]), len(m["tab32"]), *m["tab32"])
    o += struct.pack(">I%dH" % len(m["idx"]), len(m["idx"]), *m["idx"])
    for name in m["materials"]:
        o += name.encode("latin-1").ljust(0x20, b"\0")
    for b in m["bones"]:
        o += struct.pack(">4f4fBB", *b["q"], *b["t"], b["parent"], b["b21"])
    o += struct.pack(">HH", m["u158"], m["u15a"])
    for p in m["parts"]:
        o += struct.pack(">IBHHHBBBB", p["mat"], p["stream"], p["n14"], p["n16"], p["n18"],
                         p["b3e"], p["b3f"], p["b40"], len(p["bones"])) + bytes(p["bones"])
    for x in m["mtx"]:
        o += struct.pack(">BBH16f", x["b40"], x["b41"], x["h42"], *x["m"])
    return bytes(o)


def pool_size(models):
    p = 0
    a16 = lambda x: (x + 15) & ~15
    for m in models:
        p = a16(p) + 0x190
        p = a16(p) + m["nmtx"] * 0x50
        p = a16(p) + m["nbone"] * 0x30 + m["npart"] * 0x5C + m["nmat"] * 4
    return p


def write(hdr, models):
    o = struct.pack(">6I", hdr["version"], hdr["u1"], hdr["u2"], len(models), hdr["n30"], hdr["pool"])
    return o + b"".join(write_model(m) for m in models)


def load_normals(ngn):
    n = struct.unpack(">H", ngn[:2])[0]
    return [struct.unpack(">3f", ngn[2 + 12 * i:14 + 12 * i]) for i in range(n)]


def strip_tris(idx):
    out = []
    for i in range(len(idx) - 2):
        a, b, c = idx[i], idx[i + 1], idx[i + 2]
        if a == b or b == c or a == c:
            continue
        out.append((a, b, c) if i % 2 == 0 else (b, a, c))
    return out


def part_tris(m):
    off = 0
    for i, p in enumerate(m["parts"]):
        strip = m["idx"][off:off + p["n14"]]
        lst = m["idx"][off + p["n14"]:off + p["n14"] + p["n16"]]
        tris = strip_tris(strip) + [tuple(lst[k:k + 3]) for k in range(0, len(lst), 3)]
        off += p["n14"] + p["n16"]
        yield i, p, m["streams"][p["stream"]], tris


def vertex(m, s, k, normals):
    pi, ni, ti = struct.unpack(">3H", s["map"][6 * k:6 * k + 6])
    e = ELEM[s["type"]]
    rec = s["data"][pi * e:(pi + 1) * e]
    pos = struct.unpack(">3f", rec[:12])
    if s["type"] % 3 == 2:
        w = struct.unpack(">3f", rec[12:24])
        skin = [(rec[24 + j], w[j]) for j in range(3) if w[j] > 0]
    else:
        skin = None
    u, v = struct.unpack(">2h", struct.pack(">I", m["tab32"][ti]))
    return pos, normals[ni], (u / 512.0, v / 512.0), skin


def dump(path):
    d = open(path, "rb").read()
    hdr, models, end = parse(d)
    print(path, hdr, "parsed to 0x%X of 0x%X" % (end, len(d)))
    for m in models:
        print("model %r @0x%X..0x%X index=%d mats=%d bones=%d parts=%d mtx=%d flags=0x%X" % (
            m["name"], m["off"], m["end"], m["index"], m["nmat"], m["nbone"], m["npart"], m["nmtx"], m["flags"]))
        print("  bbox", ["%.3f" % v for v in m["bbox"]])
        for i, s in enumerate(m["streams"]):
            print("  stream %d type %d nmap %d n %d (%d bytes)" % (i, s["type"], s["nmap"], s["n"], len(s["data"])))
        print("  tab32 %d, idx %d, u158 %d u15a %d" % (len(m["tab32"]), len(m["idx"]), m["u158"], m["u15a"]))
        print("  materials", m["materials"])
        for i, p in enumerate(m["parts"]):
            print("  part %d" % i, p)
        for i, b in enumerate(m["bones"][:6]):
            print("  bone %d" % i, ["%.3f" % v for v in b["q"]], ["%.3f" % v for v in b["t"]], b["parent"], b["b21"])


if __name__ == "__main__":
    if sys.argv[1] == "dump":
        for p in sys.argv[2:]:
            dump(p)
