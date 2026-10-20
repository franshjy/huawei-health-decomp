import os, sys
def _root():
    """Work dir (the apktool decode). argv[1] or $HH_ROOT, default ./hh_decoded."""
    return os.environ.get("HH_ROOT") or (sys.argv[1] if len(sys.argv) > 1 else "hh_decoded")


P = os.path.join(_root(), r"lib\arm64-v8a\libwhiteBoxJniLib.so")
BAK = P + ".orig"

data = bytearray(open(P, "rb").read())
open(BAK, "wb").write(data)  # pristine backup

# .text in this ELF has vaddr == file offset, so use vaddrs directly.
SRC = 0xF8E44  # success path: adrp x8,0x10d000 / mov w9,#1 / strb w9,[x8,#0x984]
DST = 0xF8854  # Java_..._executeAuth entry (same 4KB page => adrp stays valid)
RET = bytes.fromhex("c0035fd6")  # ret

seq = bytes(data[SRC : SRC + 12])
print("existing seq at 0x%x : %s" % (SRC, seq.hex()))
print("patch site before   : %s" % bytes(data[DST : DST + 16]).hex())
assert seq[:4] == bytes.fromhex("a80000b0"), "unexpected adrp encoding"
assert seq[4:8] == bytes.fromhex("29008052"), "unexpected mov encoding"
assert seq[8:12] == bytes.fromhex("09112639"), "unexpected strb encoding"
print("adrp sanity         : ok")

data[DST : DST + 12] = seq
data[DST + 12 : DST + 16] = RET
print("patch site after    : %s" % bytes(data[DST : DST + 16]).hex())

open(P, "wb").write(data)
print("patched ->", P)
print("backup  ->", BAK)
