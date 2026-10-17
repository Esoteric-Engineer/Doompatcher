#!/usr/bin/env python3

import os
import struct
import sys

from PIL import Image, ImageChops, ImageFilter, ImageStat

import bigtool
import gshtool
import nbig
from aptpatch import Apt

PORTRAIT_SRC = 4
SELECT, SELECT_ALT = "DrDoom.png", "DrDoom-Dark.png"
STRIPS = ("entermatch-slice1.png", "entermatch-slice2.png")
TILES = ("charselect-normal.png", "charselect-selected.png")
ICON, ICON_RAGE = "icon.png", "icon-rage.png"
CROPS = {"entermatch-slice1.png": (2.0, 162.5, 18.0), "entermatch-slice2.png": (2.0, 226.5, 18.0),
         "icon.png": (0.674, 161.5, 28.1)}
CROP_TOLERANCE = 16.0
SELECT_SCALE, SELECT_AT = 0.8, (-30, 30)


def read_entry(big, name):
    entries, *_ = bigtool.read_big_index(big)
    for e in entries:
        if e.name.lower() == name.lower():
            with open(big, "rb") as f:
                f.seek(e.offset)
                return f.read(e.size)
    raise SystemExit("no entry " + name)


def geo_records(d):
    n = struct.unpack_from("<I", d, 0)[0]
    out = []
    for o in struct.unpack_from("<%dI" % n, d, 4):
        rid, npieces = struct.unpack_from("<II", d, o)
        p = o + 8
        pieces = []
        for _ in range(npieces):
            tex = struct.unpack_from("<6I", d, p)[5]
            m = struct.unpack_from("<16f", d, p + 24)
            p += 88
            pts = []
            for _ in range(2):
                pts += [struct.unpack_from("<3f", d, p + 4 + 12 * k)[:2] for k in range(3)]
                p += 40
            xs, ys = [q[0] for q in pts], [q[1] for q in pts]
            pieces.append({"rid": rid, "tex": str(tex), "s": m[0], "t": (m[12], m[13]), "x0": min(xs),
                           "y0": min(ys), "x1": max(xs), "y1": max(ys)})
        out.append(pieces)
    return out


def shape_offsets(apt, const):
    apt = Apt(apt, const)
    movie = apt.apt_off
    out = {}
    for f in range(apt.u32(movie + 8)):
        for it, _ in apt.frame_places(movie, f):
            c = apt.u32(it + 12)
            if c == 0xFFFFFFFF or apt.u32(apt.character(c)) != 5:
                continue
            for it2, _ in apt.frame_places(apt.character(c), 0):
                shp = apt.character(apt.u32(it2 + 12))
                if apt.u32(shp) == 1:
                    x, y = struct.unpack_from(">2f", apt.d, it + 32)
                    x2, y2 = struct.unpack_from(">2f", apt.d, it2 + 32)
                    out.setdefault(apt.u32(shp + 24), (x + x2, y + y2))
    return out


def canvas_of(pieces):
    s = pieces[0]["s"]
    X0, Y0 = min(p["x0"] for p in pieces), min(p["y0"] for p in pieces)
    X1, Y1 = max(p["x1"] for p in pieces), max(p["y1"] for p in pieces)
    return s, X0, Y0, int(round((X1 - X0) * s)), int(round((Y1 - Y0) * s))


def redraw(gsh, records, art_for_record):
    for i, pieces in enumerate(records):
        s, X0, Y0, W, H = canvas_of(pieces)
        canvas = art_for_record(i, W, H)
        for p in pieces:
            info = next(gshtool.image_info(gsh, off) for n, off, _ in gshtool.entries(gsh) if n == p["tex"])
            dx, dy = p["t"][0] + X0 * s, p["t"][1] + Y0 * s
            img = Image.new("RGBA", (info["w"], info["h"]), (0, 0, 0, 0))
            img.paste(canvas, (int(round(dx)), int(round(dy))))
            gsh = gshtool.replace(gsh, p["tex"], img)
    return gsh


def rename_archive(files, old, new):
    out = []
    for n, b in files:
        if not n.lower().startswith(old.lower() + "."):
            raise SystemExit("unexpected file %s in %s" % (n, old))
        out.append((new + n[len(old):], b))
    return out


def glow(im, colour, radius):
    a = im.getchannel("A").filter(ImageFilter.GaussianBlur(radius))
    g = Image.new("RGBA", im.size, colour)
    g.putalpha(a.point(lambda v: min(255, v * 2)))
    g.alpha_composite(im)
    return g


# alt-costume
def pixels(im):
    return im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()


def luminance(p):
    return (299 * p[0] + 587 * p[1] + 114 * p[2]) // 1000


class DarkRecolour:

    def __init__(self, art):
        a = Image.open(os.path.join(art, SELECT)).convert("RGBA")
        b = Image.open(os.path.join(art, SELECT_ALT)).convert("RGBA")
        if a.size != b.size:
            raise SystemExit("%s and %s differ in size" % (SELECT, SELECT_ALT))
        diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
        self.mask = ImageChops.multiply(diff.point(lambda v: 255 if v > 2 else 0),
                                        a.getchannel("A").point(lambda v: 255 if v > 200 else 0))
        acc = [[0, 0, 0, 0] for _ in range(256)]
        for p, q, m in zip(pixels(a), pixels(b), pixels(self.mask)):
            if m:
                x = acc[luminance(p)]
                x[0] += q[0]; x[1] += q[1]; x[2] += q[2]; x[3] += 1
        known = [(i, (x[0] / x[3], x[1] / x[3], x[2] / x[3])) for i, x in enumerate(acc) if x[3] >= 3]
        lut = []
        for i in range(256):
            lo = max((k for k in known if k[0] <= i), default=known[0], key=lambda k: k[0])
            hi = min((k for k in known if k[0] >= i), default=None, key=lambda k: k[0])
            if hi is None:
                top = known[-8:]
                r = [sum(c[1][j] for c in top) / sum(c[0] or 1 for c in top) for j in range(3)]
                lut.append(tuple(min(255, int(round(i * r[j]))) for j in range(3)))
            elif hi[0] == lo[0]:
                lut.append(tuple(int(round(c)) for c in lo[1]))
            else:
                t = (i - lo[0]) / (hi[0] - lo[0])
                lut.append(tuple(int(round(lo[1][j] + (hi[1][j] - lo[1][j]) * t)) for j in range(3)))
        self.lut = lut
        self.src = a

    def apply(self, im, crop):
        k, ox, oy = crop
        tf = (1 / k, 0, ox, 0, 1 / k, oy)
        self.check(im, tf)
        m = self.mask.transform(im.size, Image.AFFINE, tf, Image.BILINEAR)
        im = im.convert("RGBA")
        out = im.copy()
        px, mp = out.load(), m.load()
        for y in range(im.height):
            for x in range(im.width):
                w = mp[x, y] / 255
                if w:
                    r, g, b, a = px[x, y]
                    c = self.lut[luminance((r, g, b))]
                    px[x, y] = (round(r + (c[0] - r) * w), round(g + (c[1] - g) * w), round(b + (c[2] - b) * w), a)
        return out

    def check(self, im, tf):
        t = im.convert("L")
        a = im.getchannel("A").point(lambda v: 255 if v > 200 else 0)
        s = self.src.convert("L").transform(im.size, Image.AFFINE, tf, Image.BILINEAR)
        ss, tt = ImageStat.Stat(s, a), ImageStat.Stat(t, a)
        g = tt.stddev[0] / (ss.stddev[0] or 1)
        s = s.point(lambda v: max(0, min(255, int((v - ss.mean[0]) * g + tt.mean[0]))))
        err = ImageStat.Stat(ImageChops.difference(s, t), a).mean[0]
        if err > CROP_TOLERANCE:
            raise SystemExit("a crop no longer lines up with %s (difference %.1f): update CROPS or add a -Dark "
                             "version of the picture" % (SELECT, err))


def alternate(art, name, dark):
    stem, ext = os.path.splitext(name)
    own = os.path.join(art, stem + "-Dark" + ext)
    if os.path.exists(own):
        return Image.open(own).convert("RGBA")
    return dark.apply(Image.open(os.path.join(art, name)), CROPS[name])


def load(art, name):
    return Image.open(os.path.join(art, name)).convert("RGBA")


# pictures
def thumbs(art):
    return [load(art, n) for n in TILES]


def hud_icons(art):
    dark = DarkRecolour(art)
    icon, rage = load(art, ICON), load(art, ICON_RAGE)
    return {"plr_doctordoom": ("plr_johnnyohm", icon),
            "plr_doctordoom_rage": ("plr_johnnyohm_rage", rage),
            "plr_altdoctordoom": ("plr_altjohnnyohm", alternate(art, ICON, dark)),
            "plr_altdoctordoom_rage": ("plr_altjohnnyohm_rage", rage)}


def build(big, art, new_id, out=None):
    P = "Apt/clash/"
    res = {}
    dark = DarkRecolour(art)

    src = "c%d_p0" % PORTRAIT_SRC
    files = dict(nbig.load(read_entry(big, P + "portraits/" + src + ".big")))
    recs = geo_records(files[src + ".geo"])
    offsets = shape_offsets(files[src + ".apt"], files[src + ".const"])

    def screen_box(pieces):
        s, X0, Y0, W, H = canvas_of(pieces)
        ox, oy = offsets[pieces[0]["rid"]]
        return s, X0 + ox, Y0 + oy, X0 + ox + W / s, Y0 + oy + H / s
    s_r, X0_r, Y0_r, _, _ = screen_box(next(r for r in recs if any(p["tex"] == "6" for p in r)))
    at = (X0_r + SELECT_AT[0] / s_r, Y0_r + SELECT_AT[1] / s_r)
    per_px = SELECT_SCALE / s_r
    normal, alt = load(art, SELECT), load(art, SELECT_ALT)

    def select_art(i, W, H):
        texs = [p["tex"] for p in recs[i]]
        s, X0, Y0, X1, _ = screen_box(recs[i])
        pic = alt if "10" in texs else normal
        x = min(at[0], X1 - pic.getbbox()[2] * per_px - 2)
        pic = pic.resize((int(round(pic.width * per_px * s)), int(round(pic.height * per_px * s))), Image.LANCZOS)
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        canvas.paste(pic, (int(round((x - X0) * s)), int(round((at[1] - Y0) * s))))
        if "6" in texs:
            return glow(canvas, (60, 255, 90, 110), 6)
        if "10" in texs:
            return glow(canvas, (120, 200, 255, 90), 6)
        return canvas
    files[src + ".gsh"] = redraw(files[src + ".gsh"], recs, select_art)
    name = "c%d_p0" % new_id
    res[P + "portraits/" + name + ".big"] = nbig.save(rename_archive(list(files.items()), src, name))

    for suffix in ("", "_alt"):
        src = "cvs%d%s" % (PORTRAIT_SRC, suffix)
        files = dict(nbig.load(read_entry(big, P + "portraits/" + src + ".big")))
        gsh = files[src + ".gsh"]
        strips = [alternate(art, n, dark) if suffix else load(art, n) for n in STRIPS]
        for n, off, _ in gshtool.entries(gsh):
            i = gshtool.image_info(gsh, off)
            pic = next((p for p in strips if p.size == (i["w"], i["h"])), None)
            if pic is None:
                raise SystemExit("%s image %s is %dx%d: no strip of that size" % (src, n, i["w"], i["h"]))
            gsh = gshtool.replace(gsh, n, pic)
        files[src + ".gsh"] = gsh
        name = "cvs%d%s" % (new_id, suffix)
        res[P + "portraits/" + name + ".big"] = nbig.save(rename_archive(list(files.items()), src, name))

    if out:
        os.makedirs(out, exist_ok=True)
        for k, v in res.items():
            base = k.rsplit("/", 1)[-1][:-4]
            for n, b in nbig.load(v):
                if n.endswith(".gsh"):
                    for nm, off, _ in gshtool.entries(b):
                        gshtool.decode(b, off).save(os.path.join(out, "%s_%s.png" % (base, nm)))
        for nm, (_, im) in hud_icons(art).items():
            im.save(os.path.join(out, "%s.png" % nm))
    return res


if __name__ == "__main__":
    res = build(sys.argv[1], sys.argv[2], 18, sys.argv[3])
    for k, v in res.items():
        open(os.path.join(sys.argv[3], k.rsplit("/", 1)[-1]), "wb").write(v)
        print(k, len(v))
