#!/usr/bin/env python3
"""Manual compute-only loader. One initialization attempt per boot; no recovery."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

KERNEL = os.uname().release
BUILDS = {
    '7.2.5-1-cachyos': ('7ed66460ba04c99f45113d0e7de293810594aeb4fc70ab19bc834dc158344121', '9f7c3c79b3ed9438164849ba39df728e5105b9907883ecb4125377a3df3d5e0f'),
    '7.2.4-1-cachyos': ('f1a9c9e550d56242741d73503c1b996d4642725c0a2ef9fcca345f90c8c774e3', '4b9ab4a30c9cd1b9aa9f7a8994bed769a269539b647b5ae19af42aa62cf5d3a1'),
    '7.2.4-arch1-2': ('5bc38891199988d253af1112c4e104a44bf97dd07c24fb316d550b70c4b12869', '1afb65e395d1a6eb2aa35f1961f86861e954be7b617784d19a77167824b7d135'),
}
ROOT = Path('/opt/gpd-egpu/615.71.09')/KERNEL
STATE = Path('/var/lib/gpd-egpu-loader')
CORE, UVM = BUILDS.get(KERNEL, ('unsupported', 'unsupported'))
GUARD = '02ca6d1cd28371c0e05335e102476b406843dc1639731b01f6d3e19f801ab497'

def startup_action(record, core, uvm):
    if record is not None and record.get('stage') != 'completed':
        raise RuntimeError('A loader attempt already failed or was interrupted this boot; no retry')
    if core and uvm:
        return 'verify'
    if core or uvm or record is not None:
        raise RuntimeError('Partial or changed driver state; no reload/recovery')
    return 'load'

def guard():
    if KERNEL not in BUILDS:
        raise RuntimeError('Untested kernel; matching private modules must be built and validated first')
    p = ROOT.parent/'guard.py'
    if hashlib.sha256(p.read_bytes()).hexdigest() != GUARD:
        raise RuntimeError('Guard library checksum changed')
    spec = importlib.util.spec_from_file_location('gpd_guard', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def boot_check(t, m):
    entries = m.menu_entries(Path('/boot/limine.conf').read_text())
    for title in ('//linux', '//linux-cachyos'):
        selected = [e for e in entries if e['title'] == title]
        m.require(len(selected) == 1, 'Missing/ambiguous normal boot entry: '+title)
        for key in ('path', 'module_path'):
            path, expected = m.boot_resource(selected[0][key])
            m.require(m.digest(path, 'blake2b') == expected, 'Boot checksum mismatch: '+str(path))
    t.log('Normal Arch fallback and CachyOS boot resource checksums match; no boot files changed')

def required_packages(kernel):
    # Validate only the package supplying the running supported kernel.
    # Updating a different installed kernel must not disable Arch eGPU startup.
    kernel_packages = {
        '7.2.5-1-cachyos': ('linux-cachyos','7.2.5-1'),
        '7.2.4-arch1-2': ('linux', '7.2.4.arch1-2'),
        '7.2.4-1-cachyos': ('linux-cachyos', '7.2.4-1'),
    }
    if kernel not in kernel_packages:
        raise RuntimeError('Unsupported running kernel; build and validate its modules first')
    return [('nvidia-utils', '615.71.09-1'), kernel_packages[kernel]]

def query_package(t, name):
    import subprocess
    t.log('Package identity query: '+name)
    result = subprocess.run(['pacman','-Q',name], capture_output=True, text=True, timeout=30)
    t.log('pacman stdout: '+result.stdout.strip())
    if result.stderr:
        t.log('pacman stderr: '+result.stderr.strip())
    if result.returncode != 0:
        raise RuntimeError('Package query failed: '+name)
    return result.stdout.strip()

def identity(t, m):
    m.require(os.uname().release in BUILDS, 'Unsupported kernel')
    m.require('GZ302EA' in t.read('/sys/class/dmi/id/product_name'), 'Wrong laptop')
    m.require(t.read('/sys/class/dmi/id/bios_version') == 'GZ302EA.314', 'BIOS changed; review compatibility')
    cmd = t.read('/proc/cmdline')
    m.require('amdgpu.dcdebugmask=0x40600' in cmd.split(), 'AMD command line changed')
    m.require(not any(s in cmd for s in ('pcie_aspm=off','pcie_ports=native','pci=realloc','thunderbolt.host_reset=0','thunderbolt.host_reset=false')), 'Unexpected PCI/USB4 command line')
    for name, version in required_packages(os.uname().release):
        m.require(query_package(t, name) == name+' '+version, 'Kernel/driver package changed; private modules need review/rebuild')
    for name, expected in [('nvidia.ko',CORE),('nvidia-uvm.ko',UVM)]:
        m.require(m.digest(ROOT/name) == expected, 'Module file changed: '+name)
        m.require(t.run(['modinfo','-F','vermagic',str(ROOT/name)]).split()[0] == KERNEL, 'Module kernel mismatch')
    m.validate_gate(m.GATE.read_text())
    m.require(not any(Path('/sys/module', x).exists() for x in ('nvidia_drm','nvidia_modeset','nouveau','nvidia_peermem')), 'Unexpected display/other NVIDIA modules; no unbinding')
    m.require(t.run(['systemctl','is-enabled','egpu-postboot-verify.service'],check=False).strip() in ('disabled','masked'), 'Old automatic verifier is enabled')
    m.require(t.run(['systemctl','is-active','egpu-postboot-verify.service'],check=False).strip() == 'inactive', 'Old automatic verifier is active')
    boot_check(t,m)

def live(t, m):
    m.require(t.read('/sys/module/nvidia/srcversion') == '329D97755EFA31D5314E8F0', 'Loaded core differs from tested build')
    params = t.read('/proc/driver/nvidia/params')
    m.parse_dpm(params)
    m.require(re.findall(r'^EnableGpuFirmware:\s*(\S+)\s*$',params,re.M) == ['0'], 'GSP-disable option did not win')

def find_gpu(t, m, wait):
    end = time.monotonic()+(90 if wait else 0)
    while True:
        devices = t.devices()
        m.require(len(devices) <= 1, 'Multiple NVIDIA display devices')
        if devices:
            gpu = devices[0]
            break
        m.require(wait and time.monotonic() < end, 'GPU absent; connect/power enclosure before a future boot attempt; no rescan')
        time.sleep(min(1,max(0,end-time.monotonic())))
    parent = Path('/sys/bus/pci/devices')/gpu.resolve().parent.name
    for p in (parent,gpu):
        t.pci(p.name)
    m.require(t.read(gpu/'device') == '0x2684', 'Not the tested RTX4090')
    m.require(t.read(parent/'vendor') == '0x8086' and t.read(parent/'device') == '0x5786', 'Not the tested JHL9480 parent')
    m.require(any(p in gpu.resolve().parts for p in m.PORTS), 'Unexpected USB4 topology')
    hda = [p for p in Path('/sys/bus/pci/devices').glob(gpu.name.rsplit('.',1)[0]+'.*') if (p/'vendor').read_text().strip() == '0x10de' and (p/'class').read_text().strip() == '0x040300']
    t.state.update(gpu_bdf=gpu.name,parent_bdf=parent.name,realpath=str(gpu.resolve()))
    return gpu,parent,hda

def nvml(t,m):
    query = t.run(['nvidia-smi','-q'])
    m.require(re.findall(r'^\s*GSP Firmware Version\s*:\s*(.+)$',query,re.M) == ['N/A'], 'GSP not confirmed disabled')

def main():
    if os.geteuid() != 0:
        raise SystemExit('Run sudo gpd-egpu-start')
    if sys.argv[1:]:
        raise SystemExit('No recovery, retry or automatic mode exists')
    os.umask(0o077)
    lock = open('/run/lock/gpd-egpu-loader.lock','a')
    fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
    m = guard()
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    m.PRIVATE = STATE/boot
    m.LOGDIR = Path('/var/log/egpu-autoconfig/loader')/boot
    t = m.Trial()
    try:
        identity(t,m)
        existing = json.loads((m.PRIVATE/'attempt.json').read_text()) if m.PRIVATE.exists() else None
        action = startup_action(existing,Path('/sys/module/nvidia').exists(),Path('/sys/module/nvidia_uvm').exists())
        if action == 'load':
            m.PRIVATE.mkdir(parents=True,mode=0o700)
            t.owned = True
            import datetime
            t.state['journal_since'] = datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')
            t.checkpoint('manual-attempt-started')
            for b in m.PORTS:
                t.pin(Path('/sys/bus/pci/devices')/b)
            t.log('Waiting up to90seconds for powered enclosure; display activation follows compute initialization')
            gpu,parent,hda = find_gpu(t,m,True)
            m.require(not (gpu/'driver').exists(), 'GPU already bound')
            t.run(['udevadm','settle','--timeout=10'])
            for p in (gpu,*hda):
                t.pin(p)
            t.start_follow()
            t.checkpoint('driverless-immediate-check')
            t.check_link(gpu,parent,hda)
            t.check_errors()
            t.checkpoint('before-private-core-load')
            os.sync()
            t.run(['insmod',str(ROOT/'nvidia.ko'),'NVreg_DynamicPowerManagement=0','NVreg_EnableGpuFirmware=0'],timeout=45)
            end = time.monotonic()+10
            while not (gpu/'driver').exists() and time.monotonic() < end:
                t.pci(parent.name); t.pci(gpu.name); time.sleep(.25)
            m.require((gpu/'driver').exists() and (gpu/'driver').resolve().name == 'nvidia', 'Core did not bind')
            t.run(['udevadm','settle','--timeout=10'])
            live(t,m)
            t.check_link(gpu,parent,hda)
            t.checkpoint('before-first-nvml')
            os.sync()
            nvml(t,m)
            t.checkpoint('initialized-immediate-check')
            t.check_link(gpu,parent,hda)
            t.check_errors()
            t.checkpoint('before-private-uvm-load')
            os.sync()
            t.run(['insmod',str(ROOT/'nvidia-uvm.ko')],timeout=30)
        else:
            live(t,m)
            gpu,parent,hda = find_gpu(t,m,False)
            if existing:
                m.require(existing.get('realpath') == str(gpu.resolve()), 'GPU topology changed since initialization; no recovery')
            t.log('Already loaded: validating existing driver without reloading')
        m.require(t.read('/sys/module/nvidia_uvm/srcversion') == '064C13389A454AA4AAF638E', 'Loaded UVM differs from tested build')
        t.check_link(gpu,parent,hda)
        live(t,m)
        nvml(t,m)
        if t.owned:
            t.check_errors()
            t.state['result'] = 'READY: proprietary615 DPM0 GSP-off core/UVM compute path'
            t.checkpoint('completed')
        t.log('READY: RTX4090 compute driver loaded; GSP disabled, DPM0, power pins on. Desktop remains on AMD. No model workload tested here.')
    except (Exception,KeyboardInterrupt) as exc:
        t.log('FAIL: '+str(exc)+'; no recovery, unload, reset or automatic retry')
        if t.owned:
            t.state['result'] = 'FAIL: '+str(exc)
            t.checkpoint('failed')
        raise SystemExit(1)
    finally:
        t.stop_follow()

if __name__ == '__main__':
    main()
