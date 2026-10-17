#!/usr/bin/env python3

import struct
import sys

from PIL import Image

FMT_CMPR = 0xE
M64 = (1 << 64) - 1


def _c565(c):
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _palette(c0, c1):
    a, b = _c565(c0), _c565(c1)
    if c0 > c1:
        return [a, b, tuple((2 * x + y) // 3 for x, y in zip(a, b)), tuple((x + 2 * y) // 3 for x, y in zip(a, b))]
    return [a, b, tuple((x + y) // 2 for x, y in zip(a, b)), None]


def decode_cmpr(data, w, h):
    im = Image.new("RGBA", (w, h))
    px = im.load()
    p = 0
    for ty in range(0, h, 8):
        for tx in range(0, w, 8):
            for by, bx in ((0, 0), (0, 4), (4, 0), (4, 4)):
                c0, c1 = struct.unpack_from(">HH", data, p)
                pal = _palette(c0, c1)
                for row in range(4):
                    byte = data[p + 4 + row]
                    for col in range(4):
                        c = pal[(byte >> (6 - 2 * col)) & 3]
                        px[tx + bx + col, ty + by + row] = (0, 0, 0, 0) if c is None else c + (255,)
                p += 8
    return im


def _565(rgb):
    r, g, b = rgb
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)


def _encode_block(pixels):
    n = 16
    mean = [sum(p[i] for p in pixels) / n for i in range(3)]
    d = [[p[i] - mean[i] for i in range(3)] for p in pixels]
    cov = [[sum(v[i] * v[j] for v in d) for j in range(3)] for i in range(3)]
    axis = [1.0, 1.0, 1.0]
    for _ in range(6):
        nxt = [sum(cov[i][j] * axis[j] for j in range(3)) for i in range(3)]
        norm = max(abs(x) for x in nxt) or 1.0
        axis = [x / norm for x in nxt]
    proj = [sum(v[i] * axis[i] for i in range(3)) for v in d]
    lo, hi = min(proj), max(proj)
    if hi - lo < 1e-6:
        lo = hi = 0.0
    e0, e1 = (tuple(max(0, min(255, round(mean[i] + axis[i] * t))) for i in range(3)) for t in (lo, hi))
    a, b = _565(e0), _565(e1)
    if a == b:
        b = a
    if a < b:
        a, b = b, a
    if a == b:
        if a < 0xFFFF:
            a += 1
        else:
            b -= 1
    pal = _palette(a, b)
    out = bytearray(struct.pack(">HH", a, b))
    for row in range(4):
        byte = 0
        for col in range(4):
            p = pixels[row * 4 + col]
            best = min(range(4), key=lambda j: (p[0] - pal[j][0]) ** 2 + (p[1] - pal[j][1]) ** 2 + (p[2] - pal[j][2]) ** 2)
            byte |= best << (6 - 2 * col)
        out.append(byte)
    return bytes(out)


def encode_cmpr(im):
    im = im.convert("RGB")
    w, h = im.size
    assert w % 8 == 0 and h % 8 == 0, "size must be a multiple of 8"
    px = im.load()
    out = bytearray()
    for ty in range(0, h, 8):
        for tx in range(0, w, 8):
            for by, bx in ((0, 0), (0, 4), (4, 0), (4, 4)):
                out += _encode_block([px[tx + bx + c, ty + by + r] for r in range(4) for c in range(4)])
    return bytes(out)


def tpl_images(tpl):
    magic, n, tab = struct.unpack_from(">III", tpl, 0)
    assert magic == 0x0020AF30, "not a TPL"
    out = []
    for i in range(n):
        ih, _pal = struct.unpack_from(">II", tpl, tab + 8 * i)
        h, w, fmt, off = struct.unpack_from(">HHII", tpl, ih)
        out.append({"w": w, "h": h, "fmt": fmt, "off": off, "hdr": ih})
    return out


def cmpr_size(w, h):
    return w * h // 2


def replace_cmpr(tpl, index, data):
    im = tpl_images(tpl)[index]
    assert im["fmt"] == FMT_CMPR, "image %d is format %d, not CMPR" % (index, im["fmt"])
    n = cmpr_size(im["w"], im["h"])
    assert len(data) == n, "need %d bytes, got %d" % (n, len(data))
    return tpl[:im["off"]] + data + tpl[im["off"] + n:]


_P1, _P2, _P3, _P4, _P5 = (11400714785074694791, 14029467366897019727, 1609587929392839161, 9650029242287828579, 2870177450012600261)


def _rol(x, r):
    return ((x << r) | (x >> (64 - r))) & M64


def _round(a, i):
    return (_rol((a + i * _P2) & M64, 31) * _P1) & M64


def xxh64(d):
    n, p = len(d), 0
    if n >= 32:
        v = [(_P1 + _P2) & M64, _P2, 0, (-_P1) & M64]
        while p <= n - 32:
            for k in range(4):
                v[k] = _round(v[k], struct.unpack_from("<Q", d, p)[0])
                p += 8
        h = (_rol(v[0], 1) + _rol(v[1], 7) + _rol(v[2], 12) + _rol(v[3], 18)) & M64
        for k in range(4):
            h = ((h ^ _round(0, v[k])) * _P1 + _P4) & M64
    else:
        h = _P5
    h = (h + n) & M64
    while p + 8 <= n:
        h ^= _round(0, struct.unpack_from("<Q", d, p)[0])
        h = (_rol(h, 27) * _P1 + _P4) & M64
        p += 8
    if p + 4 <= n:
        h ^= (struct.unpack_from("<I", d, p)[0] * _P1) & M64
        h = (_rol(h, 23) * _P2 + _P3) & M64
        p += 4
    while p < n:
        h ^= (d[p] * _P5) & M64
        h = (_rol(h, 11) * _P1) & M64
        p += 1
    h ^= h >> 33
    h = (h * _P2) & M64
    h ^= h >> 29
    h = (h * _P3) & M64
    h ^= h >> 32
    return h


def dolphin_name(tpl, index):
    im = tpl_images(tpl)[index]
    assert im["fmt"] == FMT_CMPR
    n = cmpr_size(im["w"], im["h"])
    return "tex1_%dx%d_%016x_%d" % (im["w"], im["h"], xxh64(tpl[im["off"]:im["off"] + n]), im["fmt"])


def main(argv):
    cmd = argv[1]
    if cmd == "info":
        for i, im in enumerate(tpl_images(open(argv[2], "rb").read())):
            print(i, "%dx%d" % (im["w"], im["h"]), "fmt", im["fmt"], "data @0x%X" % im["off"])
    elif cmd == "decode":
        tpl = open(argv[2], "rb").read()
        im = tpl_images(tpl)[int(argv[3])]
        decode_cmpr(tpl[im["off"]:im["off"] + cmpr_size(im["w"], im["h"])], im["w"], im["h"]).save(argv[4])
    elif cmd == "encode":
        open(argv[3], "wb").write(encode_cmpr(Image.open(argv[2])))
    elif cmd == "hash":
        print(dolphin_name(open(argv[2], "rb").read(), int(argv[3])))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
