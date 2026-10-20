"""hh0 - disable the app's self-signature check.

This was the very first patch made on this project and, until now, the only one that was
never scripted. That omission is not cosmetic: without it the app calls `System.exit(0)`
about 15-20 seconds after launch.

SecurityChecker compares the running APK's signature against the one it was built with.
A repack signed with your own key fails that check, so the check must be disabled or the
app kills itself. The symptom is confusing because it is NOT a crash - the process exits
cleanly with status 0, leaving no FATAL, no tombstone and nothing in logcat's crash buffer:

    I/R_SecurityChecker: [C++] Log helper set successfully
    W/R_SecurityChecker: wrong App: java
    I/m.huawei.health: System.exit called, status: 0
    I/Zygote: Process 12345 exited cleanly (0)

Diagnose with:
    adb shell dumpsys activity exit-info com.huawei.health      # look for reason=1 EXIT_SELF

The Java-side exit path ends in `health/compact/a/CommonLibUtil.c(Context)`, which starts an
activity and then calls System.exit(0). Returning false here stops it being reached.
"""

import os, sys


def _root():
    """Work dir (the apktool decode). argv[1] or $HH_ROOT, default ./hh_decoded."""
    return os.environ.get("HH_ROOT") or (
        sys.argv[1] if len(sys.argv) > 1 else "hh_decoded"
    )


import re
import shutil

F = os.path.join(
    _root(),
    r"smali_classes10\com\huawei\hwcommonmodel\security\SecurityChecker.smali",
)
SIG = "e()Z"
MARK = "# PATCH(hh0): disable app self-signature check (original called System.exit(0) on mismatch)"
BACKUP = F + ".pre-hh0"

if not os.path.isfile(F):
    raise SystemExit("missing: %s" % F)

text = open(F, "r", encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in text else "\n"
lines = text.split(nl)

# Accept either marker so this is a no-op on an already-patched tree.
already = any(("PATCH(hh0)" in l or "REA patch" in l) for l in lines)
if already:
    print("already patched, skipping")
    raise SystemExit(0)

if not os.path.exists(BACKUP):
    shutil.copy2(F, BACKUP)
    print("backup:", os.path.basename(BACKUP))

decl = re.compile(
    r"\.method\s+(?:public |private |protected |static |final |synthetic )*"
    + re.escape(SIG)
)
hits = [i for i, l in enumerate(lines) if decl.search(l)]
if len(hits) != 1:
    raise SystemExit("expected exactly 1 match for %r, got %d" % (SIG, len(hits)))

i = hits[0]
j = i + 1
while j < len(lines) and not lines[j].strip().startswith(".locals"):
    j += 1
if j >= len(lines):
    raise SystemExit("no .locals found for %s" % SIG)

lines.insert(j + 1, "    " + MARK)
lines.insert(j + 2, "    const/4 v0, 0x0")
lines.insert(j + 3, "")
lines.insert(j + 4, "    return v0")
lines.insert(j + 5, "")

open(F, "w", encoding="utf-8", newline="").write(nl.join(lines))
print("patched SecurityChecker.e() -> false (self-signature check disabled)")
