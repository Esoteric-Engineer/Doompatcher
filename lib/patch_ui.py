#!/usr/bin/env python3

import os
import struct
import sys

import bigtool
import nbig
from aptpatch import Apt

NEW_ID = 18
PORTRAIT_ID = 4
NAME = "DOCTOR DOOM"


def read_entry(big, name):
    entries, *_ = bigtool.read_big_index(big)
    for e in entries:
        if e.name.lower() == name.lower():
            with open(big, "rb") as f:
                f.seek(e.offset)
                return f.read(e.size)
    raise SystemExit("no entry " + name)


def split(files):
    d = {n.rsplit(".", 1)[-1].lower(): (n, b) for n, b in files}
    return d


def rebuild(files, apt_bytes, const_bytes, other=None):
    other = dict(other or {}, apt=apt_bytes, const=const_bytes)
    out = []
    for n, b in files:
        ext = n.rsplit(".", 1)[-1].lower()
        out.append((n, other.get(ext, b)))
    return nbig.save(out)


def patch_charselect(data):
    files = nbig.load(data)
    d = split(files)
    apt = Apt(d["apt"][1], d["const"][1])
    movie = apt.apt_off
    block = apt.frame_actions(movie, 0)[0]

    at = apt.find_push(block, lambda v: v[:1] == ["aObject"] and v[-1] == 18 and "thumb17" in v)
    items = apt.get_push(at)
    thumb = apt.push_str(block, "thumb%d" % NEW_ID)
    apt.set_push(at, [items[0], thumb] + items[1:-1] + [apt.const_int(NEW_ID + 1)])

    at = apt.find_push(block, lambda v: v[:1] == ["aCharObject"] and v[-1] == 18)
    items = apt.get_push(at)
    apt.set_push(at, [items[0]] + [items[1]] * 27 + [apt.const_int(27)])

    at = apt.find_push(block, lambda v: v[:1] == ["g_aCharacterOrder"] and v[-1] == 18 and v[1] == 17)
    items = apt.get_push(at)
    apt.set_push(at, [items[0], apt.const_int(NEW_ID)] + items[1:-1] + [apt.const_int(NEW_ID + 1)])

    a, c = apt.build()
    return rebuild(files, a, c)


def patch_thumbs(data, art=None):
    files = nbig.load(data)
    d = split(files)
    apt = Apt(d["apt"][1], d["const"][1])
    exports = dict(apt.exports())
    replaced = {}
    holder = None
    for n in range(apt.u32(apt.apt_off + 20)):
        c = apt.character(n)
        if c and apt.u32(c) == 5 and any(nm == "thumb17" for _, nm in apt.frame_places(c, 0)):
            holder = c
    if holder is None:
        raise SystemExit("thumbnail holder sprite not found")
    places = {nm: it for it, nm in apt.frame_places(holder, 0) if nm}

    src0, src9 = places["thumb0"], places["thumb9"]
    y0, y9 = struct.unpack_from(">f", apt.d, src0 + 36)[0], struct.unpack_from(">f", apt.d, src9 + 36)[0]
    rec = bytearray(apt.d[src9:src9 + 64])
    struct.pack_into(">f", rec, 36, y9 + (y9 - y0))
    depths = [struct.unpack_from(">i", apt.d, it + 8)[0] for it, _ in apt.frame_places(holder, 0)]
    struct.pack_into(">i", rec, 8, max(depths) + 2)
    struct.pack_into(">I", rec, 52, apt.append_str("thumb%d" % NEW_ID))
    apt.add_frame_item(holder, 0, apt.append(bytes(rec)))

    for block in apt.frame_actions(holder, 0):
        pool = apt.pool(block)
        for at, op in apt.walk(block):
            if op == 0x96:
                items = apt.get_push(at)
                if [apt.const_value(i, pool) for i in items] == [18]:
                    apt.set_push(at, [apt.const_int(NEW_ID + 1)])

    if art:
        new_sprite, geo, gsh = add_tile(apt, exports["char%d" % PORTRAIT_ID], d["geo"][1], d["gsh"][1], art)
        apt.add_export("char%d" % NEW_ID, new_sprite)
        replaced = {"geo": geo, "gsh": gsh}
    else:
        apt.add_export("char%d" % NEW_ID, exports["char%d" % PORTRAIT_ID])

    a, c = apt.build()
    return rebuild(files, a, c, replaced)


def add_tile(apt, sprite_id, geo, gsh, art):
    import gshtool
    import make_doom_portraits
    movie = apt.apt_off
    nchars, chars = apt.u32(movie + 20), apt.u32(movie + 24)
    src = apt.character(sprite_id)
    nframes, frames = apt.u32(src + 8), apt.u32(src + 12)
    table = [apt.u32(chars + 4 * i) for i in range(nchars)]
    shape_map, image_map = {}, {}
    geo_new, img_new = {}, {}
    images = {n: off for n, off, _ in gshtool.entries(gsh)}
    order = []
    for f in range(nframes):
        for it, _ in apt.frame_places(src, f):
            sh = apt.u32(it + 12)
            if sh in shape_map:
                continue
            shp = apt.character(sh)
            if apt.u32(shp) != 1:
                raise SystemExit("tile sprite places a non-shape")
            geo_id = apt.u32(shp + 24)
            new_shape = len(table)
            table.append(apt.append(bytes(apt.d[shp:shp + 28])))
            apt.put32(table[-1] + 24, new_shape)
            shape_map[sh] = new_shape
            old_tex = _geo_texture(geo, geo_id)
            img = apt.character(old_tex)
            new_img = len(table)
            table.append(apt.append(bytes(apt.d[img:img + 12])))
            apt.put32(table[-1] + 8, new_img)
            image_map[old_tex] = new_img
            geo_new[new_shape] = (geo_id, {old_tex: new_img})
            order.append(old_tex)
    if len(order) != 2:
        raise SystemExit("expected two tile pictures (unselected, selected), found %d" % len(order))
    jo = [gshtool.decode(gsh, images[str(t)]) for t in order]
    pics = make_doom_portraits.thumbs(art)
    for t, j, im in zip(order, jo, pics):
        if im.size != j.size:
            raise SystemExit("tile picture is %dx%d, not %dx%d" % (*im.size, *j.size))
        img_new[str(image_map[t])] = (str(t), im)
    sizes = {1: 8, 2: 16, 3: 64, 4: 8}
    new_frames = bytearray()
    for f in range(nframes):
        n, items, _ = apt.frame(src, f)
        ptrs = []
        for i in range(n):
            it = apt.u32(items + 4 * i)
            kind = apt.u32(it)
            if kind not in sizes:
                raise SystemExit("tile sprite frame item type %d not copied" % kind)
            rec = bytearray(apt.d[it:it + sizes[kind]])
            if kind == 1:
                struct.pack_into(">I", rec, 4, _copy_action(apt, apt.u32(it + 4)))
            elif kind == 3:
                if apt.u32(it + 52) or apt.u32(it + 60):
                    raise SystemExit("tile PlaceObject with a name or clip actions not copied")
                struct.pack_into(">I", rec, 12, shape_map[apt.u32(it + 12)])
            ptrs.append(apt.append(bytes(rec)))
        new_frames += struct.pack(">II", n, apt.append_u32s(ptrs))
    spr = bytearray(apt.d[src:src + 20])
    struct.pack_into(">I", spr, 12, apt.append(bytes(new_frames)))
    new_sprite = len(table)
    table.append(apt.append(bytes(spr)))
    apt.put32(movie + 24, apt.append_u32s(table))
    apt.put32(movie + 20, len(table))
    return new_sprite, gshtool.geo_add_records(geo, geo_new), gshtool.add_images(gsh, img_new)


def _copy_action(apt, block):
    end = None
    for at, op in apt.walk(block):
        if op in (0x8E, 0x9B):
            raise SystemExit("action block 0x%X defines a function: not copied" % block)
        end = at + 1
    apt.d += b"\0" * ((block - len(apt.d)) % 4)
    new = apt.append(bytes(apt.d[block:end]), align=1)
    for at, op in list(apt.walk(new)):
        if op in (0x88, 0x96):
            o = (at + 4) & ~3
            n, arr = apt.u32(o), apt.u32(o + 4)
            apt.put32(o + 4, apt.append_u32s([apt.u32(arr + 4 * k) for k in range(n)]))
    return new


def _geo_texture(geo, rid):
    n = struct.unpack_from("<I", geo, 0)[0]
    for o in struct.unpack_from("<%dI" % n, geo, 4):
        if struct.unpack_from("<I", geo, o)[0] == rid:
            if struct.unpack_from("<II", geo, o + 4) != (1, 3):
                raise SystemExit(".geo record %d is not one textured piece" % rid)
            return struct.unpack_from("<I", geo, o + 8 + 20)[0]
    raise SystemExit("no .geo record %d" % rid)


def patch_main(data):
    files = nbig.load(data)
    d = split(files)
    apt = Apt(d["apt"][1], d["const"][1])
    movie = apt.apt_off
    done = set()
    nframes = apt.u32(movie + 8)
    for f in range(nframes):
        for block in apt.frame_actions(movie, f):
            if apt.d[block] != 0x88:
                continue
            pool = apt.pool(block)
            for at, op in list(apt.walk(block)):
                if op != 0x96:
                    continue
                items = apt.get_push(at)
                vals = [apt.const_value(i, pool) for i in items]
                if len(vals) >= 19 and vals[-1] == 18 and vals[-2] == "~kT_THING" and vals[-19] == "~kT_VANROEKEL":
                    name = apt.push_str(block, NAME)
                    apt.set_push(at, items[:-19] + [name] + items[-19:-1] + [apt.const_int(19)])
                    done.add("names")
                elif len(vals) >= 19 and vals[-1] == 18 and vals[-2] == 11897431 and vals[-19] == 9484461:
                    apt.set_push(at, items[:-19] + [apt.const_int(0xFFFFFF)] + items[-19:-1] + [apt.const_int(19)])
                    done.add("colours")
                elif vals[-2:] == ["kGlobal_Max_NumChar", 18]:
                    apt.set_push(at, items[:-1] + [apt.const_int(NEW_ID + 1)])
                    done.add("max")
    if done != {"names", "colours", "max"}:
        raise SystemExit("main movie: lists not found: %s" % sorted(done))
    a, c = apt.build()
    return rebuild(files, a, c)


def rename_archive(data, old, new):
    out = []
    for n, b in nbig.load(data):
        if not n.lower().startswith(old.lower() + "."):
            raise SystemExit("unexpected file %s in %s" % (n, old))
        out.append((new + n[len(old):], b))
    return nbig.save(out)


def main(big, out, art=None):
    os.makedirs(out, exist_ok=True)
    args = []

    def emit(kind, name, data):
        path = os.path.join(out, name.replace("/", "__"))
        open(path, "wb").write(data)
        args.extend([kind, "%s=%s" % (name, path)])

    P = "Apt/clash/"
    emit("--set", P + "screens/clashCharSelect.big", patch_charselect(read_entry(big, P + "screens/clashCharSelect.big")))
    emit("--set", P + "screens/clashCharSelect_thumbs.big", patch_thumbs(read_entry(big, P + "screens/clashCharSelect_thumbs.big"), art))
    for name in ("main.big", "mainBE.big"):
        emit("--set", P + name, patch_main(read_entry(big, P + name)))
    dd, new = PORTRAIT_ID, NEW_ID
    if art:
        import gshtool
        import make_doom_portraits
        icons = make_doom_portraits.hud_icons(art)
        for lang in ("ENG", "FRA", "GER", "ITA"):
            name = "HUD/hud%s.1.gsh" % lang
            emit("--set", name, gshtool.add_images(read_entry(big, name), icons))
        res = make_doom_portraits.build(big, art, new)
        for name in ("c%d_p0" % new, "cvs%d" % new, "cvs%d_alt" % new):
            emit("--add" if name.endswith("_alt") else "--set", P + "portraits/%s.big" % name, res[P + "portraits/%s.big" % name])
        open(os.path.join(out, "repack_args.txt"), "w").write("\n".join(args) + "\n")
        print("wrote %d archives to %s" % (len(args) // 2, out))
        return
    emit("--set", P + "portraits/c%d_p0.big" % new, rename_archive(read_entry(big, P + "portraits/c%d_p0.big" % dd), "c%d_p0" % dd, "c%d_p0" % new))
    emit("--set", P + "portraits/cvs%d.big" % new, rename_archive(read_entry(big, P + "portraits/cvs%d.big" % dd), "cvs%d" % dd, "cvs%d" % new))
    emit("--add", P + "portraits/cvs%d_alt.big" % new, rename_archive(read_entry(big, P + "portraits/cvs%d_alt.big" % dd), "cvs%d_alt" % dd, "cvs%d_alt" % new))
    open(os.path.join(out, "repack_args.txt"), "w").write("\n".join(args) + "\n")
    print("wrote %d archives to %s" % (len(args) // 2, out))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
