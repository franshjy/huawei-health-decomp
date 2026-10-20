# huawei-health-decomp

Repackaging notes and patch scripts for **Huawei Health** (`com.huawei.health`),
`versionCode 1700008300` / `versionName 17.0.8.300`. Purpose of this repo is to:
1. Strip analytics, bloat, and other data transportation methods to Huawei's servers
2. Allow pairing and other functionalities without logging in.


Repo was tested on a  **Huawei Watch GT 2** on a non-Huawei phone, without account, without root, and without an emulator.

**THIS REPOSITORY DOES NOT PROVIDE APKS NOR SIGNING KEYS** 
You can download the official Huawei Health APK from their website or their app store.

## Patches

| # | Script | Effect |
|---|---|---|
| 00 | `patches/00_securitychecker.py` | `SecurityChecker.e()` → `false`. Disables the self-signature check. **Required** — without it the app calls `System.exit(0)` ~19 s after launch, with no crash, no tombstone and nothing in logcat's crash buffer. |
| 01 | `patches/01_whitebox.py` | Native `.so`: forces the auth gate in `executeAuth` onto its success path. Without it, startup ANRs with `StringIndexOutOfBoundsException` in `createNewSecureKey`. |
| 02 | `patches/02_telemetry.py` | 19 analytics methods in `OpAnalyticsUtil` / `OpAnalyticsImpl` / `ReportTask` → no-op. |
| 03 | `patches/03_bloat.py` | 9 methods: DFX monitor centre, `DownloadFileProvider`, `PPSECProvider`, config + A/B registrars. |
| 04 | `patches/04_login.py` | `SharedPreferenceUtil.getIsLogined()` → `true`, plus `LoginInit.browsingToLogin(...)` → reports code 0. Removes the Huawei ID requirement. |
| 05 | `patches/05_hatool.py` | 5 methods in the network-kit HiAnalytics and `hatool` task queue. |
| 06 | `patches/06_hianalytics.py` | All 20 entry points of `com.huawei.hianalytics.a0` (the real `HiAnalyticsInstance`). |
| 07 | `patches/07_dfx.py` | 11 DFX / CrowdTest methods across 5 classes. |
| 08 | `patches/08_loguploadworker.py` | `LogUploadWorker.doWork()` → `Result.success()`. This is the only real DFX upload egress. |

## Login Bypass (04)

The Huawei ID requirement is entirely app-level, not protocol-level. `LoginInit.isBrowseMode()`
is literally `!getIsLogined()`, so forcing that one boolean opens every browse-mode gate
(including the add-device button). The BLE pairing path (`AllDeviceListActivity` →
`rnj.b()` → `DevicePairGuideSecondActivity`, and `DeviceManager.bindDevice()` →
`doCreateBond()`) never consults an account; device discovery is
`getConnectedDevices(7)` / `getBondedDevices()`.

## Telemetry (06 & 08)

There are three separate HiAnalytics implementations in this APK. Patching the network-kit
and `hatool` copies (05) silences two of them and looks successful at boot, but the live one is
`com.huawei.hianalytics.a0`, and feature analytics instantiates lazily on first use.

The DFX pipeline builds a `OneTimeWorkRequest` and hands it to WorkManager. The job
survives process death and retries on WiFi, so patching the callers (07) is not sufficient on
its own, 08 makes the worker inert.

A boot-time measurement proves nothing for either. Verify by exercising the UI and counting
`RecordTask==> record evt` (should be 0) and `WM-WorkerWrapper: Worker result SUCCESS` (should
appear, with no upload following).

## Usage

```bash
python apply_all.py --apk com.huawei.health.1700008300.apk \
                    --keystore my.keystore --ks-pass pass:secret
```

That decodes (`apktool d -r`), applies patches 00-08, rebuilds, aligns and signs.

`--preflight-only` checks the base APK and exits without decoding.

### Requirements

- Python 3.9+
- `apktool` (developed against **3.0.1**) on `PATH`, or `APKTOOL=/path/to/apktool`
- Android `build-tools` with `aapt2`, `zipalign`, `apksigner` — via `BUILD_TOOLS=/path` or
  `ANDROID_HOME`

### Reference build

The exact APK these were developed against:

```
size   238.1 MB
sha256 6E693FE6051B69FEFA68215CE52D1F3AE4A2A7C8E25D09B034C73C20BF6F42FD
```

`versionCode` is the gate. A different `sha256` with the same `versionCode` is fine — the same
version from another channel (bundle split, mirror re-zip) differs in bytes but not in
obfuscation mapping. The patches verify their targets as they run and fail loudly on drift.

`-r` during decode is required: it keeps `resources.arsc` raw and `AndroidManifest.xml` as
binary AXML. That is why nothing here edits the manifest.

## Signing

You must sign with your own key. The patched build cannot be installed over an official one.

Practically, on Xiaomi/MIUI:

- An official Huawei Health install **cannot** be updated in place; uninstall first.
- In-place updates between *your own* builds are also frequently rejected
  (`INSTALL_FAILED_UPDATE_INCOMPATIBLE: upgrade keys do not match`) even with an identical
  certificate. Plan for uninstall → install → re-pair.
- `INSTALL_FAILED_USER_RESTRICTED` usually means MIUI's on-device confirmation prompt timed
  out. Retry and accept it; it is not a policy block.
- Runtime permission grants are wiped by every reinstall. After each install:

```bash
adb shell pm grant com.huawei.health android.permission.ACCESS_BACKGROUND_LOCATION
```

Without it, the weather-report toggle silently reverts to off: the push is issued from
`:PhoneService`, a background process, and gets dropped without a location fix.


## Known limits

- Cloud features are dead by design — no account means no token. Expect
  `ProfileUploadTaskSdk: the account has expired` and `error:1007`.
- `nor.d()` is deliberately untouched: it also drives thermal and battery tasks.
- CrowdTest feedback UI is no-op'd, not removed.
- Patches are specific to `versionCode 1700008300`. Other builds need re-analysis, not just
  re-running these scripts.
- Watchfaces aren't available without logging in.

## Not included

`hh_decoded/` (the apktool working tree), build outputs, logcat captures, and the signing
keystore are all excluded — see `.gitignore`. Regenerate the tree with `apply_all.py`.

`manifest_tree.txt` and `wb_disasm.txt` are retained as analysis evidence: the manifest is
binary AXML, and the whitebox disassembly backs patch 01.
