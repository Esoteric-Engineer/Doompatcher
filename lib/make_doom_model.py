#!/usr/bin/env python3

import math
import os
import struct
import sys

import bigtool
import gltf
import gxtex
import ngmtool as N
from PIL import Image

NAME = "DoctorDoom"
SRC = "Bundles/johnnyohm"
MAX_PALETTE = 20

COSTUMES = {"": ("17401_diffuse.png", "17402_diffuse.png"),
            "_alt": ("17401_diffuse_dark.png", "17402_diffuse_dark.png")}
TEX_SIZE = (512, 128)

GLTF_MAT = {"17401": 0, "17402": 1}
MAT_SUFFIX = ("", "_cloth")
CAPE_MAT = 1


def names(costume):
    return {"MODEL": NAME + costume + ".nod", "PHYSMODEL": NAME + costume + "_phys.nod",
            "SHADOWMODEL": NAME + costume + "_shadow.nod"}


def materials(costume):
    return [NAME + costume + m for m in MAT_SUFFIX]


JO = {"pelvis": 1, "spine1": 2, "chest": 3, "neck": 4, "head": 5}
JO_SIDE = {"r": {"clav": 22, "arm": 23, "arm2": 24, "elbow": 25, "fore2": 26, "hand": 27,
                 "front": (28, 29, 30), "back": (31, 32, 33), "thumb": (34, 35),
                 "thigh": 65, "knee": 66, "ankle": 67, "toe": 68},
           "l": {"clav": 42, "arm": 43, "arm2": 44, "elbow": 45, "fore2": 46, "hand": 47,
                 "front": (48, 49, 50), "back": (51, 52, 53), "thumb": (54, 55),
                 "thigh": 61, "knee": 62, "ankle": 63, "toe": 64}}
TORSO = {"Bip01 Pelvis": "pelvis", "Bip01 Spine": "spine1", "Bip01 Spine1": "spine1", "Bip01 Spine2": "chest",
         "Bip01 Neck": "neck", "Bip01 Head": "head"}
SPLITS = {"UpperArm": ("arm", "arm2", "Forearm", 0.25, 0.55), "Forearm": ("elbow", "fore2", "Hand", 0.45, 0.8)}


def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def length(a): return math.sqrt(dot(a, a))
def unit(a): return mul(a, 1.0 / (length(a) or 1.0))
def mat_apply(m, v): return tuple(dot(m[i], v) for i in range(3))
def mat_mul3(a, b): return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
IDENT = [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]


def rot_between(a, b):
    a, b = unit(a), unit(b)
    v, c = cross(a, b), dot(a, b)
    if c < -0.999999:
        raise ValueError("opposite directions")
    k = 1.0 / (1.0 + c)
    vx = [[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]]
    vx2 = mat_mul3(vx, vx)
    return [[IDENT[i][j] + vx[i][j] + vx2[i][j] * k for j in range(3)] for i in range(3)]


def conv(v):
    return (-v[0], v[2], v[1])


class Bone:

    def __init__(self, P, Q, s, R=IDENT, axis=None, k=1.0):
        self.P, self.Q, self.s, self.R, self.axis, self.k = P, Q, s, R, axis, k

    def apply(self, v):
        d = mul(sub(v, self.P), self.s)
        if self.axis is not None and self.k != 1.0:
            d = add(d, mul(self.axis, (self.k - 1.0) * dot(d, self.axis)))
        return add(self.Q, mat_apply(self.R, d))


class Torso:

    def __init__(self, P_pelvis, Q_pelvis, s, z_shoulder, kz_up, kz_down):
        self.P, self.Q, self.s, self.zs, self.ku, self.kd = P_pelvis, Q_pelvis, s, z_shoulder, kz_up, kz_down
        self.R = IDENT

    def z(self, z):
        dz = z - self.P[2]
        if dz < 0:
            return self.kd * dz
        if z <= self.zs:
            return self.ku * dz
        return self.ku * (self.zs - self.P[2]) + (z - self.zs)

    def apply(self, v):
        s = self.s
        return (self.Q[0] + s * (v[0] - self.P[0]), self.Q[1] + s * (v[1] - self.P[1]), self.Q[2] + s * self.z(v[2]))


def read_entry(big, name):
    entries, *_ = bigtool.read_big_index(big)
    for e in entries:
        if e.name.lower() == name.lower():
            with open(big, "rb") as f:
                f.seek(e.offset)
                return f.read(e.size)
    raise SystemExit("no entry " + name)


def load_doom(path):
    g = gltf.GLB(path)
    j = g.j
    W = g.world()
    sk = j["skins"][0]
    ibm = [gltf.col_major(m) for m in g.accessor(sk["inverseBindMatrices"])]
    jm = [gltf.mat_mul(W[n], ibm[k]) for k, n in enumerate(sk["joints"])]
    base = [j["nodes"][n]["name"].rsplit("_", 1)[0] for n in sk["joints"]]
    joint_pos = {base[k]: conv(tuple(W[n][r][3] for r in range(3))) for k, n in enumerate(sk["joints"])}
    prims = []
    for mesh in j["meshes"]:
        for prim in mesh["primitives"]:
            mat = j["materials"][prim["material"]]["name"]
            a = prim["attributes"]
            P, Nn, UV = g.accessor(a["POSITION"]), g.accessor(a["NORMAL"]), g.accessor(a["TEXCOORD_0"])
            J, Wt = g.accessor(a["JOINTS_0"]), g.accessor(a["WEIGHTS_0"])
            I = g.accessor(prim["indices"])
            pos, nrm, skin = [], [], []
            for p, n, jj, ww in zip(P, Nn, J, Wt):
                px, nx = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
                sw = [(base[ji], w) for ji, w in zip(jj, ww) if w > 0]
                tot = sum(w for _, w in sw)
                for ji, w in zip(jj, ww):
                    if w > 0:
                        px = add(px, mul(gltf.mat_vec(jm[ji], p), w / tot))
                        nx = add(nx, mul(gltf.mat_vec(jm[ji], n, 0.0), w / tot))
                pos.append(conv(px))
                nrm.append(unit(conv(nx)))
                skin.append([(b, w / tot) for b, w in sw])
            prims.append({"mat": GLTF_MAT[mat], "pos": pos, "nrm": nrm, "uv": UV, "skin": skin,
                          "tris": [tuple(I[k:k + 3]) for k in range(0, len(I), 3)]})
    return prims, joint_pos


def jo_positions(model):
    return [tuple(-x for x in b["t"][:3]) for b in model["bones"]]


def build_maps(D, J):
    maps, to_jo = {}, {}
    side = lambda s, b: "Bip01 %s %s" % (s.upper(), b)
    avg = lambda b: mul(add(D[side("l", b)], D[side("r", b)]), 0.5)
    S = (J[JO_SIDE["r"]["thigh"]][2] - J[JO_SIDE["r"]["ankle"]][2]) / (avg("Thigh")[2] - avg("Foot")[2])
    pelvis = D["Bip01 Pelvis"]
    z_sh = avg("UpperArm")[2]
    ankle_z = S * avg("Foot")[2]
    kz_up = (J[JO_SIDE["r"]["arm"]][2] - J[JO["pelvis"]][2]) / (S * (z_sh - pelvis[2]))
    kz_down = (J[JO["pelvis"]][2] - ankle_z) / (S * (pelvis[2] - avg("Foot")[2]))
    torso = Torso(pelvis, J[JO["pelvis"]], S, z_sh, kz_up, kz_down)
    for b, jb in TORSO.items():
        maps[b], to_jo[b] = torso, JO[jb]

    def seg(b, child_P, Q, Qc):
        d = sub(child_P, D[b])
        R = rot_between(d, sub(Qc, Q))
        maps[b] = Bone(D[b], Q, S, R, unit(d), length(sub(Qc, Q)) / (S * length(d)))
        return R

    for s in "rl":
        js = JO_SIDE[s]
        n = lambda b: side(s, b)
        # arm: clavicle, shoulder, elbow, wrist -> 22, 23, 25, 27 (or 42, 43, 45, 47)
        chain = [(n("Clavicle"), js["clav"]), (n("UpperArm"), js["arm"]), (n("Forearm"), js["elbow"]),
                 (n("Hand"), js["hand"])]
        for (b, jb), (c, jc) in zip(chain, chain[1:]):
            seg(b, D[c], J[jb], J[jc])
            to_jo[b] = jb
        # hand: points from the wrist to the knuckles
        hand = n("Hand")
        knuck = D[n("Finger1")]
        jo_knuck = mul(add(J[js["front"][0]], J[js["back"][0]]), 0.5)
        R_hand = seg(hand, knuck, J[js["hand"]], add(J[js["hand"]], mul(unit(sub(jo_knuck, J[js["hand"]])), S * length(sub(knuck, D[hand])))))
        to_jo[hand] = js["hand"]
        # fingers (mitten) and thumb
        f = js["front"]
        _fk(maps, to_jo, D, [n("Finger1"), n("Finger11")], maps[hand], R_hand,
            [sub(J[f[1]], J[f[0]]), sub(J[f[2]], J[f[1]])], f[:2], S)
        t = js["thumb"]
        _fk(maps, to_jo, D, [n("Finger0"), n("Finger01")], maps[hand], R_hand, [sub(J[t[1]], J[t[0]])] * 2, t, S)
        # leg: hip, knee, ankle
        hip, knee = J[js["thigh"]], J[js["knee"]]
        ankle = (J[js["ankle"]][0], J[js["ankle"]][1], ankle_z)
        seg(n("Thigh"), D[n("Calf")], hip, knee)
        seg(n("Calf"), D[n("Foot")], knee, ankle)
        to_jo[n("Thigh")], to_jo[n("Calf")] = js["thigh"], js["knee"]
        # foot and toes
        maps[n("Foot")] = Bone(D[n("Foot")], ankle, S)
        maps[n("Toe0")] = Bone(D[n("Toe0")], maps[n("Foot")].apply(D[n("Toe0")]), S)
        to_jo[n("Foot")], to_jo[n("Toe0")] = js["ankle"], js["toe"]

    def weights(b, v):
        part = b.rsplit(" ", 1)[-1]
        if part not in SPLITS:
            return [(to_jo[b], 1.0)]
        first, twist, child, t0, t1 = SPLITS[part]
        s = "r" if " R " in b else "l"
        d = sub(D[side(s, child)], D[b])
        t = dot(sub(v, D[b]), d) / dot(d, d)
        f = max(0.0, min(1.0, (t - t0) / (t1 - t0)))
        return [(JO_SIDE[s][first], 1.0 - f), (JO_SIDE[s][twist], f)]
    return maps, weights, S


def _fk(maps, to_jo, D, bones, parent_map, R_parent, dirs, jchain, S):
    R = R_parent
    for i, b in enumerate(bones):
        d = sub(D[bones[i + 1]], D[b]) if i + 1 < len(bones) else sub(D[b], D[bones[i - 1]])
        R = mat_mul3(rot_between(mat_apply(R, d), dirs[i]), R)
        maps[b] = Bone(D[b], parent_map.apply(D[b]), S, R)
        to_jo[b] = jchain[i]
        parent_map = maps[b]


class NormalIndex:

    def __init__(self, table, cells=8):
        self.t, self.c = table, cells
        self.grid = {}
        for i, n in enumerate(table):
            self.grid.setdefault(self._cell(n), []).append(i)

    def _cell(self, n):
        return tuple(int(math.floor((x + 1) * self.c / 2)) for x in n)

    def nearest(self, n):
        cx, cy, cz = self._cell(n)
        best, bi = -2, 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for i in self.grid.get((cx + dx, cy + dy, cz + dz), ()):
                        d = dot(n, self.t[i])
                        if d > best:
                            best, bi = d, i
        return bi


def top3(weights):
    acc = {}
    for b, w in weights:
        if w > 0:
            acc[b] = acc.get(b, 0) + w
    best = sorted(acc.items(), key=lambda x: -x[1])[:3]
    tot = sum(w for _, w in best)
    return [(b, w / tot) for b, w in best]


def build_render_model(jo_main, tris_by_mat, normals, costume):
    nidx = NormalIndex(normals)
    data, data_of = bytearray(), {}
    uvs, uv_of = [], {}
    nrm_of = {}
    maps, idx, parts = bytearray(), [], []
    nmap = 0
    allpos = []
    for mat in sorted(tris_by_mat):
        tris = tris_by_mat[mat]
        tris.sort(key=lambda t: sorted(b for v in t for b, _ in v[3]))
        groups, cur, cur_b = [], [], set()
        for t in tris:
            tb = {b for v in t for b, _ in v[3]}
            if len(cur_b | tb) > MAX_PALETTE:
                groups.append((cur, cur_b))
                cur, cur_b = [], set()
            cur.append(t)
            cur_b |= tb
        if cur:
            groups.append((cur, cur_b))
        for gtris, gbones in groups:
            local = {}
            pidx = []
            for t in gtris:
                for pos, n, uv, w in t:
                    w = sorted(w, key=lambda x: -x[1])
                    key = (pos, tuple(w))
                    if key not in data_of:
                        bones = [b for b, _ in w] + [w[0][0]] * (3 - len(w))
                        ws = [x for _, x in w] + [0.0] * (3 - len(w))
                        data_of[key] = len(data) // 28
                        data += struct.pack(">3f3f3BB", *pos, *ws, *bones, 0)
                        allpos.append(pos)
                    pi = data_of[key]
                    nk = (round(n[0], 4), round(n[1], 4), round(n[2], 4))
                    if nk not in nrm_of:
                        nrm_of[nk] = nidx.nearest(unit(n))
                    ni = nrm_of[nk]
                    u = max(-32768, min(32767, int(round(uv[0] * 512))))
                    vv = max(-32768, min(32767, int(round(uv[1] * 512))))
                    tk = ((u & 0xFFFF) << 16) | (vv & 0xFFFF)
                    if tk not in uv_of:
                        uv_of[tk] = len(uvs)
                        uvs.append(tk)
                    ti = uv_of[tk]
                    mk = (pi, ni, ti)
                    if mk not in local:
                        local[mk] = nmap + len(local)
                        maps += struct.pack(">3H", pi, ni, ti)
                    pidx.append(local[mk])
            idx += pidx
            parts.append({"mat": mat, "stream": 0, "n14": 0, "n16": len(pidx), "n18": len(local), "b3e": 0,
                          "b3f": 0, "b40": 3, "bones": sorted(gbones)})
            nmap += len(local)
    if nmap > 0xFFFF or len(data) // 28 > 0xFFFF or len(uvs) > 0xFFFF:
        raise SystemExit("too many vertices for 16-bit indices")
    lo = [min(p[i] for p in allpos) for i in range(3)]
    hi = [max(p[i] for p in allpos) for i in range(3)]
    m = dict(jo_main)
    mats = materials(costume)
    m.update(name=names(costume)["MODEL"], nmat=len(mats), npart=len(parts), materials=mats,
             bbox=(lo[0], lo[1], lo[2], 0.0, hi[0], hi[1], hi[2], 0.0), tab32=uvs, idx=idx, parts=parts,
             streams=[{"type": 2, "nmap": nmap, "map": bytes(maps), "n": len(data) // 28, "data": bytes(data)}])
    m["nstream"] = 1
    return m


def build_tpl(jo_tpl, textures, extra):
    ims = gxtex.tpl_images(jo_tpl)
    hdr0 = jo_tpl[ims[0]["hdr"]:ims[0]["hdr"] + 0x24]
    entries = []
    for name, im in textures:
        h = bytearray(hdr0)
        struct.pack_into(">HH", h, 0, im.size[1], im.size[0])
        entries.append((name, bytes(h), gxtex.encode_cmpr(im)))
    for name, tpl, i in extra:
        im = gxtex.tpl_images(tpl)[i]
        if im["fmt"] != gxtex.FMT_CMPR:
            raise SystemExit("only CMPR images are copied")
        entries.append((name, tpl[im["hdr"]:im["hdr"] + 0x24], tpl[im["off"]:im["off"] + gxtex.cmpr_size(im["w"], im["h"])]))
    n = len(entries)
    out = bytearray(struct.pack(">III", 0x0020AF30, n, 0xC))
    table = len(out)
    out += bytes(8 * n)
    hdrs = []
    for name, h, _ in entries:
        while len(out) % 0x20:
            out += b"\0"
        hdrs.append(len(out))
        out += h
    for i, (name, h, data) in enumerate(entries):
        while len(out) % 0x20:
            out += b"\0"
        struct.pack_into(">I", out, hdrs[i] + 8, len(out))
        struct.pack_into(">II", out, table + 8 * i, hdrs[i], 0)
        out += data
    ngt = b"".join(name.encode() + b"\r\n" for name, _, _ in entries)
    return bytes(out), ngt


def load_texture(path, size):
    im = Image.open(path).convert("RGB")
    if im.size != (size, size):
        im = im.resize((size, size), Image.LANCZOS)
    return im


def make(big, glb, texdir, out, preview=False):
    os.makedirs(out, exist_ok=True)
    normals = N.load_normals(read_entry(big, "Misc/NormalTable.ngn"))
    hdr, jo_models, _ = N.parse(read_entry(big, SRC + ".ngm"))
    jo_main, jo_phys, jo_shadow = jo_models
    J = jo_positions(jo_main)
    prims, D = load_doom(glb)
    maps, weights, S = build_maps(D, J)

    tris_by_mat = {}
    for p in prims:
        verts = []
        for pos, n, uv, sw in zip(p["pos"], p["nrm"], p["uv"], p["skin"]):
            q = (0.0, 0.0, 0.0)
            nn = (0.0, 0.0, 0.0)
            jw = []
            for b, w in sw:
                q = add(q, mul(maps[b].apply(pos), w))
                nn = add(nn, mul(mat_apply(maps[b].R, n), w))
                jw += [(jb, w * f) for jb, f in weights(b, pos)]
            verts.append((q, unit(nn), uv, top3(jw)))
        lst = tris_by_mat.setdefault(p["mat"], [])
        for a, b, c in p["tris"]:
            lst.append((verts[a], verts[b], verts[c]))
            if p["mat"] == CAPE_MAT:
                flip = lambda v: (v[0], mul(v[1], -1), v[2], v[3])
                lst.append((flip(verts[a]), flip(verts[c]), flip(verts[b])))

    jo_tpl = read_entry(big, SRC + ".tpl")
    jo_names = read_entry(big, SRC + ".ngt").decode().split()
    args = []
    for costume, files in COSTUMES.items():
        nm = names(costume)
        render = build_render_model(jo_main, {m: list(t) for m, t in tris_by_mat.items()}, normals, costume)
        phys = dict(jo_phys, name=nm["PHYSMODEL"])
        shadow = dict(jo_shadow, name=nm["SHADOWMODEL"])
        models = [render, phys, shadow]
        h = dict(hdr, pool=N.pool_size(models) + 52 * sum(m["npart"] for m in models) + 512)
        ngm = N.write(h, models)
        N.parse(ngm)
        texs = [load_texture(os.path.join(texdir, f), size) for f, size in zip(files, TEX_SIZE)]
        tpl, ngt = build_tpl(jo_tpl, list(zip(materials(costume), texs)),
                             [("ge_charlight", jo_tpl, jo_names.index("ge_charlight")),
                              ("GE_PAR_ElectricParticles", jo_tpl, jo_names.index("GE_PAR_ElectricParticles"))])
        bundle = "doctordoom" + costume
        for ext, d in (("ngm", ngm), ("ngt", ngt), ("tpl", tpl)):
            path = os.path.join(out, "%s.%s" % (bundle, ext))
            open(path, "wb").write(d)
            args += ["--add", "Bundles/%s.%s=%s" % (bundle, ext, path)]
        st = render["streams"][0]
        print("%s: %d parts, %d positions, %d vertices, %d triangles, %d UVs; .ngm %d bytes, .tpl %d bytes" % (
            bundle, render["npart"], st["n"], st["nmap"], len(render["idx"]) // 3, len(render["tab32"]), len(ngm), len(tpl)))
        if preview and not costume:
            _preview(render, jo_main, jo_tpl, texs, normals, out)
    print("scale %.3f" % S)
    open(os.path.join(out, "bundle_args.txt"), "w").write("\n".join(args) + "\n")


def _preview(render, jo_main, jo_tpl, texs, normals, out):
    import raster
    tris = []
    for i, p, s, tl in N.part_tris(render):
        for t in tl:
            vs = [N.vertex(render, s, k, normals) for k in t]
            tris.append(tuple(v[0] for v in vs) + tuple(v[1] for v in vs) + tuple(v[2] for v in vs) + (texs[p["mat"]],))
    jtris = []
    jtpl = gxtex.decode_cmpr(jo_tpl[gxtex.tpl_images(jo_tpl)[0]["off"]:], 256, 256).convert("RGB")
    for i, p, s, tl in N.part_tris(jo_main):
        for t in tl:
            vs = [N.vertex(jo_main, s, k, normals) for k in t]
            jtris.append(tuple(v[0] for v in vs) + tuple(v[1] for v in vs) + tuple(v[2] for v in vs) + (jtpl,))
    bbox = (-1.15, -0.02, 1.15, 2.1)
    for view in ("front", "right", "back"):
        vb = bbox if view in ("front", "back") else (-0.6, -0.02, 0.6, 2.1)
        raster.render(tris, view, 480, os.path.join(out, "preview_%s.png" % view), bbox=vb)
        raster.render(jtris, view, 480, os.path.join(out, "preview_jo_%s.png" % view), bbox=vb)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    make(a[0], a[1], a[2], a[3], "--preview" in sys.argv)
