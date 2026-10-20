#!/usr/bin/env python3
"""Patch the APK without decoding all 48 dexes.

The full path (`apply_all.py`) decodes ~104k files and, cold, re-assembles all 48
dexes - about 11 minutes, and the assembly step is memory-hungry enough to kill a
JVM on a 16 GB machine.

This path only ever touches the dexes the patches actually modify (9 of 48, ~31% of
dex bytes):

    1. build a tiny APK holding just those dexes + the native lib to patch
    2. apktool d -r / patch / apktool b   -> only 9 dexes are ever assembled
    3. splice the rebuilt dexes back into the ORIGINAL apk, byte-for-byte identical
       everywhere else
    4. zipalign + apksigner

No smali/baksmali jars needed - apktool stays the only toolchain dependency.

    python patch_apk.py --apk com.huawei.health.apk --keystore my.keystore \
                        --ks-pass pass:secret --out hh_signed.apk
"""

import argparse
import os
import re
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from apply_all import (  # noqa: E402  (shared gate + toolchain plumbing)
    PATCHES,
    build_tools_dir,
    die,
    preflight,
    run,
    sha256,
)

NATIVE = "lib/arm64-v8a/libwhiteBoxJniLib.so"


def dex_extensions():
    """Derive which dexes the patch scripts touch, straight from the scripts."""
    roots = set()
    for name in PATCHES:
        p = os.path.join(HERE, "patches", name)
        if not os.path.isfile(p):
            die("missing patch script: %s" % p)
        with open(p, encoding="utf-8") as f:
            roots.update(re.findall(r"(smali(?:_classes\d+)?)[\\/]", f.read()))

    mapping = {}
    for r in sorted(roots):
        mapping[r] = "classes.dex" if r == "smali" else r.replace("smali_", "") + ".dex"
    return mapping


def build_mini(src_apk, mini, dex_names, want_native):
    """Subset APK: manifest + arsc + touched dexes + native lib."""
    written = []
    with zipfile.ZipFile(src_apk) as zin:
        names = {i.filename: i for i in zin.infolist()}
        want = ["AndroidManifest.xml", "resources.arsc"] + list(dex_names)
        if want_native:
            want.append(NATIVE)

        missing = [w for w in want if w not in names]
        if missing:
            die("APK is missing expected entries: %s" % ", ".join(missing))

        with zipfile.ZipFile(mini, "w", zipfile.ZIP_DEFLATED) as zout:
            for w in want:
                item = names[w]
                info = zipfile.ZipInfo(w, date_time=item.date_time)
                info.compress_type = item.compress_type
                zout.writestr(info, zin.read(w))
                written.append(w)
    return written


def splice(base_apk, patched_mini, out_apk, dex_names, want_native):
    """Copy base_apk, replacing only the rebuilt entries. Everything else untouched."""
    replace = set(dex_names)
    if want_native:
        replace.add(NATIVE)

    with zipfile.ZipFile(patched_mini) as src:
        fresh = {n: src.read(n) for n in replace if n in src.namelist()}
    missing = replace - set(fresh)
    if missing:
        die("mini build did not contain: %s" % ", ".join(sorted(missing)))

    dropped = 0
    with (
        zipfile.ZipFile(base_apk) as zin,
        zipfile.ZipFile(out_apk, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout,
    ):
        for item in zin.infolist():
            fn = item.filename
            if fn.startswith("META-INF/") and fn.upper().endswith(
                (".SF", ".RSA", ".DSA", ".EC")
            ):
                dropped += 1
                continue
            data = fresh.get(fn)
            if data is None:
                data = zin.read(fn)
            info = zipfile.ZipInfo(fn, date_time=item.date_time)
            info.compress_type = (
                item.compress_type
            )  # arsc stays STORED, .so stays DEFLATED
            info.external_attr = item.external_attr
            info.internal_attr = item.internal_attr
            info.create_system = item.create_system
            zout.writestr(info, data, compresslevel=9)

    return sorted(fresh), dropped


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--apk", required=True, help="original, unmodified APK")
    ap.add_argument("--out", default="hh_signed.apk")
    ap.add_argument("--work", default="_mini", help="scratch dir (default: _mini)")
    ap.add_argument("--keystore")
    ap.add_argument("--ks-alias", default="hh")
    ap.add_argument("--ks-pass")
    ap.add_argument("--key-pass")
    ap.add_argument("--force", action="store_true", help="skip the versionCode gate")
    ap.add_argument("--keep", action="store_true", help="keep the scratch dir")
    args = ap.parse_args()

    bt = build_tools_dir()
    aapt2 = (
        os.path.join(bt, "aapt2" + (".exe" if os.name == "nt" else ""))
        if bt
        else "aapt2"
    )

    preflight(args.apk, aapt2, args.force)

    mapping = dex_extensions()
    dex_names = sorted(mapping.values())
    want_native = any(n.startswith("01_") for n in PATCHES)
    print("\ndexes to rebuild (%d): %s" % (len(dex_names), ", ".join(dex_names)))

    if os.path.isdir(args.work):
        shutil.rmtree(args.work)
    os.makedirs(args.work)

    mini = os.path.join(args.work, "mini.apk")
    print(
        "\n=== build mini APK (manifest + arsc + %d dexes%s) ==="
        % (len(dex_names), " + .so" if want_native else "")
    )
    written = build_mini(args.apk, mini, dex_names, want_native)
    print(
        "  %d entries, %.1f MB" % (len(written), os.path.getsize(mini) / (1024 * 1024))
    )

    decode_dir = os.path.join(args.work, "decoded")
    apktool = os.environ.get("APKTOOL") or "apktool"
    print("\n=== decode mini (-r) ===")
    run([apktool, "d", "-r", mini, "-o", decode_dir])

    print("\n=== patches ===")
    for name in PATCHES:
        print("\n--- %s ---" % name)
        run([sys.executable, os.path.join(HERE, "patches", name), decode_dir])

    patched_mini = os.path.join(args.work, "mini_patched.apk")
    print("\n=== build mini ===")
    run([apktool, "b", decode_dir, "-o", patched_mini])

    print("\n=== splice into original ===")
    spliced = os.path.join(args.work, "spliced.apk")
    replaced, dropped = splice(args.apk, patched_mini, spliced, dex_names, want_native)
    print(
        "  replaced %d entries, dropped %d stale signature files"
        % (len(replaced), dropped)
    )

    if not args.keystore:
        shutil.copy2(spliced, "unsigned.apk")
        print("\nno --keystore: unsigned build at unsigned.apk")
        return

    if not bt:
        die("could not locate build-tools; set BUILD_TOOLS")

    print("\n=== align + sign ===")
    aligned = os.path.join(args.work, "aligned.apk")
    run(
        [
            os.path.join(bt, "zipalign" + (".exe" if os.name == "nt" else "")),
            "-p",
            "-f",
            "4",
            spliced,
            aligned,
        ]
    )

    signer = os.path.join(bt, "apksigner" + (".bat" if os.name == "nt" else ""))
    if not os.path.exists(signer):
        signer = os.path.join(bt, "apksigner")
    cmd = [signer, "sign", "--ks", args.keystore, "--ks-key-alias", args.ks_alias]
    if args.ks_pass:
        cmd += ["--ks-pass", args.ks_pass]
    if args.key_pass or args.ks_pass:
        cmd += ["--key-pass", args.key_pass or args.ks_pass]
    cmd += ["--out", args.out, aligned]
    run(cmd)

    print("\n=== done ===")
    print(
        "signed : %s (%.1f MB)" % (args.out, os.path.getsize(args.out) / (1024 * 1024))
    )
    print("sha256 : %s" % sha256(args.out))

    if not args.keep:
        shutil.rmtree(args.work, ignore_errors=True)


if __name__ == "__main__":
    main()
