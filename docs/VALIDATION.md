# Evidence summary and bundle checks

## Hardware validation recorded in the investigation

The following are sanitized milestone summaries from the supplied trial logs, not new tests run while creating this bundle:

| UTC milestone | Outcome |
|---|---|
| 2026-09-13 17:32 | CachyOS proprietary615/non-GSP core, NVML and 60-second idle PASS; DPM0 |
| 2026-09-13 17:39 | CachyOS tiny CUDA kernel PASS; 256 verified results |
| 2026-09-13 17:50 | CachyOS bounded CUDA PASS; 60 x 64-MiB rounds and subsequent idle checks |
| 2026-09-13 18:03 | Arch proprietary615/non-GSP core, NVML and 60-second idle PASS |
| 2026-09-13 18:04 | Arch smoke child stopped on its own guarded-directory assumption before CUDA; not hardware failure |
| 2026-09-13 18:09 | Corrected Arch continuation PASS; 256 results, PCI/NVML healthy after 60 seconds |
| 2026-09-13 18:14 | Arch bounded CUDA PASS; 60 x 64-MiB rounds and subsequent idle checks |
| 2026-09-14 01:25 | Clean eject released clients and normally unloaded DRM, modeset, UVM and core; owner subsequently confirmed physical unplug worked |
| 2026-09-14 02:29 | Same-boot original driver restart after clean eject READY; owner confirmed |

Later owner confirmations established external monitor output, automatic connected boot, automatic clean-eject reconnect and the native left-click tray menu. No total cycle count or long-duration reliability measurement was established.

Representative successful live state:

```text
Driver: 615.71.09 proprietary
DynamicPowerManagement: 0
EnableGpuFirmware: 0
Root ports: power/control=on
GPU and HDA: power/control=on
Parent/GPU PCI configuration readable before and after the bounded checks
```

The unused root sometimes had accumulated runtime-suspended time while its current power/control was on. This was not treated as a failure.

The first display candidate's 60-second activation PASS is not proof of surprise-removal safety. The final working artifact set excludes that candidate and retains the original proprietary display modules.

## Validation during bundle creation

- All included Python sources compile syntactically without executing them.
- Tray C++ bridge builds against installed Qt6/KF6.
- Offscreen tray startup exits successfully; no disconnect helper invoked.
- Three tray unit tests pass (dynamic PCI identity, success-marker/exit requirements, fixed helper target).
- Ten local module files report matching 615.71.09 version and exact expected kernel vermagic; their SHA256 hashes are cross-checked against the retained successful payload manifests.
- Public text is scanned for the original account, hostname, machine ID, filesystem UUID and GPU UUID prefix.
- Public archive excludes local binaries, compiled UI objects, bytecode, raw journals and machine backup records.

These checks do not install the redacted code, run CUDA, change drivers, exercise physical removal, or establish portability to another machine. `SHA256SUMS` verifies the public source/documentation files; exact historical NVIDIA module hashes are separately recorded in `driver/tested-artifacts.json`.

## September14 refresh checks

The bundle now carries10 exact module artifacts: four Arch7.2.4, two historical CachyOS7.2.4, four CachyOS7.2.5. All hashes checked. All Python sources compile;22 bundled regression tests pass, including six tests of pending LACT restoration. Earlier test imports referenced retired workspace paths; imports now resolve bundled code. No GPU workloads, installs or service actions were performed during this refresh.

See [the update](SEPTEMBER-14-UPDATE.md) for successful new-kernel CUDA/display/clean-cycle evidence and the intermittent reboot failure. LACT installation/live validation remains unconfirmed. Historical milestones above refer to their original kernel versions.

## September 15 regression update

All 27 bundled tests pass, including five new package-query tests. Startup repair was live-verified on Arch; Blender enumerated RTX 4090 CUDA/OptiX and the owner confirmed restored operation. See [incident details](SEPTEMBER-15-PACKAGE-QUERY-FIX.md).

## September 15, Arch 7.2.6 and tray telemetry

The sensitive update hooks completed; the first boot revealed an old kernel-name dispatch bug that left only core/UVM loaded. After the registry dispatch correction, all four modules loaded, LACT initialized both GPUs, HDMI was enabled through Plasma, and 256 CUDA results passed. The owner reported working operation. Cold-boot activation after the correction and a separately documented physical reconnect cycle remain unconfirmed. A live tray menu test showed GPU utilization and power. Latest portable checks: 27 bundle unittest cases, 34 update-support cases (private inventory test omitted), 3 original tray cases, plus the telemetry parsing/eject-order assertions. See [details](SEPTEMBER-15-UPDATES-AND-TELEMETRY.md).
