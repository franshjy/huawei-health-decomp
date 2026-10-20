"""hh5 - force the app's "logged in" flag, which removes the Huawei ID requirement.

`LoginInit.isBrowseMode()` is literally `!getIsLogined()`, so this single method opens
every browse-mode gate in the app (including the add-device button) without patching
individual call sites.

Recorded here after the fact: this patch was originally applied by hand, and the exact
byte delta was verified as +4 (const/4 + return).
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
    r"smali_classes2\com\huawei\login\ui\login\util\SharedPreferenceUtil.smali",
)
SIG = ".method public getIsLogined()Z"
MARK = (
    "# PATCH(hh5): force logged-in. Single source of truth -- LoginInit.isBrowseMode()"
)
BACKUP = F + ".pre-hh5"

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

# .locals 3 -> v0 is available; return an int literal for the boolean.
lines.insert(j + 1, "    " + MARK)
lines.insert(
    j + 2,
    "    # is literally !getIsLogined(), so this opens every browse-mode login gate",
)
lines.insert(j + 3, "    const/4 v0, 0x1")
lines.insert(j + 4, "")
lines.insert(j + 5, "    return v0")
lines.insert(j + 6, "")

open(F, "w", encoding="utf-8", newline="").write(nl.join(lines))
print("patched getIsLogined() -> true")
