import os, sys
def _root():
    """Work dir (the apktool decode). argv[1] or $HH_ROOT, default ./hh_decoded."""
    return os.environ.get("HH_ROOT") or (sys.argv[1] if len(sys.argv) > 1 else "hh_decoded")

import re, shutil

D = _root()

HA = os.path.join(
    D,
    r"smali_classes3\com\huawei\hms\framework\common\hianalytics\HianalyticsHelper.smali",
)
V0 = os.path.join(D, r"smali_classes3\com\huawei\hms\hatool\v0.smali")
U = os.path.join(D, r"smali_classes3\com\huawei\hms\hatool\u.smali")

# (path, method prototype substring, return mode)
PATCHES = [
    (HA, ".method private isEnableReport(Landroid/content/Context;ZZ)Z", "false"),
    (HA, ".method public executeReportHa(", "void"),
    (
        HA,
        ".method public onEvent(Ljava/util/LinkedHashMap;Ljava/lang/String;I)V",
        "void",
    ),
    (V0, ".method public run()V", "void"),
    (U, ".method public a()V", "void"),
]

for path, proto, mode in PATCHES:
    with open(path, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)

    idx = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith(".method") and proto in ln:
            idx = i
            break
    if idx is None:
        print("NOT FOUND: %s in %s" % (proto, os.path.basename(path)))
        continue

    # find the .locals line for this method
    loc = None
    for j in range(idx, min(idx + 12, len(lines))):
        if lines[j].strip().startswith(".locals"):
            loc = j
            break
    if loc is None:
        print("NO .locals for %s" % proto)
        continue

    marker = "# PATCH(hh6): telemetry disabled at source"
    if any(marker in l for l in lines[idx : loc + 4]):
        print("already patched: %s" % proto)
        continue

    if mode == "false":
        inject = [marker, "    const/4 v0, 0x0", "", "    return v0"]
    else:
        inject = [marker, "    return-void"]

    lines[loc + 1 : loc + 1] = inject + [""]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(nl.join(lines))
    print("patched: %s  (%s)" % (proto, os.path.basename(path)))

print("\n--- verify ---")
for path, proto, mode in PATCHES:
    with open(path, "r", encoding="utf-8") as f:
        t = f.read()
    i = t.find(proto)
    ok = i != -1 and "PATCH(hh6)" in t[i : i + 400]
    print("%-70s %s" % (proto[:68], "OK" if ok else "MISSING"))
