#!/usr/bin/env python3
"""Doompatcher: adds Doctor Doom to Marvel Nemesis: Rise of the Imperfects (GameCube, USA, GVLE69).

  python3 doompatcher.py GAME.iso|GAME.ciso [OUT.iso] [--keep-work]
"""
import hashlib
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import bigtool
import disc
import dolpatch
import make_doom_model
import make_doom_shaders
import make_doom_templates
import patch_ui

ASSETS = os.path.join(HERE, "assets")
GAME_ID = "GVLE69"
BH_SHA1 = "32836d400df4b4e9f95b9eb790ebb142ab5c28bb"
BIG_SHA1 = "9519b437d8677dbfb3dea7757aae3511bbfabc71"


def step(msg):
    print("\n== " + msg, flush=True)


def read_args(path):
    lines = open(path).read().split()
    sets, adds = [], []
    for kind, spec in zip(lines[::2], lines[1::2]):
        (sets if kind == "--set" else adds).append(tuple(spec.split("=", 1)))
    return sets, adds


def extract_checked(d, name, out, sha1):
    e = d.file(name)
    h = hashlib.sha1()
    with open(out, "wb") as f:
        pos, left = e.offset, e.size
        while left:
            chunk = d.img.read(pos, min(left, 1 << 22))
            h.update(chunk)
            f.write(chunk)
            pos += len(chunk)
            left -= len(chunk)
    if h.hexdigest() != sha1:
        raise SystemExit("%s is not the original GVLE69 one (already patched, or another version)" % name)


def main(argv):
    keep = "--keep-work" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit(__doc__)
    src = args[0]
    out = args[1] if len(args) > 1 else os.path.splitext(src)[0] + " (Doctor Doom).iso"
    if os.path.abspath(out) == os.path.abspath(src):
        raise SystemExit("the output must be a new file")
    t0 = time.time()

    step("Reading " + src)
    d = disc.Disc(src)
    if d.game_id != GAME_ID or d.revision != 0:
        raise SystemExit("this is %s rev %d; Doompatcher needs %s rev 0 (USA)" % (d.game_id, d.revision, GAME_ID))
    dol = dolpatch.patch(d.dol)

    work = tempfile.mkdtemp(prefix="doompatcher-", dir=os.path.dirname(os.path.abspath(out)))
    try:
        big, bh = os.path.join(work, "CLASH.BIG"), os.path.join(work, "CLASH.BH")
        extract_checked(d, "CLASH.BH", bh, BH_SHA1)
        print("extracting CLASH.BIG (1.3 GB)...", flush=True)
        extract_checked(d, "CLASH.BIG", big, BIG_SHA1)

        step("Building Doom's model bundles")
        make_doom_model.make(big, os.path.join(ASSETS, "doom_mua.glb"), os.path.join(ASSETS, "model"),
                             os.path.join(work, "doom"))
        sets, adds = read_args(os.path.join(work, "doom", "bundle_args.txt"))

        step("Templates and materials")
        for name, fn in (("Misc/Global.not", lambda a, b: make_doom_templates.main([None, a, b])),
                         ("Materials/Shaders/shaders.nsa", make_doom_shaders.main)):
            orig = os.path.join(work, name.rsplit("/", 1)[1])
            bigtool.cmd_get(big, name, orig + ".orig")
            fn(orig + ".orig", orig)
            sets.append((name, orig))

        step("Select screen, portraits and HUD")
        patch_ui.main(big, os.path.join(work, "ui"), ASSETS)
        s, a = read_args(os.path.join(work, "ui", "repack_args.txt"))
        sets += s
        adds = a + adds

        step("Writing " + out)
        plan, index, total, bh_out = bigtool.plan_repack(big, bh, sets, adds)
        size = disc.write_iso(out, d, dol, {
            "CLASH.BH": bh_out,
            "CLASH.BIG": lambda f: bigtool.write_big(big, plan, index, total, f),
        })
    except BaseException:
        if os.path.exists(out):
            os.remove(out)
        raise
    finally:
        if keep:
            print("work files kept in " + work)
        else:
            shutil.rmtree(work, ignore_errors=True)
    print("\nDone in %.0f s: %s (%d bytes)" % (time.time() - t0, out, size))
    print("In VERSUS, press DOWN twice from the first tile on the character select screen to reach Doom.")


if __name__ == "__main__":
    main(sys.argv)
