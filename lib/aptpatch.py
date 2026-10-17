#!/usr/bin/env python3

import struct

import aptdump as A

CONST_MAGIC = b"Apt constant file\x1a\0\0"


class Apt:
    def __init__(self, apt, const):
        self.d = bytearray(apt)
        if const[:0x14] != CONST_MAGIC:
            raise ValueError("bad .const header")
        self.apt_off, count, self.items_off = struct.unpack_from(">III", const, 0x14)
        self.items = [list(struct.unpack_from(">II", const, self.items_off + 8 * i)) for i in range(count)]
        self.n_orig = count
        self.const_head = const[:self.items_off]
        self.strings = bytearray(const[self.items_off + 8 * count:])
        self.strings_base = self.items_off + 8 * count
        self.new_strings = {}
        self.r = A.R(self.d)

    # .const
    def _add_item(self, typ, value):
        self.items.append([typ, value])
        return len(self.items) - 1

    def const_str(self, s):
        self.strings += b"\0" * (-len(self.strings) % 4)
        off = len(self.strings)
        self.strings += s.encode("latin-1") + b"\0"
        i = self._add_item(1, 0)
        self.new_strings[i] = off
        return i

    def const_int(self, v):
        return self._add_item(7, v & 0xFFFFFFFF)

    def const_pool(self, pool_index):
        return self._add_item(8, pool_index)

    def const_value(self, idx, pool=None):
        typ, v = self.items[idx]
        if typ == 8 and pool is not None:
            return self.const_value(pool[v])
        if typ == 1:
            if idx in self.new_strings:
                off = self.new_strings[idx]
            else:
                off = v - self.strings_base
            end = self.strings.index(b"\0", off)
            return self.strings[off:end].decode("latin-1")
        if typ == 7:
            return v - (1 << 32) if v & 0x80000000 else v
        return (typ, v)

    # .apt
    def u32(self, o):
        return struct.unpack_from(">I", self.d, o)[0]

    def put32(self, o, v):
        struct.pack_into(">I", self.d, o, v & 0xFFFFFFFF)

    def append(self, data, align=4):
        self.d += b"\0" * (-len(self.d) % align)
        off = len(self.d)
        self.d += data
        return off

    def append_u32s(self, values):
        return self.append(b"".join(struct.pack(">I", v & 0xFFFFFFFF) for v in values))

    def append_str(self, s):
        return self.append(s.encode("latin-1") + b"\0")

    # action blocks
    def pool(self, block):
        if self.d[block] != 0x88:
            raise ValueError("no ConstantPool at 0x%X" % block)
        p = A.al4(block + 1)
        n, ptr = self.u32(p), self.u32(p + 4)
        return [self.u32(ptr + 4 * i) for i in range(n)]

    def extend_pool(self, block, item_indices):
        old = self.pool(block)
        p = A.al4(block + 1)
        self.put32(p, len(old) + len(item_indices))
        self.put32(p + 4, self.append_u32s(old + list(item_indices)))
        return len(old)

    def push_str(self, block, s):
        return self.const_pool(self.extend_pool(block, [self.const_str(s)]))

    def get_push(self, at):
        if self.d[at] != 0x96:
            raise ValueError("no PushData at 0x%X" % at)
        p = A.al4(at + 1)
        n, ptr = self.u32(p), self.u32(p + 4)
        return [self.u32(ptr + 4 * i) for i in range(n)]

    def set_push(self, at, items):
        if self.d[at] != 0x96:
            raise ValueError("no PushData at 0x%X" % at)
        p = A.al4(at + 1)
        self.put32(p, len(items))
        self.put32(p + 4, self.append_u32s(items))

    def walk(self, p, end=None):
        d = self.d
        while end is None or p < end:
            at = p
            op = d[p]; p += 1
            yield at, op
            if op == 0x00 and end is None:
                return
            if op in A.STR_OPS or op in A.I32_OPS or op in A.BR_OPS or op in (0xB4, 0xB7):
                p = A.al4(p) + 4
            elif op in A.CONST_BYTE_OPS or op in (0xB5, 0xB9):
                p += 1
            elif op in (0xA3, 0xB6):
                p += 2
            elif op in (0x83, 0x88, 0x96):
                p = A.al4(p) + 8
            elif op == 0x9B:
                p = A.al4(p)
                size = struct.unpack_from(">i", d, p + 12)[0]
                p += 24
                yield from self.walk(p, p + size)
                p += size
            elif op == 0x8E:
                p = A.al4(p)
                size = struct.unpack_from(">i", d, p + 16)[0]
                p += 28
                yield from self.walk(p, p + size)
                p += size

    def find_push(self, block, pred):
        pool = self.pool(block)
        hits = []
        for at, op in self.walk(block):
            if op == 0x96:
                vals = [self.const_value(i, pool) for i in self.get_push(at)]
                if pred(vals):
                    hits.append(at)
        if len(hits) != 1:
            raise ValueError("expected one matching PushData in block 0x%X, found %d" % (block, len(hits)))
        return hits[0]

    # movie structure
    def character(self, n):
        chars = self.u32(self.apt_off + 24)
        return self.u32(chars + 4 * n)

    def frame(self, char_ptr, f):
        frames = self.u32(char_ptr + 12)
        rec = frames + 8 * f
        return self.u32(rec), self.u32(rec + 4), rec

    def frame_actions(self, char_ptr, f):
        n, items, _ = self.frame(char_ptr, f)
        out = []
        for i in range(n):
            it = self.u32(items + 4 * i)
            if self.u32(it) == 1:
                out.append(self.u32(it + 4))
        return out

    def frame_places(self, char_ptr, f):
        n, items, _ = self.frame(char_ptr, f)
        out = []
        for i in range(n):
            it = self.u32(items + 4 * i)
            if self.u32(it) == 3:
                out.append((it, self.r.s(self.u32(it + 52))))
        return out

    def add_frame_item(self, char_ptr, f, item_ptr):
        n, items, rec = self.frame(char_ptr, f)
        new = self.append_u32s([self.u32(items + 4 * i) for i in range(n)] + [item_ptr])
        self.put32(rec, n + 1)
        self.put32(rec + 4, new)

    def exports(self):
        n, ptr = self.u32(self.apt_off + 48), self.u32(self.apt_off + 52)
        return [(self.r.s(self.u32(ptr + 8 * i)), self.u32(ptr + 8 * i + 4)) for i in range(n)]

    def add_export(self, name, char_id):
        n, ptr = self.u32(self.apt_off + 48), self.u32(self.apt_off + 52)
        old = bytes(self.d[ptr:ptr + 8 * n])
        name_ptr = self.append_str(name)
        new = self.append(old + struct.pack(">II", name_ptr, char_id))
        self.put32(self.apt_off + 48, n + 1)
        self.put32(self.apt_off + 52, new)

    # output
    def build(self):
        added = len(self.items) - self.n_orig
        shift = 8 * added
        new_base = self.strings_base + shift
        items = bytearray()
        for i, (typ, v) in enumerate(self.items):
            if typ == 1:
                v = new_base + self.new_strings[i] if i in self.new_strings else v + shift
            items += struct.pack(">II", typ, v)
        head = bytearray(self.const_head)
        struct.pack_into(">I", head, 0x18, len(self.items))
        return bytes(self.d), bytes(head) + bytes(items) + bytes(self.strings)
