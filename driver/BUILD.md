# NVIDIA driver provenance and build reproduction

The successful driver has **no local NVIDIA source patch**. It is the proprietary `kernel/` tree from NVIDIA 615.71.09, not `kernel-open/`. The working change is selecting that driver path, loading it with GSP off/DPM0, and coordinating power/display lifecycle.

Official archive recorded by the investigation:

[Download NVIDIA-Linux-x86_64-615.71.09-no-compat32.run](https://download.nvidia.com/XFree86/Linux-x86_64/615.71.09/NVIDIA-Linux-x86_64-615.71.09-no-compat32.run)

Recorded SHA256:

```text
e5545862c291f3991a91ee40dd9c7a71cccc69247a193d5e5b891bfd964ac104
```

This is recorded historical provenance, not a fresh vendor-signature or availability check. Check the download against trusted vendor information before executing its extraction stub. NVIDIA's original license text is included in `../licenses/NVIDIA-Driver-LICENSE.txt`; NVIDIA code is not relicensed by this bundle.

## Build without installing

Use a normal build workspace. Obtain the exact kernel build headers/configuration and a compatible toolchain. The investigation extracted matching Arch headers privately; it did not replace the preferred kernel to satisfy a driver dependency. Do not substitute a different kernel's build tree just because the driver version matches.

After verifying the vendor archive, run **only its `--extract-only` mode** and work in the extracted proprietary `kernel/` directory. Do not run `nvidia-installer` as a side effect of reproduction.

Recorded CachyOS build:

```bash
make -j8 modules \
  SYSSRC=/usr/lib/modules/7.2.4-1-cachyos/build \
  SYSOUT=/usr/lib/modules/7.2.4-1-cachyos/build \
  KERNEL_UNAME=7.2.4-1-cachyos \
  LLVM=1 CC=clang LD=ld.lld
```

Recorded Arch build, using a private exact-version header tree:

```bash
# Set EGPU_HEADERS to your verified 7.2.4-arch1-2 build directory first.
make clean SYSSRC="$EGPU_HEADERS" SYSOUT="$EGPU_HEADERS" \
  KERNEL_UNAME=7.2.4-arch1-2 CC=gcc LD=ld
make -j8 modules SYSSRC="$EGPU_HEADERS" SYSOUT="$EGPU_HEADERS" \
  KERNEL_UNAME=7.2.4-arch1-2 CC=gcc LD=ld
```

Check `modinfo -F version`, `modinfo -F vermagic`, `modinfo -F license`, and `modinfo -F srcversion` for each result before considering a separate guarded test. `nvidia.ko` reported license `NVIDIA`. Core/UVM from both kernels and modeset/DRM from Arch are recorded in `tested-artifacts.json`. Builds can produce different binary hashes when build paths/toolchains differ; that is not permission to bypass a kernel ABI check.

The successful deployment keeps private modules under `/opt/gpd-egpu/615.71.09/<kernel>/` and the Arch display payload under `/opt/gpd-egpu/display-extension/display-payload/`. It loads explicitly through guarded code rather than replacing module-tree files. NVIDIA/nouveau modalias loading remains blocked to avoid initializing the wrong module flavor first.

Core initialization passes both:

```text
NVreg_DynamicPowerManagement=0
NVreg_EnableGpuFirmware=0
```

UVM and display modules must match the core and running kernel. The tested display settings are `modeset=1 fbdev=0`. **These are a description of the guarded sequence, not an instruction to insert modules into an unknown live system.** Read the full report and adapt all preconditions first.

Exact tested local `.ko` copies are retained separately from the public source archive. They are not portable modules for arbitrary future Arch kernels. Driver source distribution and reuse remain governed by NVIDIA's terms.

## CachyOS7.2.5 build added September14

The same unpatched proprietary vendor archive was built against a private extraction of the signature-verified `linux-cachyos-headers 7.2.5-1` package:

```bash
# EGPU_HEADERS points to that exact extracted kernel build directory.
make -j8 modules SYSSRC="$EGPU_HEADERS" SYSOUT="$EGPU_HEADERS" \
  KERNEL_UNAME=7.2.5-1-cachyos LLVM=1 CC=clang LD=ld.lld
```

All four resulting modules are recorded in `tested-artifacts.json`. Tiny CUDA, NVML, display output and clean eject/reconnect passed; this does not resolve the intermittent shutdown failure. The production display path for this kernel is `/opt/gpd-egpu/display-extension/display-payload-7.2.5-1-cachyos/`. The Arch display path remains unchanged.
