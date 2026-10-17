#!/usr/bin/env python3

import sys

import nottool as N
from make_doom_model import names

AURA = (0x28, 0x14, 0x30)


def clone(src, new_name, parent=None):
    t = N.Template(N.name32(new_name), list(src.props), b"\0")
    if parent:
        t.set(0x00, N.v_str(parent))
    return t


def prop(t, pid):
    return next(v for i, v in t.props if i == pid)


def main(argv):
    src, dst = argv[1], argv[2]
    ts = N.parse(open(src, "rb").read())
    by = {t.name.lower(): t for t in ts}
    for n in ("act_doctordoom", "plr_doctordoom", "plr_altdoctordoom"):
        if n in by:
            raise SystemExit("%s already present" % n)

    jo, jo_alt = by["act_johnnyohm"], by["plr_altjohnnyohm"]
    act = clone(jo, "act_DoctorDoom")
    plr = clone(by["plr_johnnyohm"], "plr_DoctorDoom", "act_DoctorDoom")
    alt = clone(jo_alt, "plr_altDoctorDoom", "act_DoctorDoom")
    for t, costume in ((act, ""), (alt, "_alt")):
        nm = names(costume)
        for pid, key in ((0x0A, "MODEL"), (0x75, "SHADOWMODEL"), (0x0F, "PHYSMODEL")):
            t.set(pid, N.v_str(nm[key]))
    for pid in AURA:
        plr.set(pid, prop(jo_alt, pid))
        alt.set(pid, prop(jo, pid))

    ts += [act, plr, alt]
    open(dst, "wb").write(N.build(ts))
    print("wrote %s: %d templates" % (dst, len(ts)))


if __name__ == "__main__":
    main(sys.argv)
