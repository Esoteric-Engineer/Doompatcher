#!/usr/bin/env python3

import os
import struct
import sys

import refpack

ALIGN = 0x80
TAG = b"L231\0\0\0\0"


def load(data):
    if data[:2] == b"\x10\xfb":
        data = refpack.decompress(data)
    if data[:4] != b"BIGF":
        raise ValueError("not BIGF: %r" % data[:4])
    count, hsize = struct.unpack_from(">II", data, 8)
    out, p = [], 16
    for _ in range(count):
        off, size = struct.unpack_from(">II", data, p)
        end = data.index(b"\0", p + 8)
        out.append((data[p + 8:end].decode("latin-1"), data[off:off + size]))
        p = end + 1
    return out


def save(files, compress=True):
    hsize = 16 + sum(8 + len(n) + 1 for n, _ in files) + len(TAG)
    pos = (hsize + ALIGN - 1) & ~(ALIGN - 1)
    index, body = bytearray(), bytearray()
    for n, d in files:
        index += struct.pack(">II", pos + len(body), len(d)) + n.encode("latin-1") + b"\0"
        body += d
        body += b"\0" * (-len(body) % ALIGN)
    total = pos + len(body)
    head = b"BIGF" + struct.pack("<I", total) + struct.pack(">II", len(files), hsize) + bytes(index) + TAG
    raw = head + b"\0" * (pos - len(head)) + bytes(body)
    return refpack.compress(raw) if compress else raw


if __name__ == "__main__":
    files = load(open(sys.argv[2], "rb").read())
    if sys.argv[1] == "list":
        for n, d in files:
            print("%8X %s" % (len(d), n))
    else:
        os.makedirs(sys.argv[3], exist_ok=True)
        for n, d in files:
            open(os.path.join(sys.argv[3], n.replace("/", "_")), "wb").write(d)
