#!/usr/bin/env python3
"""Replace one dex inside an existing APK, preserving every entry's compression method.

Why this exists: `apktool b` needs a JVM, and on a memory-constrained machine it dies
with `IOException: Insufficient system resources` or a native malloc failure
(`hs_err_pid`, `Chunk::new`). apktool assembles the dexes to `<work>/build/apk/` before
the zip stage, so if the build dies late you can splice the assembled dex into a known
APK yourself.

Compression must be preserved per entry: `resources.arsc` has to stay STORED for
targetSdk >= 30, while this APK's `.so` files are DEFLATED. A naive rewrite breaks
install or bloats the file.

    python repack_dex.py --base hh_patched4.apk \
                         --dex hh_decoded/build/apk/classes2.dex \
                         --entry classes2.dex --out hh_patched5.apk

Then: zipalign -p -f 4 in.apk out.apk && apksigner sign ...
"""

import argparse
import os
import sys
import zipfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--base", required=True, help="APK to take every non-dex entry from"
    )
    ap.add_argument("--dex", required=True, help="assembled dex file to splice in")
    ap.add_argument("--entry", required=True, help="zip entry name, e.g. classes2.dex")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.base):
        raise SystemExit("missing base APK: %s" % args.base)
    if not os.path.isfile(args.dex):
        raise SystemExit("missing dex: %s" % args.dex)
    if os.path.exists(args.out):
        os.remove(args.out)

    new_dex = open(args.dex, "rb").read()
    replaced = False

    with zipfile.ZipFile(args.base, "r") as zin:
        with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == args.entry:
                    data = new_dex
                    replaced = True
                elif item.filename.startswith(
                    "META-INF/"
                ) and item.filename.upper().endswith((".SF", ".RSA", ".DSA", ".EC")):
                    # drop stale signatures; the APK gets signed again afterwards
                    continue
                else:
                    data = zin.read(item.filename)

                info = zipfile.ZipInfo(item.filename, date_time=item.date_time)
                info.compress_type = item.compress_type  # preserve STORED vs DEFLATED
                info.external_attr = item.external_attr
                info.internal_attr = item.internal_attr
                info.create_system = item.create_system
                zout.writestr(info, data)

    if not replaced:
        os.remove(args.out)
        raise SystemExit("entry %r not found in %s" % (args.entry, args.base))

    print(
        "wrote %s (%.1f MB), replaced %s"
        % (args.out, os.path.getsize(args.out) / (1024 * 1024), args.entry)
    )


if __name__ == "__main__":
    sys.exit(main())
