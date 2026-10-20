"""hh9 - kill the DFX log upload at the WorkManager worker.

This is the only real egress for the DFX/CrowdTest pipeline. Everything upstream
(`mpw` / `Dfx_UploadLogUtil`, `nbz`, `nph`, `lyy`) merely *builds* a OneTimeWorkRequest
and hands it to WorkManager; the worker runs later, survives process death, and retries
on WiFi. Patching the callers is therefore not enough - a queued job still fires.
Returning success here makes the whole upstream graph inert.

Do not touch `.locals`: the original is `.locals 19` and the unreachable body still
references v1-v18. Rewriting that directive to `.locals 1` assembles cleanly but produces
bytecode the verifier rejects.
"""

import os, sys


def _root():
    """Work dir (the apktool decode). argv[1] or $HH_ROOT, default ./hh_decoded."""
    return os.environ.get("HH_ROOT") or (
        sys.argv[1] if len(sys.argv) > 1 else "hh_decoded"
    )


import shutil

F = os.path.join(
    _root(),
    r"smali_classes11\com\huawei\hwdevice\phoneprocess\util\LogUploadWorker.smali",
)
SIG = ".method public doWork()Landroidx/work/ListenableWorker$Result;"
MARK = "# PATCH(hh9): dfx.LogUploadWorker.doWork disabled (returns success)"
BACKUP = F + ".pre-hh9"

if not os.path.exists(F):
    raise SystemExit("missing: %s" % F)

if not os.path.exists(BACKUP):
    shutil.copy2(F, BACKUP)
    print("backup:", os.path.basename(BACKUP))

text = open(F, "r", encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in text else "\n"
lines = text.split(nl)

if any(MARK in l for l in lines):
    print("already patched, skipping")
    raise SystemExit(0)

idx = [i for i, l in enumerate(lines) if l.strip() == SIG]
if len(idx) != 1:
    raise SystemExit("expected exactly 1 match for %r, got %d" % (SIG, len(idx)))

i = idx[0]
j = i + 1
while j < len(lines) and not lines[j].strip().startswith(".locals"):
    j += 1
if j >= len(lines):
    raise SystemExit("no .locals found for %s" % SIG)

locals_line = lines[j].strip()
print("keeping %r (do not shrink - dead body uses v1..v18)" % locals_line)

lines.insert(j + 1, "    " + MARK)
lines.insert(
    j + 2,
    "    invoke-static {}, Landroidx/work/ListenableWorker$Result;->success()Landroidx/work/ListenableWorker$Result;",
)
lines.insert(j + 3, "")
lines.insert(j + 4, "    move-result-object v0")
lines.insert(j + 5, "")
lines.insert(j + 6, "    return-object v0")
lines.insert(j + 7, "")

open(F, "w", encoding="utf-8", newline="").write(nl.join(lines))
print("patched doWork() -> Result.success()")
