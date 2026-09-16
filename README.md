# RTX 4090 over USB4 on ASUS ROG Flow Z13 GZ302EA

Field report from September 2026: **CUDA, NVIDIA external display output, automatic startup/connection, and tray-assisted safe disconnect/reconnect work on this machine. Surprise unplugging does not. An intermittent reboot/shutdown hang remains unresolved; see the latest update.**

The successful driver is **NVIDIA's unpatched proprietary 615.71.09**, built for the exact running kernel, with `NVreg_EnableGpuFirmware=0` and `NVreg_DynamicPowerManagement=0`. We did not write a new NVIDIA driver. The custom work is the guarded loading, power-policy checks, automatic reconnect, safe disconnect helper, and KDE tray integration. Experimental patches are not part of the successful driver.

Updated September 14: dual-kernel integration is deployed; conditional LACT restoration is included separately as staged, not live-confirmed.

Latest fix: September 15 package-query warnings no longer masquerade as a driver-version mismatch. The owner confirmed recovery; NVIDIA activation and Blender CUDA/OptiX enumeration were verified. [Details and regression coverage](docs/SEPTEMBER-15-PACKAGE-QUERY-FIX.md).

Start with:

- [September 14 changes, upgrade procedure and reboot-failure evidence](docs/SEPTEMBER-14-UPDATE.md)

- [Full account and reproduction sequence](docs/FINDINGS-AND-STEPS.md)
- [What remains for seamless surprise unplug](docs/SEAMLESS-DISCONNECT.md)
- [Driver origin and build instructions](driver/BUILD.md)
- [Code layout and adaptation requirements](code/README.md)
- [Tested module identities](driver/tested-artifacts.json)

## Tested configuration

| Component | Configuration |
|---|---|
| Laptop | ASUS ROG Flow Z13 GZ302EA, AMD Strix Halo |
| BIOS | GZ302EA.314 |
| Enclosure | GPD TBT5-EGPU |
| PCI bridge | Intel JHL9480, `8086:5786` |
| GPU | NVIDIA RTX 4090 AD102 / Ada, `10de:2684` |
| Preferred kernel | Arch `7.2.4-arch1-2` (`linux 7.2.4.arch1-2`) |
| Current CachyOS kernel | `7.2.5-1-cachyos` |
| Historical CachyOS compute tests | `7.2.4-1-cachyos` |
| Userspace | `nvidia-utils 615.71.09-1` |
| Successful module flavor | Proprietary NVIDIA, GSP off, DPM0 |
| Desktop | KDE Plasma / KWin Wayland, AMD internal display |

## Validation boundaries

| Capability | Evidence |
|---|---|
| Core initialization and NVML | Passed on Arch and CachyOS, including 60-second idle checks |
| Tiny CUDA kernel | 256 results verified on Arch7.2.4 and CachyOS7.2.4/7.2.5 |
| Bounded CUDA transfers/kernel work | 60 rounds of 64-MiB transfers/launches, followed by 60 seconds idle, passed on Arch7.2.4 and historical CachyOS7.2.4; not repeated on7.2.5 |
| RTX 4090 external monitor | Confirmed on Arch7.2.4 and CachyOS7.2.5 |
| Boot with enclosure connected | User confirmed external display activates automatically |
| Clean disconnect | User confirmed internal desktop survives physical removal after normal driver unload |
| Reconnect after clean eject | User confirmed automatic activation; also manually validated same-boot restart |
| Tray, left-click menu, no separate app needed | User confirmed native KDE menu works |
| Reboot with active eGPU after multiple cycles | Intermittent failure: link loss, Xid79 and display teardown hang; not solved |
| Conditional LACT restoration | Staged code, six unit tests passed; live validation pending |
| Surprise unplug while driver/display active | **Failed: desktop freeze requiring forced shutdown** |
| Sustained model/gaming workloads, suspend/resume, arbitrary kernel upgrades | Not established by these tests |

These are observations from one machine, not a guarantee for every JHL9480 enclosure or GPU. No controlled experiment isolated GSP alone: module flavor, firmware path and patch status changed together.

## Public repository and local driver files

`local-tested-driver/` in the local folder contains ten exact tested `.ko` files. They remain unmodified, have kernel-specific identities, and may contain build-machine paths in debug information. **They are excluded from this GitHub repository and the community `.tar.gz` archive.** The archive contains code, configuration, vendor download/build instructions, license text and artifact hashes. Obtain NVIDIA's driver from its vendor source rather than assuming a kernel module from another machine is portable.

Account names in text code are replaced with `EGPU_USER`; hardware serials, filesystem UUIDs, boot IDs, network addresses, raw journals and root backup inventories are omitted. No file in this bundle has been installed or executed against the GPU as part of assembling it.

The reference code is a documented snapshot, **not a turnkey installer**. It deliberately contains exact machine/version guards and hashes that must be reviewed when adapting it. See `code/README.md` before attempting deployment.

## Credits

The initial BIOS/DPM/root-port direction came from [djanice1980/eGPU-Blackwell-Stability](https://github.com/djanice1980/eGPU-Blackwell-Stability) and its [runbook](https://github.com/djanice1980/eGPU-Blackwell-Stability/blob/main/docs/egpu-runbook-v2.md). The locally retained reference checkout is commit `a95d1b0eaea361b7f71763e491c8ac450b357f1a`; the live repository may differ. That project's principal GPU is Blackwell; this report concerns Ada.

NVIDIA authored the driver. KDE/Qt provide the desktop integration libraries. The scripts and report were developed with OpenAI Codex, with the machine owner performing privileged installations and hardware tests. Successful user-reported tests are distinguished from code-only validation.
