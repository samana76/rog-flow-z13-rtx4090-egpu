# Origin and license notices

NVIDIA authored the proprietary driver. Its license is supplied verbatim in NVIDIA-Driver-LICENSE.txt; this bundle does not relicense NVIDIA binaries or source. Vendor download and original tested binary hashes are documented. The successful driver had no local source patch.

Qt, PySide/shiboken and KDE KF6 are external installed dependencies, not bundled/relicensed libraries. The small native-tray.cpp bridge calls the installed KStatusNotifierItem API.

The power-rule approach was informed by djanice1980/eGPU-Blackwell-Stability; its retained commit is recorded in the report. Configuration included here reflects the local working add/bind behavior. Third-party experimental patches are not included or claimed as original work.

The machine-specific orchestration scripts and Markdown report were assembled during the owner/Codex investigation. No new blanket license purporting to cover third-party material is applied. If publishing a repository, select appropriate terms for original contributions separately and preserve applicable third-party notices.
