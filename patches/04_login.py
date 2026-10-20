"""hh4 - login gate.

The Huawei ID requirement is entirely app-level. `LoginInit.isBrowseMode()` is literally
`!getIsLogined()`, so forcing that one boolean open every browse-mode gate in the app,
including the add-device button. The BLE pairing path never consults an account.

Two edits:

  SharedPreferenceUtil.getIsLogined()  -> true
      Single source of truth. Preferred over patching each call site.

  LoginInit.browsingToLogin(cb, key)   -> invoke cb.onResponse(0, null) and return
      The gate interceptor. With getIsLogined() forced true this is largely redundant
      (the original already reports code 0 when logged in), but it is kept so the build
      matches the one that was verified on-device.
"""

import os, sys


def _root():
    """Work dir (the apktool decode). argv[1] or $HH_ROOT, default ./hh_decoded."""
    return os.environ.get("HH_ROOT") or (
        sys.argv[1] if len(sys.argv) > 1 else "hh_decoded"
    )


import re
import shutil

# (path, exact method signature, kind, marker)
#   kind "true"      -> const/4 v0, 0x1 / return v0        (boolean -> true)
#   kind "callback0" -> cb.onResponse(0, null) / return-void
TARGETS = [
    (
        r"smali_classes2\com\huawei\login\ui\login\util\SharedPreferenceUtil.smali",
        "getIsLogined()Z",
        "true",
        "# PATCH(hh4): force logged-in; LoginInit.isBrowseMode() is !getIsLogined()",
    ),
    (
        r"smali\com\huawei\login\ui\login\LoginInit.smali",
        "browsingToLogin(Lcom/huawei/hwbasemgr/IBaseResponseCallback;Ljava/lang/String;)V",
        "callback0",
        "# PATCH(hh4): force login gate to report success (pairing proceeds without Huawei ID)",
    ),
]


def insert_regs(kind):
    if kind == "true":
        return ["    const/4 v0, 0x1", "", "    return v0", ""]
    return [
        "",
        "    if-eqz p1, :rea_patch_ret",
        "",
        "    const/4 v0, 0x0",
        "",
        "    const/4 v1, 0x0",
        "",
        "    invoke-interface {p1, v0, v1}, Lcom/huawei/hwbasemgr/IBaseResponseCallback;->onResponse(ILjava/lang/Object;)V",
        "",
        "    :rea_patch_ret",
        "    return-void",
        "",
    ]


ok = 0
for rel, sig, kind, mark in TARGETS:
    path = os.path.join(_root(), rel)
    if not os.path.isfile(path):
        raise SystemExit("missing: %s" % path)

    text = open(path, "r", encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)

    if any(("PATCH(hh4)" in l or "REA patch" in l) for l in lines[:4000]):
        print("already patched, skipping:", os.path.basename(path))
        continue

    bak = path + ".pre-hh4"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)

    decl = re.compile(
        r"\.method\s+(?:public |private |protected |static |final |synthetic )*"
        + re.escape(sig)
    )
    hits = [i for i, l in enumerate(lines) if decl.search(l)]
    if len(hits) != 1:
        raise SystemExit(
            "expected 1 match for %r in %s, got %d" % (sig, rel, len(hits))
        )

    i = hits[0]
    j = i + 1
    while j < len(lines) and not lines[j].strip().startswith(".locals"):
        j += 1
    if j >= len(lines):
        raise SystemExit("no .locals found for %s" % sig)

    block = ["    " + mark] + insert_regs(kind)
    for offset, line in enumerate(block):
        lines.insert(j + 1 + offset, line)

    open(path, "w", encoding="utf-8", newline="").write(nl.join(lines))
    print("patched %s -> %s" % (sig.split("(")[0], kind))
    ok += 1

print("applied %d/%d" % (ok, len(TARGETS)))
