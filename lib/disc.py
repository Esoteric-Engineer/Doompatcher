import struct

SECTOR = 0x8000
CISO_HEADER = 0x8000
GC_DISC_SIZE = 1459978240


class Image:

    def __init__(self, path):
        self.f = open(path, "rb")
        head = self.f.read(8)
        self.blocks = None
        if head[:4] == b"CISO":
            self.block_size = struct.unpack_from("<I", head, 4)[0]
            present = self.f.read(CISO_HEADER - 8)
            self.blocks, n = [], 0
            for b in present:
                self.blocks.append(n if b else None)
                n += 1 if b else 0

    def read(self, offset, size):
        if self.blocks is None:
            self.f.seek(offset)
            data = self.f.read(size)
            return data + b"\0" * (size - len(data))
        out = bytearray()
        bs = self.block_size
        while size:
            i, within = divmod(offset, bs)
            n = min(size, bs - within)
            slot = self.blocks[i] if i < len(self.blocks) else None
            if slot is None:
                out += b"\0" * n
            else:
                self.f.seek(CISO_HEADER + slot * bs + within)
                out += self.f.read(n)
            offset += n
            size -= n
        return bytes(out)

    def copy(self, offset, size, dst, chunk=1 << 22):
        while size:
            n = min(size, chunk)
            dst.write(self.read(offset, n))
            offset += n
            size -= n


class FileEntry:
    __slots__ = ("path", "offset", "size")

    def __init__(self, path, offset, size):
        self.path, self.offset, self.size = path, offset, size


class Disc:
    def __init__(self, path):
        self.img = Image(path)
        self.boot = self.img.read(0, 0x440)
        self.bi2 = self.img.read(0x440, 0x2000)
        ap_size, ap_trailer = struct.unpack(">II", self.img.read(0x2440 + 0x14, 8))
        self.apploader = self.img.read(0x2440, 0x20 + ap_size + ap_trailer)
        self.game_id = self.boot[:6].decode("latin-1")
        self.revision = self.boot[7]
        self.dol_offset, self.fst_offset, self.fst_size = struct.unpack_from(">III", self.boot, 0x420)
        self.fst = self.img.read(self.fst_offset, self.fst_size)
        self.dol = self.img.read(self.dol_offset, dol_size(self.img.read(self.dol_offset, 0x100)))
        self.files = parse_fst(self.fst)

    def file(self, path):
        for e in self.files:
            if e.path.lower() == path.lower():
                return e
        raise KeyError(path)

    def read_file(self, path):
        e = self.file(path)
        return self.img.read(e.offset, e.size)

    def extract(self, path, out):
        e = self.file(path)
        with open(out, "wb") as f:
            self.img.copy(e.offset, e.size, f)


def dol_size(head):
    offs = struct.unpack_from(">18I", head, 0)
    sizes = struct.unpack_from(">18I", head, 0x90)
    return max(o + s for o, s in zip(offs, sizes) if s)


def parse_fst(fst):
    count = struct.unpack_from(">I", fst, 8)[0]
    names = fst[count * 12:]
    files, stack = [], [(count, "")]

    def name(i):
        off = struct.unpack_from(">I", fst, i * 12)[0] & 0xFFFFFF
        return names[off:names.index(b"\0", off)].decode("latin-1")

    for i in range(1, count):
        while i >= stack[-1][0]:
            stack.pop()
        flags = fst[i * 12]
        a, b = struct.unpack_from(">II", fst, i * 12 + 4)
        if flags:
            stack.append((b, stack[-1][1] + name(i) + "/"))
        else:
            files.append(FileEntry(stack[-1][1] + name(i), a, b))
    return files


def write_iso(out, disc, dol, replace):
    replace = {k.lower(): v for k, v in replace.items()}
    order = sorted(disc.files, key=lambda e: e.offset)
    fst = bytearray(disc.fst)
    count = struct.unpack_from(">I", fst, 8)[0]
    index = {}
    for i, e in zip([j for j in range(1, count) if not fst[j * 12]], disc.files):
        index[e.path] = i
    if len(dol) > disc.fst_offset - disc.dol_offset:
        raise SystemExit("the patched DOL does not fit before the FST")

    with open(out, "wb") as f:
        f.write(disc.boot + disc.bi2 + disc.apploader)
        f.seek(disc.dol_offset)
        f.write(dol)
        pos = disc.fst_offset + disc.fst_size
        for e in order:
            start = max(e.offset, (pos + SECTOR - 1) & ~(SECTOR - 1))
            f.seek(start)
            src = replace.get(e.path.lower())
            if src is None:
                disc.img.copy(e.offset, e.size, f)
                size = e.size
            elif callable(src):
                size = src(f)
            else:
                f.write(src)
                size = len(src)
            struct.pack_into(">II", fst, index[e.path] * 12 + 4, start, size)
            pos = start + size
        if pos > GC_DISC_SIZE:
            raise SystemExit("the patched game is 0x%X bytes, more than a GameCube disc holds" % pos)
        f.seek(disc.fst_offset)
        f.write(fst)
        f.truncate(GC_DISC_SIZE)
    return GC_DISC_SIZE
