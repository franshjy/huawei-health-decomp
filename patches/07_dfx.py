import os, sys


def _root():
    """Work dir (the apktool decode). argv[1] or $HH_ROOT, default ./hh_decoded."""
    return os.environ.get("HH_ROOT") or (
        sys.argv[1] if len(sys.argv) > 1 else "hh_decoded"
    )


import re


import shutil

BASE = _root()

# (relative path, exact method signature, short label)
TARGETS = [
    # --- CrowdTest / beta SDK: never bootstrap, never send logs ---
    (
        r"smali_classes10\lyy.smali",
        "init(Landroid/content/Context;)V",
        "crowdtest.init",
    ),
    (
        r"smali_classes10\lyy.smali",
        "sendLog(Landroid/content/Context;Lcom/huawei/hwcrowdtestapi/HealthFeedbackParams;"
        "Ljava/lang/String;ZZLcom/huawei/hwcrowdtestapi/HealthSendLogCallback;)V",
        "crowdtest.sendLog",
    ),
    (
        r"smali_classes10\lyy.smali",
        "checkLogUploadStatus(Landroid/content/Context;)V",
        "crowdtest.checkLogUploadStatus",
    ),
    (
        r"smali_classes10\lyy.smali",
        "gotoFeedback(Landroid/content/Context;Llyz;Lcom/huawei/hwcrowdtestapi/HealthFeedbackParams;"
        "Lcom/huawei/hwcrowdtestapi/HealthFeedbackCallback;)V",
        "crowdtest.gotoFeedback",
    ),
    # --- DFX app-event log writer: no event log files ---
    (
        r"smali_classes4\cpi.smali",
        "a(Ljava/lang/String;Ljava/lang/String;ILcom/huawei/health/devicemgr/business/entity/DeviceInfo;)V",
        "dfx.logAppEvent",
    ),
    (
        r"smali_classes4\cpi.smali",
        "b(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;"
        "Lcom/huawei/health/devicemgr/business/entity/DeviceInfo;)V",
        "dfx.logAppEvent2",
    ),
    # --- DFX upload task ---
    (r"smali_classes11\nph.smali", "run()V", "dfx.EventLogUploadTask.run"),
    # --- DFX upload release (startUploadLogWithWifi etc.) ---
    (r"smali_classes11\nbz.smali", "a(Landroid/content/Context;)V", "dfx.uploadWifi"),
    (
        r"smali_classes11\nbz.smali",
        "a(Lcom/huawei/health/devicemgr/business/entity/DeviceInfo;Ljava/lang/String;"
        "Lcom/huawei/health/IBaseCommonCallback;)V",
        "dfx.uploadDeviceLog",
    ),
    # --- DFX upload driver ---
    (
        r"smali_classes11\mpw.smali",
        "a(Landroid/content/Context;ZLjava/lang/String;)V",
        "dfx.uploadLog",
    ),
    (
        r"smali_classes11\mpw.smali",
        "d(Landroid/content/Context;ZLjava/lang/String;)V",
        "dfx.uploadLogWifi",
    ),
]

MARK = "# PATCH(hh8): {label} disabled"
ok = 0
fail = []

for rel, sig, label in TARGETS:
    path = os.path.join(BASE, rel)
    if not os.path.exists(path):
        fail.append((label, "file missing"))
        continue

    bak = path + ".pre-hh8"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)

    with open(path, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)

    # Match the declaration itself. A bare `sig in l` also matches `uninit(...)`
    # for the signature `init(...)`, which silently double-counts.
    decl = re.compile(
        r"\.method\s+(?:public |private |protected |static |final |synthetic )*"
        + re.escape(sig)
    )
    hits = [i for i, l in enumerate(lines) if decl.search(l)]
    if len(hits) != 1:
        fail.append((label, "%d matches" % len(hits)))
        continue

    i = hits[0]
    # refuse to double-patch
    if any(MARK.split("{")[0] in l for l in lines[i : i + 8]):
        fail.append((label, "already patched"))
        continue

    j = i + 1
    while j < len(lines) and not lines[j].strip().startswith(".locals"):
        j += 1
    if j >= len(lines):
        fail.append((label, "no .locals"))
        continue

    lines.insert(j + 1, "    " + MARK.format(label=label))
    lines.insert(j + 2, "    return-void")
    lines.insert(j + 3, "")

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(nl.join(lines))
    ok += 1

print("patched: %d / %d" % (ok, len(TARGETS)))
for label, why in fail:
    print("  FAIL %-30s %s" % (label, why))

# verify
print("\n--- verify ---")
total = 0
for rel, sig, label in TARGETS:
    path = os.path.join(BASE, rel)
    t = open(path, encoding="utf-8").read()
    n = t.count("PATCH(hh8): " + label + " disabled")
    total += n
    print("  %-32s %s" % (label, "OK" if n == 1 else "MISSING(%d)" % n))
print("markers total:", total)
sys.exit(0 if ok == len(TARGETS) else 1)
