import os, sys
def _root():
    """Work dir (the apktool decode). argv[1] or $HH_ROOT, default ./hh_decoded."""
    return os.environ.get("HH_ROOT") or (sys.argv[1] if len(sys.argv) > 1 else "hh_decoded")

import io

BASE = _root()

# kind: "void"  -> insert `return-void`
#       "true"  -> insert `const/4 v0, 0x1` + `return v0`  (for ContentProvider.onCreate()Z)
TARGETS = [
    # ---- DFX: crash/ANR/block/thread/memory monitors, started at app create ----
    (r"smali\health\compact\a\DfxMonitorCenter.smali", "a()V", "void"),
    (r"smali\health\compact\a\DfxMonitorCenter.smali", "b(Ljava/lang/Class;)V", "void"),
    (r"smali\health\compact\a\DfxMonitorCenter.smali", "c()V", "void"),
    (r"smali\health\compact\a\DfxMonitorCenter.smali", "d()V", "void"),
    (r"smali\health\compact\a\DfxMonitorCenter.smali", "e()V", "void"),
    # ---- Ads SDK: manifest-declared ContentProviders are instantiated at app start.
    # Keep the classes (the manifest still references them) but make onCreate a no-op
    # that reports success, so the ad SDK never initialises.
    (
        r"smali_classes12\com\huawei\openalliance\ad\download\DownloadFileProvider.smali",
        "onCreate()Z",
        "true",
    ),
    (
        r"smali_classes42\com\huawei\openalliance\ad\provider\PPSECProvider.smali",
        "onCreate()Z",
        "true",
    ),
    # ---- AGC: stop remote-config and A/B-test registration callbacks.
    # getServices() is deliberately left intact so AGC service lookup cannot NPE.
    (
        r"smali_classes23\com\huawei\agconnect\remoteconfig\ConfigRegistrar.smali",
        "initialize(Landroid/content/Context;)V",
        "void",
    ),
    (
        r"smali_classes23\com\huawei\agconnect\abtest\ABTestRegistrar.smali",
        "initialize(Landroid/content/Context;)V",
        "void",
    ),
]

report = []
for rel, sig, kind in TARGETS:
    path = os.path.join(BASE, rel)
    if not os.path.exists(path):
        report.append(("MISSING FILE", rel, sig))
        continue

    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        lines = fh.readlines()
    nl = "\r\n" if any(l.endswith("\r\n") for l in lines) else "\n"

    start = None
    for k, l in enumerate(lines):
        if l.startswith(".method") and l.rstrip("\r\n").endswith(sig):
            start = k
            break
    if start is None:
        report.append(("METHOD NOT FOUND", rel, sig))
        continue

    loc = None
    for k in range(start + 1, len(lines)):
        if lines[k].startswith(".end method"):
            break
        if lines[k].strip().startswith(".locals"):
            loc = k
            break
    if loc is None:
        report.append(("NO .locals", rel, sig))
        continue

    if kind == "void":
        body = [nl, "    return-void" + nl]
    else:
        # ensure at least one local register exists for v0
        try:
            n = int(lines[loc].strip().split()[1])
        except Exception:
            n = 1
        if n < 1:
            indent = lines[loc][: len(lines[loc]) - len(lines[loc].lstrip())]
            lines[loc] = indent + ".locals 1" + nl
        body = [nl, "    const/4 v0, 0x1" + nl, nl, "    return v0" + nl]

    lines[loc + 1 : loc + 1] = body

    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.writelines(lines)
    report.append(("OK", rel, sig))

for status, rel, sig in report:
    print("%-16s %-70s %s" % (status, rel, sig))
print("")
print("applied: %d / %d" % (sum(1 for r in report if r[0] == "OK"), len(TARGETS)))
