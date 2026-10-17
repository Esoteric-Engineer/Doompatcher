import hashlib

ORIGINAL_SHA1 = "8e3cc563c300b7730802f69ade112bba1f4c6be5"

EDITS = [
    # clashCharSelect_GetCharList: loop bound 18 -> 19 (cmpwi r0, 0x12 -> 0x13)
    (0x1007DC, "2c000012", "2c000013"),
    # Control_SetSelectInfo: cmpwi / li 0x12 -> 0x13 (unclamp from 18 to 19)
    (0x101758, "2c000012", "2c000013"),
    (0x101760, "38000012", "38000013"),
    (0x101788, "2c000012", "2c000013"),
    (0x101790, "38000012", "38000013"),
    # replace record 19 with "plr_doctordoom", "DOCTOR DOOM", stats 7/4/3/6/5/4
    (0x4C7AC4, "7468696e6700000000000000", "646f63746f72646f6f6d0000"),
    (0x4C7AE0, "7e6b545f5448494e47000000", "444f43544f5220444f4f4d00"),
    (0x4C7B00, "0206020601050000", "0704030605040000"),
    # replace alt-costume: "plr_altDoctordoom"
    (0x4C80B4, "616c745468696e670000000000000000", "616c74446f63746f72646f6f6d000000"),
    (0x4C80D0, "7e6b545f5448494e47000000", "444f43544f5220444f4f4d00"),
    (0x4C80F0, "0206020601050000", "0704030605040000"),
    # select-screen entry 19
    (0x4C8148, "00000000", "00000013"),
]


def patch(dol):
    if hashlib.sha1(dol).hexdigest() != ORIGINAL_SHA1:
        raise SystemExit("main.dol is not the original GVLE69 one (already patched, or another version)")
    out = bytearray(dol)
    for off, old, new in EDITS:
        old, new = bytes.fromhex(old), bytes.fromhex(new)
        assert out[off:off + len(old)] == old and len(old) == len(new), hex(off)
        out[off:off + len(new)] = new
    return bytes(out)
