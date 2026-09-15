# What remains for disconnect without an eject action

The current solution makes **connection and boot activation automatic**. It makes planned disconnection safe by releasing clients and unloading drivers **before** the cable is removed. It does not make an unexpected physical removal safe.

## Observed failure and limits of the evidence

Physical removal while the NVIDIA display stack was active froze the desktop and required a forced shutdown. The investigation recorded GPU loss/Xid79 and a display framebuffer-cleanup fault consistent with a use-after-free during teardown. Earlier initialization resets also occurred, but those were a separate failure class; the proprietary/non-GSP configuration addressed initialization in the successful tests.

A candidate with display-side changes activated and survived a 60-second observation. **Its surprise-removal and reconnect behavior was never validated.** Review identified unresolved teardown ordering and object-lifetime concerns. It is deliberately not shipped as the working driver or presented as a successful patch.

The fact that this enclosure works with surprise disconnect on Windows is the owner's useful comparison. It does not establish that the tested Linux NVIDIA/KWin combination implements equivalent behavior.

## Why an automatic post-unplug script is insufficient

By the time a physical removal event reaches a userspace script, the GPU may already be inaccessible and the kernel may already be handling interrupts, rendering operations, pending fences or object teardown. Replaying the clean-eject procedure after this point cannot guarantee safety. A userspace service cannot reliably predict someone pulling a USB4 cable.

The root cause needs safe handling of disappearance in the driver/display stack, not a PCI rescan or forced module unload. Do not describe automatic recovery after a fault as equivalent to preventing the fault.

## Required engineering work

1. **Surprise-removal-safe driver teardown.** Quiesce hardware access and callbacks when the device is gone. Complete or fail pending work/fences without infinite waits. Preserve correct ordering between DRM unplug, atomic shutdown and NVIDIA modeset cleanup. Avoid freeing per-device objects while open DRM file descriptors, framebuffer cleanup, callbacks or queued work can still reference them. These are investigation targets, not a reviewed patch specification.
2. **Compositor/client behavior.** Verify KWin/logind/Xwayland release a vanished secondary GPU without blocking the AMD desktop. Test applications that hold CUDA, graphics, video or monitoring handles; a GPU process may need to receive a clean device-lost error rather than continue running.
3. **Re-add after true loss.** Safely retire the disappeared device and allow a fresh instance on reconnect, including changed BDFs, without forced unload, stale state reuse or PCI recovery loops. Existing clean-eject reconnect does not prove this case.
4. **Power and service races.** Keep the root/GPU/HDA policy correct across add/bind/remove, coordinate loader/eject requests, and account for monitoring tools such as LACT. Rapid connector changes must not trigger concurrent initializations.
5. **Reproducible tests with diagnostics.** Preserve an AMD-only fallback and persistent crash evidence. Validate many boot, attach, clean-eject and surprise-removal cycles; include active scanout, CUDA transfers, idle, application-held handles, both USB4 roots, and suspend/resume. Another hard reset is a hardware-test stop, not permission for an automatic retry loop.

A future verified driver/desktop fix may remove the need for the tray's eject action. There is no demonstrated source patch or settings-only change in this investigation that makes surprise unplug safe.

## Other work before calling it fully integrated

- Package the private proprietary builds with trustworthy provenance and appropriate vendor licensing; rebuild for every new kernel ABI and matching userspace version.
- Make upgrades transactional and preserve a tested boot fallback. Current exact-version guards intentionally refuse unsupported updates.
- Generalize account paths and machine checks without weakening the root helper; provide a reviewed installation/rollback path and root-owned code/dependencies.
- CachyOS7.2.5 display output and clean cycles now work with separately built modules. Resolve the intermittent reboot/display-teardown hang described in [the update](SEPTEMBER-14-UPDATE.md).
- Test long-running models/games, suspend/resume, different cables/ports/enclosures, repeated output topology changes, and LACT resumption.
- Measure cycle counts and failure rates. The successful field tests here do not supply a statistical reliability guarantee.

Until then, **use the tray and wait for “Safe to unplug.”**

The September14 reboot failure reinforces that successful clean cycles do not prove reliable device-loss or shutdown teardown. Conditional LACT restoration is staged, not a fix for GPU disappearance.
