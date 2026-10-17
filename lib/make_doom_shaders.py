#!/usr/bin/env python3

import sys

from make_doom_model import COSTUMES, materials

BLOCK = """
%s
{
\tshader charlight
\tspecularity\t3.0
\tshininess\t1.0
\tintensity\t1.0
\ttexture %s
\ttexture2 ge_charlight
}
"""


def main(src, dst):
    d = open(src, "rb").read()
    if b"\nDoctorDoom\r\n" in d:
        raise SystemExit("already patched")
    if not d.endswith(b"\r\n"):
        d += b"\r\n"
    blocks = "".join(BLOCK % (m, m) for costume in COSTUMES for m in materials(costume))
    open(dst, "wb").write(d + blocks.replace("\n", "\r\n").encode())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
