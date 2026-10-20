#!/usr/bin/env python3
"""One command: decode -> apply patches 00..08 -> build -> zipalign -> sign.

    python apply_all.py --apk com.huawei.health.2609241423.apk \
                        --keystore my.keystore --ks-pass pass:secret

The patches are build-specific. They depend on Huawei's obfuscation mapping, which is
fixed per versionCode, so the base APK is verified before anything is touched.

Requires on PATH (or via env): apktool, aapt2, zipalign, apksigner.
  APKTOOL       - path to apktool (bat/cmd/wrapper ok; stdin is closed for you)
  BUILD_TOOLS   - path to an Android build-tools directory (supplies aapt2/zipalign/apksigner)
  ANDROID_HOME  - fallback; the newest build-tools under it is used
"""

import argparse
import glob
import hashlib
import os
import shutil
import subprocess
import sys

VERSION_CODE = "1700008300"
VERSION_NAME = "17.0.8.300"

# Byte-exact identity of the reference build this was developed against. Informational
# only: the same version pulled from a different channel (bundle split, mirror re-zip)
# will not match, and the patches still apply. versionCode is the real gate.
REF_SHA256 = "6E693FE6051B69FEFA68215CE52D1F3AE4A2A7C8E25D09B034C73C20BF6F42FD"

HERE = os.path.dirname(os.path.abspath(__file__))
PATCHES = [
    "00_securitychecker.py",
    "01_whitebox.py",
    "02_telemetry.py",
    "03_bloat.py",
    "04_login.py",
    "05_hatool.py",
    "06_hianalytics.py",
    "07_dfx.py",
    "08_loguploadworker.py",
]


def die(msg):
    print("\nERROR: " + msg)
    raise SystemExit(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def tool(name, env_var):
    v = os.environ.get(env_var)
    if v:
        return v
    return name


def build_tools_dir():
    d = os.environ.get("BUILD_TOOLS")
    if d:
        return d
    home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not home:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            home = os.path.join(local, "Android", "Sdk")
    if home:
        found = sorted(glob.glob(os.path.join(home, "build-tools", "*")))
        if found:
            return found[-1]
    return None


def run(cmd, cwd=None):
    cmd = [str(c) for c in cmd]
    exe = shutil.which(cmd[0]) or cmd[0]
    cmd[0] = exe
    # Windows cannot CreateProcess a .bat/.cmd directly (apktool ships as apktool.bat).
    if os.name == "nt" and exe.lower().endswith((".bat", ".cmd")):
        cmd = ["cmd", "/c"] + cmd
    shown = " ".join(str(c) for c in cmd)
    print("\n$ " + shown)
    # stdin=DEVNULL matters on Windows: apktool.bat ends in `pause`.
    r = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        die("command failed (%d): %s" % (r.returncode, shown))


def badging(apk, aapt2):
    out = subprocess.run(
        [aapt2, "dump", "badging", apk],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if out.returncode != 0:
        die("aapt2 dump badging failed; is this an APK?\n" + out.stderr.strip())
    return out.stdout


def preflight(apk, aapt2, force):
    if not os.path.isfile(apk):
        die("no such APK: %s" % apk)

    info = badging(apk, aapt2)
    vc = vn = None
    for line in info.splitlines():
        if line.startswith("package:"):
            for field in line.split():
                if field.startswith("versionCode="):
                    vc = field.split("=", 1)[1].strip("'")
                elif field.startswith("versionName="):
                    vn = field.split("=", 1)[1].strip("'")
            break

    print("base APK : %s" % apk)
    print("version  : versionCode=%s versionName=%s" % (vc, vn))

    digest = sha256(apk)
    print("sha256   : %s" % digest)
    if digest == REF_SHA256:
        print("           exact reference build - patches are known-good")
    else:
        print("           NOT the reference build (expected %s)" % REF_SHA256)
        print(
            "           same version is fine; per-patch verification will catch drift"
        )

    if vc != VERSION_CODE and not force:
        die(
            "versionCode is %s, expected %s.\n"
            "These patches depend on the obfuscation mapping of %s (%s).\n"
            "A different build will not have the same class/method layout.\n"
            "Use --force only if you know the layout matches."
            % (vc, VERSION_CODE, VERSION_CODE, VERSION_NAME)
        )


def check_not_already_patched(work):
    hits = []
    for root, _dirs, files in os.walk(work):
        if not os.path.basename(root).startswith("smali"):
            continue
        for fn in files:
            if not fn.endswith(".smali"):
                continue
            p = os.path.join(root, fn)
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    if "PATCH(hh" in f.read(4096):
                        hits.append(p)
            except OSError:
                pass
            if len(hits) > 3:
                return hits
    return hits


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--apk", required=True, help="original, unmodified Huawei Health APK"
    )
    ap.add_argument(
        "--work", default="hh_decoded", help="decode dir (default: hh_decoded)"
    )
    ap.add_argument("--out", default="hh_signed.apk", help="signed output APK")
    ap.add_argument("--keystore", help="keystore to sign with (skipped if omitted)")
    ap.add_argument("--ks-alias", default="hh")
    ap.add_argument("--ks-pass", help="e.g. pass:secret or file:path")
    ap.add_argument("--key-pass", help="defaults to --ks-pass")
    ap.add_argument("--force", action="store_true", help="skip the versionCode gate")
    ap.add_argument(
        "--skip-build", action="store_true", help="patches only, no build/sign"
    )
    ap.add_argument(
        "--preflight-only",
        action="store_true",
        help="check the base APK and exit (no decode)",
    )
    args = ap.parse_args()

    bt = build_tools_dir()
    aapt2 = (
        os.path.join(bt, "aapt2" + (".exe" if os.name == "nt" else ""))
        if bt
        else "aapt2"
    )
    if bt and not os.path.exists(aapt2):
        aapt2 = tool("aapt2", "AAPT2")

    preflight(args.apk, aapt2, args.force)

    if args.preflight_only:
        print("\npreflight OK (-r decode, patches 00..08, build, sign)")
        return

    if os.path.isdir(args.work) and os.listdir(args.work):
        hits = check_not_already_patched(args.work)
        if hits:
            die(
                "work dir already contains applied patches:\n  "
                + "\n  ".join(hits)
                + "\nDelete it or point --work somewhere else."
            )
        die(
            "work dir already exists and is not empty: %s\n"
            "Delete it or pass a fresh --work path." % args.work
        )

    apktool = tool("apktool", "APKTOOL")
    print("\n=== decode (-r: resources stay raw, manifest stays binary AXML) ===")
    run([apktool, "d", "-r", args.apk, "-o", args.work])

    print("\n=== patches ===")
    for name in PATCHES:
        path = os.path.join(HERE, "patches", name)
        if not os.path.isfile(path):
            die("missing patch script: %s" % path)
        print("\n--- %s ---" % name)
        run([sys.executable, path, os.path.abspath(args.work)])

    if args.skip_build:
        print("\npatches applied; --skip-build set, stopping here")
        return

    print("\n=== build ===")
    patched = os.path.join(HERE, "_patched.apk")
    run([apktool, "b", args.work, "-o", patched])

    if not args.keystore:
        print("\nNo --keystore given; unsigned APK left at %s" % patched)
        return

    if not bt:
        die("could not locate build-tools; set BUILD_TOOLS")

    print("\n=== align + sign ===")
    aligned = os.path.join(HERE, "_aligned.apk")
    run(
        [
            os.path.join(bt, "zipalign" + (".exe" if os.name == "nt" else "")),
            "-p",
            "-f",
            "4",
            patched,
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
        "signed  : %s (%d MB)" % (args.out, os.path.getsize(args.out) // (1024 * 1024))
    )
    print("sha256  : %s" % sha256(args.out))
    print(
        "\nThis build cannot update an official install, and MIUI/OnePlus-era package"
    )
    print("managers often reject in-place updates even between your own builds.")
    print("Expect to uninstall first and re-pair the watch.")


if __name__ == "__main__":
    main()
