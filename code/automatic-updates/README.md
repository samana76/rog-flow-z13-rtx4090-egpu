# Automatic eGPU update support — reference implementation

This directory contains the actual update program and deployment references, not just a description:

- `payload/update.py`: pacman pre/post manager, signed-header retrieval, unprivileged four-module build, boot/initramfs validation, backup/receipt handling and registry commit.
- `payload/registry.py`: strict kernel/artifact schema and trusted-path checks.
- `payload/registry.json`: original two-kernel baseline fixture, **not the current live registry**. New successful builds are appended by the installed updater. Machine-specific new build hashes are not fabricated here.
- `payload/00-gpd-egpu-update-pre.hook` and `payload/zz-gpd-egpu-update-post.hook`: pacman integration.
- `install.py`, `rollback.py`, `payload-seal.json`, `payload/changes.json`: original installation layer, exact original baselines and rollback implementation.
- `routing-fix/`: subsequent startup-dispatch repair, installer and reverse-order file rollback. The current reference-system tree includes this correction; the original payload deliberately preserves the prior installation baseline.
- `test_support.py`: portable update-policy regressions. The private real-boot-inventory test was omitted; no root inventory is distributed.

## How it was deployed on the source machine

1. Audit the installed loaders, module artifacts, package identities, normal boot entries and fallback; retain recovery evidence.
2. Obtain the exact NVIDIA 615.71.09 vendor archive. The original installer expects it at `../update-preparation/NVIDIA-Linux-x86_64-615.71.09-no-compat32.run` and checks its SHA256. The archive is not included.
3. Generate/review the private payload and integrity pins against that machine's actual state, validate the hook/build path, then install the root-owned support and pacman hooks with `install.py`.
4. Run a normal full `sudo pacman -Syu`; inspect hook completion before rebooting. Keep an unchanged tested kernel as fallback.
5. Apply the subsequent registered-kernel routing correction with its matching integrity chain. On a new adaptation, integrate this dispatch from the outset rather than retaining the historical kernel-name fallback.
6. Validate the new kernel at runtime: core/NVML, display, CUDA, and separately clean eject/reconnect. Do not promote untested builds merely because compilation succeeded.

**Do not run these redacted installers unchanged.** They require exact old helper hashes, private root records, boot layout, matching payloads and recovery state. Redaction deliberately invalidates some original pins/seals. Adapt and recompute the entire reviewed integrity chain; do not remove guards to force installation. The repository does not contain a universal setup installer or vendor driver archive.

The manager accepts a limited set of full-system pacman invocations; new NVIDIA releases, unsupported transactions, missing fallback and changes to both tested kernels stop for review. Successful pre-builds do not make arbitrary future updates safe. A failing post-hook cannot roll back the package transaction automatically.

Run code-only checks without root:

```sh
python3 code/automatic-updates/test_support.py
python3 -m unittest discover -s tests
python3 code/tray/test_tray.py
```

Undo layers in reverse installation order: routing repair first, then update support, then earlier loader changes. Review the rollback guards and newer registry entries; never remove a needed active-kernel payload blindly.
