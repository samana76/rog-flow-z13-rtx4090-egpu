> Updated scope: see [September14 follow-up](SEPTEMBER-14-UPDATE.md) for deployed CachyOS7.2.5 support, upgrade handling, LACT staging and the unresolved reboot hang.

# What was tried, what worked, and how the working system is arranged

This is the final sequence distilled from the recorded attempts. Historical trial instructions and failed candidates should not be replayed indiscriminately.

## 1. Establish a recoverable baseline

Record the laptop, BIOS, running kernel, installed packages, kernel command line, module options, udev rules and boot configuration. Keep a pre-change root snapshot plus copies of modified files and exact package records. Preserve a working internal-AMD boot option. A Btrfs root snapshot alone does not necessarily back up a separate `/boot` or the user's home subvolume.

The BIOS was already 314. The original kernel target was 7.2.2; after the owner's kernel updates, the target became **7.2.4-arch1-2**. Do not confuse that older target or its module packages with the eventual successful build. The existing `amdgpu.dcdebugmask=0x40600` was preserved. G-Helper, ASUS support services and their udev rule were kept.

The working implementation did not depend on `pcie_aspm=off`, `pcie_ports=native`, `pci=realloc`, link-speed forcing, Thunderbolt host-controller rebinding, PCI remove/rescan loops, or automatic recovery after an inaccessible device.

## 2. Apply and verify the platform power policy

Install the narrow root/GPU/HDA rule in `/etc/udev/rules.d/99-usb4-tunnel-ports-awake.rules`; the included `config/` copy reflects the working policy. The two laptop-specific USB4 tunnel roots are:

- `0000:00:01.1`
- `0000:00:01.2`

Both must have `power/control=on`. Detect the GPU by PCI vendor/device/display class, then discover its parent through the real sysfs path. The GPU appeared behind either root; its BDF is not constant. Verify that the immediate downstream parent is the expected JHL9480 when applying this machine-specific procedure.

Pin the NVIDIA display function and same-slot HDA function too. The initial GPU pin worked while HDA still read `auto`; this was a real policy gap. The final udev rule covers **add and bind** for NVIDIA display/HDA, and the controlled loader verifies/applies the required policy before driver initialization. A sound-driver bind must not leave HDA unpinned.

Normal udev coldplug is the persistent mechanism. An early installer incorrectly required the USB4 rule inside initramfs. That requirement was removed; no custom initramfs hook or forced FILES entry was necessary. An unused port's historical `runtime_suspended_time` need not be zero. Require `power/control=on` after processing and record runtime status/time diagnostically.

The GPU need not enumerate before the root-port fix is installed. That earlier guard was circular and was removed. Enumeration waits are bounded at 90 seconds. Read parent/GPU PCI configuration before initialization: all-FF, short/invalid reads or header type 7f stop the attempt without recovery.

## 3. Make DPM0 actually win

The persistent override is:

```conf
# /etc/modprobe.d/zz-nvidia-egpu.conf
options nvidia NVreg_DynamicPowerManagement=0
```

Inspect every modprobe configuration source because later-sorting distribution options can override earlier ones. `modprobe -c` is useful but not authoritative. After loading, read:

```text
/proc/driver/nvidia/params
DynamicPowerManagement: 0
```

In the final private loader, options are also passed explicitly when loading the proprietary core. The successful live parameters include:

```text
DynamicPowerManagement: 0
EnableGpuFirmware: 0
```

Do not treat `Runtime D3 status: Not supported` as enabled runtime D3. An early check was too strict about the wording. Unknown status remains unknown; it does not justify claiming that DPM is disabled. The live parameter and actual device power policies remain mandatory.

## 4. Separate driverless tunnel behavior from NVIDIA initialization

The first stock-open attempt targeted cached prebuilt `nvidia-open 610.57.04-16` and `nvidia-utils 610.57.04-1`, with required EGL dependencies permitted. Existing OpenCL userspace packages were not evidence of kernel-driver contamination. Neither firmware nor stock modules such as `nvidia-wmi-ec-backlight` should trip a clean-state check; match exact NVIDIA display-driver module stems instead.

Automatic NVIDIA/nouveau loading was then gated with narrowly scoped blacklist/install-false rules, preserving the AMD desktop. The controlled test could observe a readable JHL9480/GPU tunnel for 60 seconds before making a single explicit NVIDIA initialization attempt. Dependencies listed by `modprobe -n` do not mean the blocked target itself will load; an overly broad dry-run parser was corrected.

Stock-open and later patched-open 615 trials produced hard resets. The next boot reported:

```text
Previous system reset reason [0x08000800]: an uncorrected error caused a data fabric sync flood event
```

Saved checkpoints placed failures around first NVML initialization or private core loading. They identify the last recorded operation, not the defective component. Switching from stock Arch to CachyOS did not by itself eliminate the patched-open reset. No dangerous PCI recovery was attempted.

## 5. The successful change: proprietary driver, GSP off

NVIDIA's **615.71.09 proprietary kernel directory** was extracted from the official `.run` distribution and built privately, without running the installer. No source patches were applied to this successful build. The proprietary path permits this Ada test with `NVreg_EnableGpuFirmware=0`; the open-driver path was not the successful configuration.

CachyOS used its matching Clang/LLVM build environment; stock Arch used its exact kernel build tree and GCC. See `driver/BUILD.md`. Modules were kept outside `/usr/lib/modules`, initially in private trial directories and later under `/opt/gpd-egpu/615.71.09/<kernel>/`. Userspace was matched to `nvidia-utils 615.71.09-1`.

The core was loaded once with DPM0/GSP0. Verification required readable PCI configuration, live parameters, `nvidia-smi -L`, full `nvidia-smi`, then another PCI/NVML check after at least 60 seconds idle. `GSP Firmware Version: N/A` was additional observed evidence alongside live `EnableGpuFirmware: 0`.

This succeeded first on CachyOS and then on Arch. It supports the combined proprietary/non-GSP configuration as the practical workaround here. It does **not** prove that GSP alone, rather than the changed driver path or another coupled factor, caused every prior reset.

## 6. Verify CUDA before claiming compute works

Load the matching private `nvidia-uvm.ko` after verifying core/UVM version, kernel ABI and source-version identities. The first Arch smoke runner failed on its own guarded-directory assumption before CUDA execution; this was corrected without reloading the already healthy modules.

The successful tiny test used the CUDA Driver API through Python ctypes and the installed CUDA driver library. It created a context, allocated a small buffer, transferred data, loaded a PTX kernel, launched it, synchronized, copied results back and verified **256 results**, then released resources. No PyTorch or CUDA toolkit installation was needed for that validation.

The next test reused a 64-MiB allocation for **60 upload/kernel/download rounds**, paced over about 120 seconds, verifying results. That is about **7.5 GiB total host/device transfers**, with duty-cycle gaps—not a maximum-power stress benchmark. Afterward, PCI configuration and NVML remained healthy following another 60 seconds idle, and the inspected trial journal had no fatal GPU errors. Both tested kernels passed these bounded compute checks. The historical child code is included for review, not as a standalone automatic stress launcher.

## 7. Enable external display output

Working CUDA/NVML alone does not create a display output. For the validated Arch build, load matching proprietary `nvidia-modeset.ko` and `nvidia-drm.ko` after the compute core, using the tested DRM settings:

```text
modeset=1
fbdev=0
```

The display guard verifies core, UVM, modeset and DRM identities, checks that the internal AMD panel remains available, and then allows KWin to use the NVIDIA output. The owner confirmed external video. This is different from deliberately moving the entire desktop compositor onto the eGPU.

The initial display payload was for **Arch7.2.4-arch1-2**. The updated bundle also contains separately built and tested **CachyOS7.2.5-1** display modules. Neither payload can be substituted for the other kernel. Do not mix module flavors or kernel builds.

## 8. Persist startup without replaying failed trials

The final installed chain is:

```text
systemd/udev activation
  -> /opt/gpd-egpu/auto/auto-start.py
  -> /usr/local/sbin/gpd-egpu-start
  -> compute loader + Arch display extension
```

The service is enabled for boot, and a narrow NVIDIA add rule requests it on connection. This operational service is distinct from the old diagnostic postboot verifier, which remains disabled. The service uses `Type=oneshot` and `Restart=no`; persistent failure markers prevent crash/retry loops. Kernel, BIOS, module hashes and userspace version are checked. Unsupported updates require rebuilding and revalidation.

Three diagnostic 60-second sleeps initially delayed video startup. They were removed from operational activation **after the corresponding tests passed**, retaining immediate safety checks. The owner then confirmed that external video came up promptly during boot. No automatic rebuild-on-kernel-update hook was established for this private proprietary loader.

Boot-integrity lesson: an early rebuild left Limine checksum fields inconsistent with the actual normal initramfs files. The normal boot problem was repaired by correcting only the measured checksum fields, not by blindly restoring a snapshot. Future packaging must update images and boot metadata coherently and preserve the normal AMD-capable entry.

## 9. Handle disconnect before removing the cable

Direct unplug while the NVIDIA display stack was active froze the desktop. The reliable sequence was implemented in a root-owned, no-arguments helper:

1. Take the shared loader/eject lock and validate the known working device/module state.
2. Confirm the internal AMD panel is available and the PCI devices remain valid.
3. Find processes holding the GPU device nodes. Unrelated GPU applications block eject; do not kill them automatically.
4. If LACT is an actual GPU client, verify its service identity and temporarily stop `lactd.service` so it cannot reopen the GPU.
5. Send synthetic **DRM userspace removal notifications** for the GPU card/render nodes so KWin, Xwayland, logind and other session users can release their handles. This is not a PCI device remove/rescan operation.
6. Wait a bounded interval for all GPU clients to release handles. Do not waive the final check just because a process is a session component.
7. Normally unload `nvidia_drm`, `nvidia_modeset`, `nvidia_uvm`, then `nvidia`, checking holders/reference state. No forced unload.
8. Record successful completion and report **READY TO UNPLUG**. Only then physically remove USB4.

The owner confirmed the internal desktop remained usable after that physical removal. LACT was left paused during the tested eject/reconnect cycle; conditional post-reconnect restoration is now staged separately, with live testing still pending.

## 10. Reconnect and tray integration

A same-boot restart first verified that clean eject had completed and all modules had unloaded. It archived the completed per-boot records rather than erasing crash evidence, then called the original loader. This passed. The automatic reconnect extension recognizes a completed clean-eject cycle and performs the same guarded restart when the enclosure is reattached. Failed or interrupted cycles stay locked out. The owner confirmed automatic reconnect worked.

The tray calls only `/usr/bin/pkexec /usr/local/libexec/gpd-egpu-eject`. A narrowly scoped polkit rule authorizes this exact root-owned helper for the selected active local desktop account; it is not passwordless sudo or permission to run arbitrary commands. The helper rejects arguments and retains its own checks. Replace `EGPU_USER` deliberately when adapting the reference rule.

Qt's generic tray left-click popup failed under Wayland. An XWayland workaround still did not resolve the user's experience. The final tray uses **KDE KStatusNotifierItem with `setIsMenu(true)`**, exporting the QMenu for Plasma to display. Plasma reported `ItemIsMenu=true`; the owner confirmed left-click works. The C++ bridge and Python source are included. KDE documents this behavior in its [KStatusNotifierItem API](https://api.kde.org/kstatusnotifieritem.html).

The user-session launcher/autostart brings the icon back at login; searching the application launcher for “GPD eGPU tray” reopens it after quitting. The standalone disconnect app was removed while keeping the shared helper. Left-click -> Disconnect safely -> wait for Safe to unplug remains required.

## 11. Rollback and cleanup

Each implementation layer retained exact created-file hashes and its own undo records; none should remove kernels or unrelated ASUS/AMD software. The later UI removal must be undone before older UI rollback layers that expect those files. Ordinary driver unload and filesystem rollback are different operations; do not attempt a rollback to recover all-FF hardware.

After successful use, historical workspace experiments were archived with per-file verification before deleting their originals. Only selected experiment snapshots were deleted; pre-test baselines, the Btrfs default snapshot, installed kernels and a new current recovery snapshot were retained. Root rollback dependency chains and working runtime/crash-lock records were preserved. Cleanup is not part of reproducing the driver fix.
