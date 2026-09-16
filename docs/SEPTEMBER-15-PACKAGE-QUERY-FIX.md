# September 15: connected hardware, unloaded driver

The enclosure was connected and the tray reported a connection, but there was no external video and Blender/LACT did not show the expected usable GPU. This incident was a startup-script false positive, not evidence of another GPU hardware failure.

## Cause

`pacman -Q nvidia-utils` exited successfully and reported the expected `615.71.09-1`. It also printed a warning to stderr that the `openai-chatgpt` repository database was missing. Our general diagnostic command runner merged stdout and stderr. The loader compared that combined text with the exact expected package line and wrongly reported that the kernel/driver package had changed.

The first activation stopped in identity checks before driver initialization. Its persistent `initializing-or-failed.json` marker then prevented another automatic attempt, including after a reboot. A physical connection shown in the tray therefore did not mean the NVIDIA driver had loaded.

## Correction

The loader now uses a dedicated package-query function:

- Capture stdout and stderr separately.
- Log both streams, including warnings.
- Reject nonzero exit codes.
- Continue comparing stdout against the exact expected package name and version.
- Preserve all existing module, kernel, firmware, PCI-validity and power-policy checks.

Changing the loader changes its hash. The display helper's loader hash and the reconnect helper's loader/display hashes were updated as one backed-up change. No NVIDIA binary, package, repository configuration, boot image or kernel was changed.

The machine-specific root repair preserved the original scripts and lockout, verified the known pre-initialization failure and absence of driver attempt state, archived that specific lockout, and requested one normal activation. It did not introduce automatic retries or clear arbitrary failure markers. Rollback is a separate newest layer, to be undone before earlier loader rollbacks; it requires an idle service and unloaded NVIDIA modules.

**Do not delete a failure marker just because a GPU is unavailable.** First establish whether the record is a preflight software error or a genuine interrupted driver/hardware failure.

## Validation and remaining distinction

The existing 22 bundled tests passed. New regression cases exercise clean output, warning-bearing successful output, wrong versions, failed commands, empty output and extra stdout. Syntax and generated rollback Bash checks passed locally. Both original and LACT-restoring reconnect variants were checked for hash propagation in private repair tests.

After the owner ran the staged root repair, the normal activation completed successfully on Arch `7.2.4-arch1-2`. All four NVIDIA modules loaded; live DPM and GSP settings remained zero. `nvidia-smi` detected the RTX 4090. LACT's service was active. A separate factory-default background Blender instance enumerated the RTX 4090 for CUDA and OptiX without rendering or saving preferences.

KDE still had the connected HDMI output disabled. Its settings were backed up and that output was enabled using `kscreen-doctor`. The owner then confirmed it was working. This display-setting correction is separate from the package parser fix; it was not added as an unconditional display-policy change to the loader.

No new CachyOS live test, sustained render, or surprise-removal validation is claimed by this incident. Existing safe-eject requirements and the previously documented intermittent shutdown issue remain.
