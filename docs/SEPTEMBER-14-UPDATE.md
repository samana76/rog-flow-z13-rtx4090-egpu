# September 14 update: kernel upgrade, two-kernel integration and remaining failures

This updates the initial Arch-focused report. No new NVIDIA source patches were
needed: the successful driver remains proprietary615.71.09 with GSP off and DPM0.

## Kernel upgrade and fallback

CachyOS was upgraded from7.2.4-1 to7.2.5-1 in a full system update, including
microcode/firmware packages. Arch remained7.2.4-arch1-2; nvidia-utils remained
615.71.09-1. The original loader incorrectly required the installed versions of
both kernels to remain unchanged. It now validates the package for the running
supported kernel, so upgrading CachyOS does not disable the unchanged Arch setup.

Before updating, the process made a recovery snapshot, verified a full boot-file
backup and checked the normal Limine image hashes. Proprietary modules were built
against privately extracted, signature-verified CachyOS7.2.5 headers. The update
plan was checked for exact packages and no removals; package hooks were allowed
to rebuild images, followed by boot checksum validation. A Python/libalpm planner
segfaulted before commit; native pacman planning replaced it, with transaction
hooks rejecting unexpected targets/removals. This was an orchestration failure,
not an eGPU crash. The identified stale lock was cleared only after checks.

Arch was booted and verified first: automatic NVIDIA loading, internal and
external displays, DPM0/GSP0, power pins and tray survived the update. CachyOS was
then booted for a separate temporary driver test, before enabling it permanently.

## CachyOS7.2.5 results and deployed lifecycle

- Core/NVML and UVM initialized with the expected exact-kernel proprietary builds.
- A tiny CUDA kernel produced256 correct results; subsequent60-second idle checks
  retained readable parent/GPU/HDA configuration and successful NVML queries.
- Matching modeset/DRM modules loaded with modeset=1 and fbdev=0. External HDMI was
  enabled at3840x1600. The AMD internal display remained available.
- The tray eject helper was extended to this kernel without changing its client
  checks, synthetic DRM notification, or normal module unload sequence.
- The owner confirmed planned physical disconnect and automatic reconnect.
  Service logs also recorded successful first activation and clean-cycle restart.
- Boot-time automatic activation was observed on CachyOS7.2.5. However, a later
  reboot after several cycles encountered the failure below.

The loader, display payload selector, dispatch wrapper, automatic activation and
clean-cycle restart now support Arch7.2.4 and CachyOS7.2.5. Old CachyOS7.2.4
compute artifacts remain historical evidence, not modules for the new kernel.
CachyOS7.2.5 has NOT received the older kernels' bounded60-round CUDA workload
validation; do not generalize its tiny-kernel result to sustained workloads.

An integration installer hit EXDEV while archiving eject history from /var/lib
to /root. It restored helper files but retained task-created module copies.
The correction validates and resumes that partial state using the ORIGINAL
rollback baseline; history is archived beside its source on the same filesystem.
Every installation layer retains its own reverse-order rollback. Do not run an
older layer's undo against later modified helper hashes.

## Intermittent reboot failure — not solved

Previous-boot logs show this local-time sequence:

| Time | Observation |
|---|---|
|00:58:37|Automatic reconnect completed|
|00:58:46|System began rebooting|
|00:58:47|PCIe link down; Thunderbolt dock disconnected|
|00:58:48|NVIDIA Xid79: GPU has fallen off the bus|
|00:58:49 onward|DRM framebuffer/cleanup warnings and repeated NVIDIA GPU-progress errors|
|Later shutdown|Plasma Login Manager and plasmashell timed out stopping|

Earlier tray-eject invocations were followed by NVIDIA flip-event timeouts even
though subsequent reconnects succeeded. The final failure trace includes
nv_drm_dev_unload, nv_pci_remove_helper and PCIe hotplug link-change handling.
The dock re-enumerated on another USB4 domain while shutdown was pending.

This is evidence of device disappearance with an active NVIDIA display stack and
problematic teardown. It does NOT establish why the link dropped, whether cable
movement was involved, or whether cycle count caused it. Several earlier reboots
worked. No repair/recovery was attempted during the read-only audit. This failure
was not a bootloader checksum problem.

Until investigated further, safely eject using the tray, wait READY TO UNPLUG,
physically disconnect, then reboot. Surprise unplug remains unsafe. Automatic
connected boot is useful and observed; reliable shutdown under all tested
connection histories is not established.

## Conditional LACT restoration — staged, not yet live-confirmed

The eject helper stops lactd.service only when LACT holds GPU handles. Previously
it stayed paused after reconnect. LACT's GUI can still enumerate GPUs in standalone
monitoring mode; its 'not connected' label refers to the daemon, not GPU presence.

The staged change in code/pending-lact starts LACT once only when:

1. The same completed eject cycle recorded lact_paused=true.
2. GPU/display reconnect and its checks completed successfully.
3. LACT is currently inactive.

It leaves active services alone, does not retry a failed service, and logs a LACT
start failure separately from GPU success. It does not change authorization,
LACT profiles, boot configuration or the ejection sequence. Starting LACT can
reapply existing LACT settings; those settings are not part of this bundle.
Six unit tests passed, but installation and service lifecycle testing have not
been confirmed. This applies to either supported kernel once installed. It does
not retroactively start a daemon paused during an unrelated earlier cycle.
