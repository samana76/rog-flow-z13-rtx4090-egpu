# Code map and adaptation requirements

## Working implementation snapshot

`reference-system/` mirrors installed paths without installing anything:

- `opt/gpd-egpu/615.71.09/loader.py`: matching proprietary core/UVM loading, verified DPM0/GSP0 and power policy.
- `opt/gpd-egpu/615.71.09/guard.py`: shared validation/diagnostic helpers. It originated in a trial runner; trial entry points are not the production startup interface.
- `opt/gpd-egpu/display-extension/display-start.py`: kernel-specific Arch/CachyOS modeset/DRM startup.
- `opt/gpd-egpu/auto/auto-start.py`: boot/add activation and persistent failure lockout.
- `opt/gpd-egpu/auto/restart-clean-cycle.py`: restart only after verified clean eject.
- `usr/local/sbin/gpd-egpu-start`: registry-based full compute/display dispatch wrapper.
- `usr/local/libexec/gpd-egpu-eject`: root-owned, no-arguments clean eject helper.

`maintenance/` contains the activation unit/rule, password-free authorization reference and selected maintenance code. `tray/` contains the **current** Python/native-KDE tray implementation. `historical-validation/` includes CUDA child kernels and the historical Arch build script, whose original protected trial-directory assumptions are retained for review.

The old Qt-popup and experimental surprise-removal driver candidates are intentionally not included as working implementations.

## Not a generic installer

The original code is tightly scoped to one tested system. Before adaptation:

1. Replace `EGPU_USER` account paths and polkit subject intentionally; review UID 1000 assumptions too.
2. Review exact kernels, BIOS, driver/userspace versions, module source versions and artifact hashes.
3. Replace baseline/trial-record dependencies with equivalent reviewed local checks; do not simply delete every guard until a script runs.
4. Recompute code hash pins after reviewed changes. **Account redaction changes Python source hashes**, so original hash pins in dependent scripts will not validate these redacted files as-is. `provenance/source-files.json` distinguishes original and bundled hashes. This is intentional disclosure, not an invitation to bypass integrity checks.
5. Preserve root ownership and non-writable parent paths for privileged code; permit only the exact no-arguments eject helper through polkit for an active local user. Never authorize a general interpreter or arbitrary shell command.
6. Preserve snapshots, working boot images/checksums, package inventories, reverse-order rollback records and failure lockout state.

The production loader deliberately checks that the old diagnostic verifier is disabled/inactive. That disabled-unit dependency is part of the reference implementation; account for it in a clean deployment. The original installation scripts and historical tests were not a general community package manager.

## Tray build

Already-installed requirements on the tested system: Python/PySide6, shiboken6, Qt6 Widgets, KDE KF6 KStatusNotifierItem (with `setIsMenu`, available since 6.14), C++ compiler, pkg-config and a Plasma session. The KDE header location below matches Arch packaging.

From `code/tray/`:

```bash
./build-native.sh
python3 egpu-tray.py
```

The tray does not install the privileged helper or policy. It expects `/usr/local/libexec/gpd-egpu-eject` to be installed separately with reviewed permissions. The local binary is rebuilt from `native-tray.cpp`; it is not included in the public archive. The application uses KDE's exported menu, so there is no XWayland workaround in the final code.

Install the reviewed tray source and compiled bridge together into a user-owned application directory, and create a user application/autostart `.desktop` entry pointing to its Python script. `gpd-egpu-tray.desktop.example` shows the reference form. A per-user local socket prevents duplicate tray instances.

Do not replace the installed production scripts with these redacted references without adapting their integrity chain and rollback records. The bundle itself makes no machine changes.

## September14 code additions

`update-reference/` contains machine-specific installers for CachyOS integration, including the corrected same-filesystem history archive and partial-state resumption. These are deployment records, not generic installers. `pending-lact/` retains the historical proposed helper and installer. Conditional restoration is now included in the deployed `reference-system/` reconnect helper.

The older `maintenance/` installers remain historical and can contain superseded kernel guards. Do not use them to overwrite the latest reference implementation. Every layered rollback must run in reverse installation order.

Run bundle regression tests with `python3 -m unittest discover -s tests`. They import guarded functions only; they do not initialize a GPU.

## September 15 package-query fix

The current reference loader captures pacman stdout and stderr separately for package identity checks, retaining exit-code and exact-version validation. Display and reconnect hash dependencies were updated together. See the incident report in `docs/SEPTEMBER-15-PACKAGE-QUERY-FIX.md`. Historical installers and the older `pending-lact/` installer retain their historical baselines; do not run them over the updated reference. The current reference includes LACT restoration with the updated integrity chain. The tested private repair is not distributed as a universal unlock utility: its permission to archive a lockout was specific to the reviewed pre-initialization failure.

## September 15 update automation and live tray readings

See [the complete update program](automatic-updates/README.md) and [latest incident and validation report](../docs/SEPTEMBER-15-UPDATES-AND-TELEMETRY.md). The registry reader and update manager are also mirrored under reference-system. The runtime registry and installed-hashes manifest are generated machine state, not portable configuration. The tray now polls GPU utilization and watts asynchronously and reaps its monitoring child before invoking safe eject.
