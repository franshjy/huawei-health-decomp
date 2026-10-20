import os, sys
def _root():
    """Work dir (the apktool decode). argv[1] or $HH_ROOT, default ./hh_decoded."""
    return os.environ.get("HH_ROOT") or (sys.argv[1] if len(sys.argv) > 1 else "hh_decoded")

import shutil, re

F = os.path.join(_root(), r"smali_classes3\com\huawei\hianalytics\a0.smali")

PREFIXES = (
    "onEvent",
    "onEventSync",
    "onPause",
    "onResume",
    "onBackground",
    "onForeground",
    "onReport",
    "onStreamEvent",
)

bak = F + ".pre-hh7"
if not os.path.exists(bak):
    shutil.copy2(F, bak)
    print("backup:", os.path.basename(bak))

with open(F, "r", encoding="utf-8", newline="") as f:
    text = f.read()
nl = "\r\n" if "\r\n" in text else "\n"
lines = text.split(nl)

MARK = "# PATCH(hh7): HiAnalytics entry point disabled"
out = []
patched = 0
i = 0
while i < len(lines):
    line = lines[i]
    out.append(line)
    s = line.strip()
    if s.startswith(".method"):
        # extract method name: ".method public final onEvent(..."
        m = re.match(
            r"\.method\s+(?:public |private |protected |static |final |synthetic )*([A-Za-z0-9_$]+)\(",
            s,
        )
        name = m.group(1) if m else None
        if name and name.startswith(PREFIXES):
            # copy until .locals, then inject
            j = i + 1
            body = []
            while j < len(lines) and not lines[j].strip().startswith(".locals"):
                body.append(lines[j])
                j += 1
            if j < len(lines):
                out.extend(body)  # annotations etc before .locals
                out.append(lines[j])  # the .locals line
                out.append("    " + MARK)
                out.append("    return-void")
                out.append("")
                patched += 1
                i = j + 1
                continue
    i += 1

with open(F, "w", encoding="utf-8", newline="") as f:
    f.write(nl.join(out))

print("methods patched:", patched)
print("--- verify ---")
t = open(F, encoding="utf-8").read()
print("PATCH(hh7) occurrences:", t.count("PATCH(hh7)"))
for name in PREFIXES:
    n = len(
        re.findall(
            r"\.method\s+(?:public |private |protected |static |final |synthetic )*"
            + name
            + r"\(",
            t,
        )
    )
    p = len(
        re.findall(
            r"\.method\s+(?:public |private |protected |static |final |synthetic )*"
            + name
            + r"\([^\n]*\n(?:[^\n]*\n)*?[ \t]*"
            + re.escape(MARK),
            t,
        )
    )
    print("  %-14s total=%d patched=%d" % (name, n, p))
