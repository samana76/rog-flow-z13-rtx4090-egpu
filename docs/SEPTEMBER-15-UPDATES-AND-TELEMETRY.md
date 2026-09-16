# Kernel updates, full display startup, LACT and tray telemetry

## What changed

The working stack is still NVIDIA's unpatched proprietary 615.71.09, GSP disabled and runtime D3 disabled. The new code manages the private module builds and their activation; it does not introduce a new NVIDIA driver.

A normal `pacman -Syu` can now invoke a PreTransaction hook before sensitive package changes. It validates the existing helper integrity, proposed transaction and a retained tested kernel, saves recovery evidence, obtains matching signed kernel headers and builds all four proprietary modules for the target kernel. Builds run as an unprivileged user. A PostTransaction hook checks installed package identities, boot image checksums, initramfs policy and built artifacts before extending the approved build registry. Neither hook loads GPU modules or reboots the computer.

New NVIDIA releases remain blocked for review, as do transactions replacing both tested kernels. This is deliberately scoped to the tested Arch/CachyOS setup and normal full-system pacman transactions. It does not promise compatibility with every future kernel. A successful post-update check establishes build/installation consistency, not runtime stability; a reboot and hardware validation still matter. A post-transaction failure cannot retroactively cancel installed packages, so its instruction to review before rebooting is significant.

The initramfs check initially rejected the mere presence of nouveau. That was a script false positive: a module can be embedded but blocked. The corrected check extracts the image as an unprivileged user and inspects effective modprobe policy and dry-run dependencies. It accepts harmless dependency insertions only when the target driver is blocked, and rejects forced early loading. It never loads the inspected modules.

## The missing-display regression and correction

Arch was updated from 7.2.4 to 7.2.6-arch2-1. The newly built core and UVM modules loaded, and nvidia-smi saw the 4090, but LACT saw only AMD and there was no NVIDIA video output. The cause was an overlooked shell dispatch list: only the two old kernel names reached the display loader; every other kernel reached the compute-only loader.

The entrypoint now verifies the registry reader and display helper, rejects unregistered kernels, and routes **every registered kernel through the full compute/display loader**. The reconnect helper's entrypoint hash and the update manager's integrity manifest were updated together. The existing working core was verified rather than reloaded, then the missing modeset and DRM stages completed. LACT was refreshed and initialized both GPUs.

Plasma still had the connected HDMI output disabled. Its layout was backed up and the output enabled through kscreen-doctor without changing the saved position or mode. DRM and NVML then reported active output. A bounded CUDA kernel verified all 256 results and completed normal cleanup on Arch 7.2.6. No new kernel errors appeared in the inspected validation interval, and the owner reported it working. The brief owner confirmation does not establish a separate measured eject/reconnect cycle or cold-boot validation of the corrected routing.

LACT's earlier vulkaninfo child crashed during incomplete activation. No recurrence appeared in the inspected post-restart log. A clock-table reset error during daemon shutdown and a client broken pipe were also recorded; successful rediscovery is not a claim that every LACT warning has been resolved.

## LACT restoration after clean eject

The deployed reconnect helper now restores lactd only when the recorded clean-eject operation previously paused it. A service the user independently left stopped is not automatically enabled. The former `pending-lact/` files remain historical references; the current deployed logic is in `reference-system/opt/gpd-egpu/auto/restart-clean-cycle.py`.

## Tray GPU and power indicators

The top of the native KDE tray menu now shows a row such as:

    GPU: 35%   |   Power: 123.5 W

An asynchronous nvidia-smi query samples utilization.gpu and power.draw every three seconds and on menu opening, selecting the discovered RTX4090 PCI address instead of assuming GPU index 0 or a fixed bus. A two-second timeout cancels stalled queries. Unavailable, unsupported, inactive and disconnected states replace stale readings. Zero utilization means idle, not disconnected; these readings are telemetry, not a complete health or workload test.

Monitoring only queries an already-bound NVIDIA device. When the user requests safe eject, the tray stops and reaps its query process **before** starting the unchanged privileged disconnect helper. It suppresses sampling during eject and after READY TO UNPLUG. This matters because an extra NVML client must not obstruct normal module unloading. No new sudo/polkit privilege is needed. The real Qt menu displayed a live wattage reading, and regression checks cover formatting and query/eject ordering. A physical eject cycle was not performed as part of the UI-only change.

## Still not seamless surprise removal

Use the tray before unplugging. Telemetry and update automation do not fix surprise unplug, the previously observed intermittent reboot/shutdown hang, or establish sustained workloads and suspend/resume reliability. See [seamless-disconnect limitations](SEAMLESS-DISCONNECT.md).

## Source and rollback map

- [Update program, hooks and baseline build registry](../code/automatic-updates/README.md).
- [Current tray source](../code/tray/egpu-tray.py).
- [Current registry-based entrypoint](../code/reference-system/usr/local/sbin/gpd-egpu-start).
- The local routing repair has its own file-only rollback, to be run before the older update-support rollback. It leaves live modules unchanged.
- The local tray rollback restores the saved Python script and restarts the user tray. No root access is required.

Private rollback records, raw journals, vendor archives and compiled driver binaries are not published. Account redaction changes code hashes: original seals/pins are provenance, not directly deployable checksums for the redacted source.
