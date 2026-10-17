#!/usr/bin/env python3

import struct
import sys

ALIGN = 0x20


class Entry:
    __slots__ = ("offset", "size", "name", "hash", "data", "usize")

    def __init__(self, offset, size, name, h=None):
        self.offset, self.size, self.name, self.hash, self.data = offset, size, name, h, None
        self.usize = 0


def read_big_index(path):
    with open(path, "rb") as f:
        head = f.read(16)
        magic, total_le = head[:4], struct.unpack("<I", head[4:8])[0]
        count, index_size = struct.unpack(">II", head[8:16])
        if magic != b"BIG4":
            raise SystemExit("not a BIG4 archive: %r" % magic)
        rest = f.read(index_size - 16 + 0x40)
        f.seek(index_size)
        slack = f.read(0x40)
    entries, p = [], 0
    for _ in range(count):
        off, size = struct.unpack_from(">II", rest, p)
        end = rest.index(b"\0", p + 8)
        entries.append(Entry(off, size, rest[p + 8:end].decode("latin-1")))
        p = end + 1
    tail = rest[p:index_size - 16]
    if entries:
        slack = slack[:max(0, entries[0].offset - index_size)].rstrip(b"\0")
    read_big_index.slack = slack
    return entries, total_le, index_size, tail


def read_bh(path):
    d = open(path, "rb").read()
    if d[:4] != b"Viv4":
        raise SystemExit("not a Viv4 index: %r" % d[:4])
    size_le = struct.unpack_from("<I", d, 4)[0]
    count, size_be = struct.unpack_from(">II", d, 8)
    rows = [struct.unpack_from(">IIII", d, 16 + 16 * i) for i in range(count)]
    term = struct.unpack_from(">IIII", d, 16 + 16 * count)
    return rows, term, size_le, size_be, len(d)


def name_hash(name):
    h = 5381
    for c in name.lower().encode("latin-1"):
        h = (h * 33 + c) & 0xFFFFFFFF
    return h


def unpacked_size(data):
    if len(data) >= 5 and data[0] == 0x10 and data[1] == 0xFB:
        return int.from_bytes(data[2:5], "big")
    return 0


def cmd_list(big, sub=None):
    entries, total, index_size, tail = read_big_index(big)
    for e in entries:
        if sub is None or sub.lower() in e.name.lower():
            print("%08X %8X %s" % (e.offset, e.size, e.name))


def cmd_get(big, name, out):
    entries, *_ = read_big_index(big)
    for e in entries:
        if e.name.lower() == name.lower():
            with open(big, "rb") as f:
                f.seek(e.offset)
                data = f.read(e.size)
            open(out, "wb").write(data)
            return
    raise SystemExit("no entry %s" % name)


def plan_repack(big, bh, sets, adds):
    entries, total, index_size, tail = read_big_index(big)
    rows, term, bh_le, bh_be, bh_len = read_bh(bh)
    assert len(rows) == len(entries)
    for e, r in zip(entries, rows):
        assert (r[0], r[1]) == (e.offset, e.size), e.name
        e.hash, e.usize = r[3], r[2]
    by_name = {e.name.lower(): e for e in entries}
    load = lambda src: src if isinstance(src, bytes) else open(src, "rb").read()
    for name, src in sets:
        e = by_name.get(name.lower())
        if e is None:
            raise SystemExit("--set: no entry %s" % name)
        e.data = load(src)
        e.usize = unpacked_size(e.data)
    for name, src in adds:
        if name.lower() in by_name:
            raise SystemExit("--add: entry exists: %s" % name)
        e = Entry(0, 0, name, name_hash(name))
        e.data = load(src)
        e.usize = unpacked_size(e.data)
        entries.append(e)
        by_name[name.lower()] = e

    slack = read_big_index.slack
    new_index_size = 16 + sum(8 + len(e.name) + 1 for e in entries) + len(tail)
    pos = (new_index_size + len(slack) + ALIGN - 1) & ~(ALIGN - 1)
    plan = []
    for e in entries:
        size = len(e.data) if e.data is not None else e.size
        plan.append((e, pos, size))
        pos = (pos + size + ALIGN - 1) & ~(ALIGN - 1)
    new_total = pos

    index = b"BIG4" + struct.pack("<I", new_total) + struct.pack(">II", len(entries), new_index_size)
    index += b"".join(struct.pack(">II", off, size) + e.name.encode("latin-1") + b"\0" for e, off, size in plan)
    index += tail
    assert len(index) == new_index_size
    index += slack

    n = len(entries)
    bh_size = 16 + 16 * n + 16
    bh_out = b"Viv4" + struct.pack("<I", bh_size) + struct.pack(">II", n, bh_size)
    bh_out += b"".join(struct.pack(">IIII", off, size, e.usize, e.hash) for e, off, size in plan)
    bh_out += struct.pack(">IIII", new_total, 0, 0, 0)
    return plan, index, new_total, bh_out


def write_big(big, plan, index, total, dst):
    base = dst.tell()
    with open(big, "rb") as src:
        dst.write(index)
        for e, off, size in plan:
            dst.write(b"\0" * (base + off - dst.tell()))
            if e.data is not None:
                dst.write(e.data)
            else:
                src.seek(e.offset)
                left = size
                while left:
                    chunk = src.read(min(left, 1 << 22))
                    if not chunk:
                        raise SystemExit("short read in %s" % e.name)
                    dst.write(chunk)
                    left -= len(chunk)
        dst.write(b"\0" * (base + total - dst.tell()))
    return total


def cmd_repack(big, bh, out_big, out_bh, sets, adds):
    plan, index, total, bh_out = plan_repack(big, bh, sets, adds)
    with open(out_big, "wb") as dst:
        write_big(big, plan, index, total, dst)
    open(out_bh, "wb").write(bh_out)
    print("wrote %s (%d entries, 0x%X bytes) and %s" % (out_big, len(plan), total, out_bh))


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    cmd = argv[1]
    if cmd == "list":
        cmd_list(argv[2], argv[3] if len(argv) > 3 else None)
    elif cmd == "get":
        cmd_get(argv[2], argv[3], argv[4])
    elif cmd == "repack":
        big, bh, out_big, out_bh = argv[2:6]
        sets, adds, i = [], [], 6
        while i < len(argv):
            kind, spec = argv[i], argv[i + 1]
            name, path = spec.split("=", 1)
            (sets if kind == "--set" else adds).append((name, path))
            i += 2
        cmd_repack(big, bh, out_big, out_bh, sets, adds)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
