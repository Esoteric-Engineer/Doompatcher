#!/usr/bin/env python3

import sys


def decompress(src):
    flags = (src[0] << 8) | src[1]
    if src[1] != 0xFB:
        raise ValueError("not RefPack: %02X %02X" % (src[0], src[1]))
    p = 2
    if flags & 0x0100:
        p += 3
    n = 4 if flags & 0x8000 else 3
    size = int.from_bytes(src[p:p + n], "big")
    p += n
    out = bytearray()
    while True:
        b0 = src[p]; p += 1
        if b0 < 0x80:
            b1 = src[p]; p += 1
            lit = b0 & 3
            off = ((b0 & 0x60) << 3) + b1 + 1
            cnt = ((b0 & 0x1C) >> 2) + 3
        elif b0 < 0xC0:
            b1, b2 = src[p], src[p + 1]; p += 2
            lit = b1 >> 6
            off = ((b1 & 0x3F) << 8) + b2 + 1
            cnt = (b0 & 0x3F) + 4
        elif b0 < 0xE0:
            b1, b2, b3 = src[p], src[p + 1], src[p + 2]; p += 3
            lit = b0 & 3
            off = ((b0 & 0x10) << 12) + (b1 << 8) + b2 + 1
            cnt = ((b0 & 0x0C) << 6) + b3 + 5
        elif b0 < 0xFC:
            lit = ((b0 & 0x1F) << 2) + 4
            out += src[p:p + lit]; p += lit
            continue
        else:
            lit = b0 & 3
            out += src[p:p + lit]; p += lit
            break
        out += src[p:p + lit]; p += lit
        start = len(out) - off
        if start < 0:
            raise ValueError("bad back reference")
        for i in range(cnt):
            out.append(out[start + i])
    if len(out) != size:
        raise ValueError("size mismatch: header %d, got %d" % (size, len(out)))
    return bytes(out)


def compress(data, window=0x4000, max_chain=48):
    n = len(data)
    if n >= 1 << 24:
        raise ValueError("too large")
    out = bytearray(b"\x10\xFB" + n.to_bytes(3, "big"))
    head = {}
    prev = [0] * n
    lit_start = 0
    p = 0

    def flush_literals(upto):
        nonlocal lit_start
        while upto - lit_start >= 4:
            run = min(112, (upto - lit_start) & ~3)
            out.append(0xE0 + (run - 4) // 4)
            out.extend(data[lit_start:lit_start + run])
            lit_start += run

    def insert(i):
        if i + 3 <= n:
            k = data[i:i + 3]
            prev[i] = head.get(k, -1)
            head[k] = i

    while p < n:
        best_len, best_off = 0, 0
        if p + 3 <= n:
            cand = head.get(data[p:p + 3], -1)
            chain = max_chain
            limit = min(n - p, 67)
            while cand >= 0 and chain and p - cand <= window:
                if data[cand + best_len:cand + best_len + 1] == data[p + best_len:p + best_len + 1]:
                    l = 0
                    while l < limit and data[cand + l] == data[p + l]:
                        l += 1
                    if l > best_len:
                        best_len, best_off = l, p - cand
                        if l == limit:
                            break
                cand = prev[cand]
                chain -= 1
        ok = best_len >= 3 and (best_off <= 1024 or best_len >= 4)
        if ok:
            flush_literals(p)
            lit = p - lit_start
            off = best_off - 1
            if best_len <= 10 and best_off <= 1024:
                out.append(((off >> 8) << 5) | ((best_len - 3) << 2) | lit)
                out.append(off & 0xFF)
            else:
                out.append(0x80 | (best_len - 4))
                out.append((lit << 6) | (off >> 8))
                out.append(off & 0xFF)
            out.extend(data[lit_start:p])
            for i in range(p, p + best_len):
                insert(i)
            p += best_len
            lit_start = p
        else:
            insert(p)
            p += 1
    flush_literals(n)
    out.append(0xFC + (n - lit_start))
    out.extend(data[lit_start:])
    return bytes(out)


if __name__ == "__main__":
    mode, src, dst = sys.argv[1:4]
    d = open(src, "rb").read()
    open(dst, "wb").write(decompress(d) if mode == "d" else compress(d))
