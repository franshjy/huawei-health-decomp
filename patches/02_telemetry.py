import os, sys
def _root():
    """Work dir (the apktool decode). argv[1] or $HH_ROOT, default ./hh_decoded."""
    return os.environ.get("HH_ROOT") or (sys.argv[1] if len(sys.argv) > 1 else "hh_decoded")

import io

BASE = _root()

# (relative smali path) -> list of exact method descriptors to turn into no-ops.
# Every target returns void, so a plain `return-void` insert is sufficient and no
# register/locals juggling is required.
TARGETS = {
    r"smali\com\huawei\operation\OpAnalyticsUtil.smali": [
        "init(Landroid/content/Context;)V",
        "init(Landroid/content/Context;Lcom/huawei/hwbasemgr/IBaseResponseCallback;)V",
        "setEvent(Ljava/lang/String;Ljava/util/LinkedHashMap;)V",
        "setEvent2nd(Ljava/lang/String;Ljava/util/LinkedHashMap;)V",
        "setEventOneErrorCode(Ljava/lang/String;I)V",
        "setEventWithActionType(ILjava/lang/String;)V",
        "setEventWithReportImmediately(Ljava/lang/String;Ljava/util/LinkedHashMap;)V",
        "setKeyProcessEvent(Ljava/lang/String;Ljava/util/LinkedHashMap;)V",
        "setNotificationPushEvent(Ljava/lang/String;Ljava/lang/String;)V",
        "setProbabilityProblemEvent(Ljava/lang/String;Ljava/lang/String;)V",
        "setRiskWarningEvent(Ljava/lang/String;Ljava/lang/String;)V",
        "setRiskWarningEventMap(Ljava/lang/String;Ljava/util/LinkedHashMap;)V",
        "sqliteDatabaseLockedExceptionSetEvent("
        "Landroid/database/sqlite/SQLiteDatabaseLockedException;Ljava/lang/String;)V",
        "isSetIgnoringBatteryOptimizations(Landroid/content/Context;Ljava/lang/String;)V",
    ],
    r"smali\com\huawei\operation\OpAnalyticsImpl.smali": [
        "setEvent(ILjava/lang/String;Ljava/util/LinkedHashMap;Z)V",
        "onReport()V",
    ],
    r"smali\com\huawei\operation\OpAnalyticsUtil$OpAnalyticsImpl2.smali": [
        "onReport(Ljava/lang/String;Ljava/lang/String;)V",
        "reportErrorCode(Ljava/lang/String;Ljava/util/LinkedHashMap;)V",
    ],
    # framework uploader: kills reporting from EVERY entry path, including the
    # watch-face subsystem which bypasses OpAnalyticsUtil entirely.
    r"smali_classes3\com\huawei\hianalytics\framework\datahandler\ReportTask.smali": [
        "run()V",
    ],
}

grand_patched = 0
grand_total = 0

for rel, meths in TARGETS.items():
    path = os.path.join(BASE, rel)
    if not os.path.exists(path):
        print("MISSING FILE: %s" % rel)
        continue
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        lines = fh.readlines()
    nl = "\r\n" if any(l.endswith("\r\n") for l in lines) else "\n"

    insert_at = []
    missing = []
    for sig in meths:
        start = None
        for k, l in enumerate(lines):
            if l.startswith(".method") and l.rstrip("\r\n").endswith(sig):
                start = k
                break
        if start is None:
            missing.append(sig)
            continue
        loc = None
        for k in range(start + 1, len(lines)):
            if lines[k].startswith(".end method"):
                break
            if lines[k].strip().startswith(".locals"):
                loc = k
                break
        if loc is None:
            missing.append(sig)
            continue
        insert_at.append(loc)

    # insert from the bottom up so earlier indices stay valid
    for idx in sorted(insert_at, reverse=True):
        lines[idx + 1 : idx + 1] = [nl, "    return-void" + nl]

    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.writelines(lines)

    grand_patched += len(insert_at)
    grand_total += len(meths)
    print(
        "%-62s patched %2d/%2d %s"
        % (rel, len(insert_at), len(meths), ("MISSING=%s" % missing) if missing else "")
    )

print("")
print("TOTAL: %d/%d methods neutralised" % (grand_patched, grand_total))
