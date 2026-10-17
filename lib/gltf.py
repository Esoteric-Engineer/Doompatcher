#!/usr/bin/env python3

import io
import json
import math
import struct

COMP = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
NORM = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def mat_vec(m, v, w=1.0):
    x, y, z = v
    return tuple(m[i][0] * x + m[i][1] * y + m[i][2] * z + m[i][3] * w for i in range(3))


def identity():
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def trs(t=(0, 0, 0), r=(0, 0, 0, 1), s=(1, 1, 1)):
    x, y, z, w = r
    m = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), t[0]],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), t[1]],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), t[2]],
         [0.0, 0.0, 0.0, 1.0]]
    for i in range(3):
        for j in range(3):
            m[i][j] *= s[j]
    return m


def col_major(v):
    return [[v[c * 4 + r] for c in range(4)] for r in range(4)]


def normalize(v):
    l = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / l for c in v)


class GLB:
    def __init__(self, path):
        d = open(path, "rb").read()
        magic, _ver, _len = struct.unpack_from("<4sII", d, 0)
        assert magic == b"glTF"
        o = 12
        self.bin = b""
        while o < len(d):
            n, t = struct.unpack_from("<II", d, o)
            chunk = d[o + 8:o + 8 + n]
            if t == 0x4E4F534A:
                self.j = json.loads(chunk)
            elif t == 0x004E4942:
                self.bin = chunk
            o += 8 + n
        self._world = None

    def view(self, i):
        bv = self.j["bufferViews"][i]
        o = bv.get("byteOffset", 0)
        return self.bin[o:o + bv["byteLength"]], bv.get("byteStride")

    def accessor(self, i):
        a = self.j["accessors"][i]
        nc = NCOMP[a["type"]]
        fmt = COMP[a["componentType"]]
        size = struct.calcsize("<" + fmt)
        data, stride = self.view(a["bufferView"])
        base = a.get("byteOffset", 0)
        stride = stride or size * nc
        out = []
        norm = a.get("normalized", False) and a["componentType"] in NORM
        for k in range(a["count"]):
            v = struct.unpack_from("<%d%s" % (nc, fmt), data, base + k * stride)
            if norm:
                v = tuple(x / NORM[a["componentType"]] for x in v)
            out.append(v if nc > 1 else v[0])
        return out

    def local(self, n):
        node = self.j["nodes"][n]
        if "matrix" in node:
            return col_major(node["matrix"])
        return trs(node.get("translation", (0, 0, 0)), node.get("rotation", (0, 0, 0, 1)), node.get("scale", (1, 1, 1)))

    def world(self):
        if self._world is None:
            nodes = self.j["nodes"]
            parent = {}
            for i, n in enumerate(nodes):
                for c in n.get("children", []):
                    parent[c] = i
            self.parent = parent
            w = {}

            def get(i):
                if i not in w:
                    w[i] = mat_mul(get(parent[i]), self.local(i)) if i in parent else self.local(i)
                return w[i]
            for i in range(len(nodes)):
                get(i)
            self._world = w
        return self._world

    def image_bytes(self, i):
        im = self.j["images"][i]
        data, _ = self.view(im["bufferView"])
        return data

    def image(self, i):
        from PIL import Image
        return Image.open(io.BytesIO(self.image_bytes(i)))

    def material_texture(self, mat):
        pbr = self.j["materials"][mat].get("pbrMetallicRoughness", {})
        t = pbr.get("baseColorTexture")
        if t is None:
            return None
        return self.j["textures"][t["index"]].get("source")
