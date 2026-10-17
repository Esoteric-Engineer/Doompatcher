#!/usr/bin/env python3

import struct
import sys

from PIL import Image


def entries(d):
    n = struct.unpack_from(">I", d, 8)[0]
    p, out = 16, []
    for _ in range(n):
        off, size = struct.unpack_from(">II", d, p)
        e = d.index(b"\0", p + 8)
        out.append((d[p + 8:e].decode("latin-1"), off, size))
        p = e + 1
    return out


def rgb5a3(c):
    if c & 0x8000:
        r, g, b = (c >> 10) & 31, (c >> 5) & 31, c & 31
        return ((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2), 255)
    a, r, g, b = (c >> 12) & 7, (c >> 8) & 15, (c >> 4) & 15, c & 15
    return (r * 17, g * 17, b * 17, (a << 5) | (a << 2) | (a >> 1))


def image_info(d, off):
    code, rsize, doff, dsize = struct.unpack_from(">IIII", d, off)
    w, h = struct.unpack_from(">II", d, off + 0x18)
    return {"code": code, "rsize": rsize, "doff": doff, "dsize": dsize, "w": w, "h": h,
            "pal": off + rsize}


def decode(d, off):
    i = image_info(d, off)
    if i["code"] >> 24 != 0x19:
        raise SystemExit("format 0x%02X not handled" % (i["code"] >> 24))
    w, h = i["w"], i["h"]
    pal = [rgb5a3(c) for c in struct.unpack_from(">256H", d, i["pal"] + 0x20)]
    im = Image.new("RGBA", (w, h))
    px = im.load()
    data = d[off + i["doff"]:off + i["doff"] + i["dsize"]]
    p = 0
    for ty in range(0, h, 4):
        for tx in range(0, w, 8):
            for y in range(4):
                for x in range(8):
                    if tx + x < w and ty + y < h:
                        px[tx + x, ty + y] = pal[data[p]]
                    p += 1
    return im


def to_rgb5a3(r, g, b, a):
    if a >= 224:
        return 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
    return ((a >> 5) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)


def encode(im):
    im = im.convert("RGBA")
    w, h = im.size
    alpha = im.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    q = im.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    qp = q.getpalette()[:255 * 3]
    pal = [0] + [to_rgb5a3(qp[3 * i], qp[3 * i + 1], qp[3 * i + 2], 255) for i in range(len(qp) // 3)]
    pal += [0] * (256 - len(pal))
    qpx, apx = q.load(), alpha.load()
    out = bytearray()
    for ty in range(0, h, 4):
        for tx in range(0, w, 8):
            for y in range(4):
                for x in range(8):
                    X, Y = tx + x, ty + y
                    out.append(0 if X >= w or Y >= h or apx[X, Y] == 0 else qpx[X, Y] + 1)
    return bytes(out), pal


def replace(d, name, im):
    d = bytearray(d)
    for n, off, _ in entries(d):
        if n == name:
            i = image_info(d, off)
            if im.size != (i["w"], i["h"]):
                raise SystemExit("image %s is %dx%d, not %dx%d" % (name, i["w"], i["h"], *im.size))
            px, pal = encode(im)
            assert len(px) == i["dsize"]
            d[off + i["doff"]:off + i["doff"] + len(px)] = px
            struct.pack_into(">256H", d, i["pal"] + 0x20, *pal)
            return bytes(d)
    raise SystemExit("no image %s" % name)


def add_images(d, new):
    old = entries(d)
    recs = {n: bytes(d[off:off + size]) for n, off, size in old}
    dir_end = 16 + sum(8 + len(n) + 1 for n, _, _ in old)
    tag = bytes(d[dir_end:dir_end + 8])
    for name, (tmpl, _) in new.items():
        if name in recs:
            raise SystemExit("image %s exists" % name)
        recs[name] = recs[tmpl]
    names = [n for n, _, _ in old]
    names = sorted(recs) if names == sorted(names) else names + [n for n in new if n not in names]
    head = 16 + sum(8 + len(n) + 1 for n in names) + len(tag)
    first = (head + 0x1F) & ~0x1F
    out = bytearray(b"ShpG" + struct.pack("<I", 0) + struct.pack(">II", len(names), head))
    offs, p = {}, first
    for n in names:
        offs[n] = p
        p = (p + len(recs[n]) + 0x1F) & ~0x1F
    for n in names:
        out += struct.pack(">II", offs[n], len(recs[n])) + n.encode() + b"\0"
    out += tag
    out += b"Buy ERTS"[:first - len(out)]
    out += bytes(first - len(out))
    for n in names:
        gap = offs[n] - len(out)
        out += (b"Buy ERTS" + bytes(gap))[:gap] + recs[n]
    out += bytes(-len(out) % 0x20) if len(d) % 0x20 == 0 else b""
    struct.pack_into("<I", out, 4, len(out))
    d = bytes(out)
    for name, (_, im) in new.items():
        d = replace(d, name, im)
    return d


def geo_add_records(g, new):
    n = struct.unpack_from("<I", g, 0)[0]
    offs = list(struct.unpack_from("<%dI" % n, g, 4))
    ends = sorted(offs) + [len(g)]
    recs = {}
    for o in offs:
        rid = struct.unpack_from("<I", g, o)[0]
        recs[rid] = bytes(g[o:ends[ends.index(o) + 1]])
    for rid, (tmpl, texmap) in new.items():
        r = bytearray(recs[tmpl])
        struct.pack_into("<I", r, 0, rid)
        npieces = struct.unpack_from("<I", r, 4)[0]
        if npieces != 1 or struct.unpack_from("<I", r, 8)[0] != 3:
            raise SystemExit("record %d: only single textured pieces are copied" % tmpl)
        old_tex = struct.unpack_from("<I", r, 8 + 20)[0]
        struct.pack_into("<I", r, 8 + 20, texmap[old_tex])
        recs[rid] = bytes(r)
    ids = sorted(recs, key=str)
    out = bytearray(struct.pack("<I", len(ids)) + bytes(4 * len(ids)))
    for i, rid in enumerate(ids):
        struct.pack_into("<I", out, 4 + 4 * i, len(out))
        out += recs[rid]
    return bytes(out)


if __name__ == "__main__":
    d = open(sys.argv[2], "rb").read()
    for name, off, size in entries(d):
        i = image_info(d, off)
        print("%-4s off 0x%X size 0x%X  %dx%d code 0x%08X" % (name, off, size, i["w"], i["h"], i["code"]))
        if sys.argv[1] == "decode":
            decode(d, off).save("%s%s.png" % (sys.argv[3], name))
