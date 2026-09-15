#!/usr/bin/env python3
"""One manual, volatile proprietary-core trial. No installed driver or boot edits."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
PRIVATE = Path('/root/egpu-proprietary-615-trial')
LOGDIR = Path('/var/log/egpu-autoconfig/proprietary-615')
GATE = Path('/etc/modprobe.d/zzz-gpd-egpu-controlled-load.conf')
PORTS = ('0000:00:01.1', '0000:00:01.2')
MODULES = ('nvidia', 'nvidia_uvm', 'nvidia_modeset', 'nvidia_drm', 'nvidia_peermem', 'nouveau')
CORE_SHA = 'f1a9c9e550d56242741d73503c1b996d4642725c0a2ef9fcca345f90c8c774e3'
KERNEL = '7.2.4-1-cachyos'
FATAL = re.compile(r'NVRM:.*(?:Xid|fallen off|RmInitAdapter.*fail)|fallen off the bus|GSP.*(?:timeout|timed out|fatal)|data fabric sync flood|Unable to change power state|Link Down', re.I)

def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)

def digest(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def validate_config(data):
    require(len(data) >= 16, 'PCI config is short or inaccessible')
    require(not all(v == 255 for v in data), 'HARDWARE/TUNNEL FAILURE: all-FF PCI config')
    require(data[14] & 127 != 127, 'HARDWARE/TUNNEL FAILURE: PCI header type 7f')
    require(data[:2] not in (b'\xff\xff', b'\x00\x00'), 'Invalid PCI vendor ID')

def parse_dpm(text):
    values = re.findall(r'^DynamicPowerManagement:\s*(\S+)\s*$', text, re.M)
    require(values == ['0'], 'DPM override did not win: '+repr(values))

def validate_gate(text):
    lines = set(text.splitlines())
    for name in MODULES:
        require('blacklist '+name in lines and 'install '+name+' /usr/bin/false' in lines,
                'Persistent autoload gate is incomplete: '+name)

def menu_entries(text):
    result, current = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('/'):
            current = {'title': s}
            result.append(current)
        elif current is not None and ':' in s and not s.startswith('#'):
            key, value = s.split(':', 1)
            current[key] = value.strip()
    return result

def boot_resource(value):
    match = re.fullmatch(r'boot\(\):(/[^#]+)#([0-9a-f]{128})', value)
    require(match is not None, 'Unsupported/missing Limine checksum: '+value)
    path = Path('/boot') / match[1].lstrip('/')
    require('..' not in path.parts, 'Unsafe boot resource path')
    return path, match[2]

class Trial:
    def __init__(self):
        LOGDIR.mkdir(parents=True, exist_ok=True)
        self.logfile = (LOGDIR/'attempt.log').open('a', buffering=1)
        self.state = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                      'stage': 'preflight', 'power_before': {}, 'private_core_sha256': CORE_SHA}
        self.owned = False
        self.follower = None
        self.follow_output = None

    def start_follow(self):
        fd = os.open(LOGDIR/'kernel-follow.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_DSYNC, 0o600)
        self.follow_output = os.fdopen(fd, 'wb', buffering=0)
        self.follower = subprocess.Popen(['journalctl', '-k', '-b', '-f', '--since', self.state['journal_since'], '-o', 'short-monotonic'], stdout=self.follow_output, stderr=subprocess.STDOUT)

    def stop_follow(self):
        if self.follower is not None:
            self.follower.terminate()
            try:
                self.follower.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.follower.kill()
        if self.follow_output is not None:
            self.follow_output.close()

    def log(self, text):
        line = datetime.datetime.now(datetime.timezone.utc).isoformat()+' '+str(text)
        print(line, flush=True)
        self.logfile.write(line+'\n')
        self.logfile.flush()
        os.fsync(self.logfile.fileno())

    def run(self, args, timeout=30, check=True):
        self.log('$ '+repr(args))
        with tempfile.TemporaryFile(mode='w+') as output:
            process = subprocess.Popen(args, text=True, stdout=output, stderr=subprocess.STDOUT)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass  # Never wait indefinitely for an uninterruptible GPU ioctl.
                output.seek(0)
                self.log(output.read())
                raise RuntimeError('Command timed out; no retry: '+repr(args))
            output.seek(0)
            text = output.read()
        self.log(text)
        self.log('exit='+str(process.returncode))
        if check:
            require(process.returncode == 0, 'Command failed: '+repr(args))
        return text

    def read(self, path):
        value = Path(path).read_text().strip()
        self.log(str(path)+' = '+value)
        return value

    def checkpoint(self, stage):
        self.state['stage'] = stage
        target = PRIVATE/'attempt.json'
        temporary = PRIVATE/'attempt.json.tmp'
        with temporary.open('w') as f:
            json.dump(self.state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(target)
        fd = os.open(PRIVATE, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        self.log('CHECKPOINT '+stage)

    def result(self, message):
        self.log(message)
        if self.owned:
            self.state['result'] = message
            self.checkpoint('completed' if message.startswith('PASS') else 'failed')
        output = Path('/home/EGPU_USER/egpu-autoconfig-result.txt')
        if output.exists():
            (LOGDIR/('prior-result-'+str(time.time_ns())+'.txt')).write_bytes(output.read_bytes())
        output.write_text(message+'\nLogs: '+str(LOGDIR)+'\nNo automatic retry or reboot.\n')
        user = pwd.getpwnam('EGPU_USER')
        os.chown(output, user.pw_uid, user.pw_gid)

    def pci(self, bdf):
        path = Path('/sys/bus/pci/devices')/bdf/'config'
        with path.open('rb', buffering=0) as f:
            data = f.read(64)
        self.log(str(path)+' '+data.hex(' '))
        validate_config(data)
        return data

    def devices(self):
        found = []
        for p in Path('/sys/bus/pci/devices').iterdir():
            try:
                if (p/'vendor').read_text().strip() == '0x10de' and (p/'class').read_text().strip().startswith('0x03'):
                    found.append(p)
            except FileNotFoundError:
                continue
        return found

    def pin(self, p):
        self.pci(p.name)
        control = p/'power/control'
        before = self.read(control)
        require(before in ('auto', 'on'), 'Unexpected power policy')
        self.state['power_before'][p.name] = {'value': before, 'realpath': str(p.resolve())}
        self.checkpoint('power-pin-intent-'+p.name)
        if before != 'on':
            self.log('WRITE '+str(control)+' = on')
            control.write_text('on\n')
        self.power(p)

    def power(self, p):
        require(self.read(p/'power/control') == 'on', 'Power pin did not hold: '+p.name)
        for item in ('runtime_status', 'runtime_suspended_time'):
            self.read(p/'power'/item)

    def check_link(self, gpu, parent, hda):
        require(gpu.exists() and gpu.resolve().parent.name == parent.name, 'GPU topology changed')
        for p in [parent, gpu, *hda]:
            self.pci(p.name)
        for p in [*(Path('/sys/bus/pci/devices')/b for b in PORTS), gpu, *hda]:
            self.power(p)

    def check_errors(self):
        text = self.run(['journalctl', '-k', '-b', '--since', self.state['journal_since'], '--no-pager', '-o', 'short-monotonic'])
        require(not FATAL.search(text), 'Fatal/link/power error recorded during trial; no recovery attempted')

    def fallback(self):
        menu = Path('/boot/limine.conf')
        entries = menu_entries(menu.read_text())
        normal = [e for e in entries if e.get('title') == '//linux']
        snapshot = [e for e in entries if e.get('title') == '////linux' and 'subvol=/@/.snapshots/461/snapshot ' in e.get('cmdline', '')]
        require(len(normal) == 1 and len(snapshot) == 1, 'Normal linux / snapshot461 fallback entry missing or ambiguous')
        checked = {}
        target = [e for e in entries if e.get('title') == '//linux-cachyos']
        require(len(target) == 1, 'CachyOS boot entry missing/ambiguous')
        require(target[0].get('cmdline') == normal[0].get('cmdline'), 'Target/fallback command lines differ')
        for entry in [normal[0], snapshot[0], target[0]]:
            for key in ('path', 'module_path'):
                path, expected = boot_resource(entry[key])
                actual = digest(path, 'blake2b')
                require(actual == expected, 'Boot checksum mismatch: '+str(path))
                checked[str(path)] = {'sha256': digest(path), 'blake2b': actual}
        snap = Path('/.snapshots/461/snapshot')
        require((snap/'usr/lib/modules'/'7.2.4-arch1-2').is_dir(), 'Snapshot461 matching kernel module tree missing')
        validate_gate((snap/str(GATE).lstrip('/')).read_text())
        self.run(['btrfs', 'subvolume', 'show', str(snap)])
        self.state['boot_files_before'] = checked
        self.state['menu_sha256'] = digest(menu)
        self.state['fallback'] = 'Snapshots > 461 > linux; files and BLAKE2b checksums verified, not a new boot test'
        self.log(self.state['fallback'])

    def execute(self):
        require(os.uname().release == KERNEL, 'Wrong running kernel')
        require('GZ302EA' in self.read('/sys/class/dmi/id/product_name'), 'Wrong laptop')
        require(self.read('/sys/class/dmi/id/bios_version') == 'GZ302EA.314', 'Wrong BIOS')
        cmdline = self.read('/proc/cmdline')
        require('amdgpu.dcdebugmask=0x40600' in cmdline.split(), 'Unexpected AMD command line')
        require(not any(x in cmdline for x in ('pcie_aspm=off', 'pcie_ports=native', 'pci=realloc', 'thunderbolt.host_reset=0', 'thunderbolt.host_reset=false')), 'Unexpected experimental command line')
        for name, version in [('linux-cachyos', '7.2.4-1'), ('linux', '7.2.4.arch1-2'), ('nvidia-utils', '615.71.09-1'), ('nvidia-open', '615.71.09-1.1')]:
            require(self.run(['pacman', '-Q', name]).strip() == name+' '+version, 'Package version changed: '+name)
        require(not any(Path('/sys/module', name).exists() for name in MODULES), 'NVIDIA/nouveau already loaded; no unload or retry')
        require(not PRIVATE.exists(), 'Trial already staged/attempted; review its records before any new attempt')
        require(not Path('/root/rollback-gpd-egpu-proprietary-615.sh').exists(), 'Trial rollback path already exists')
        validate_gate(GATE.read_text())
        for name in MODULES:
            plan = self.run(['modprobe', '--show-depends', '-n', '-v', name])
            require('install /usr/bin/false' in plan, 'Module gate not effective: '+name)
            require(not re.search(r'(?m)^insmod .*\b'+re.escape(name.replace('_', '-'))+r'\.ko', plan.replace('_', '-')), 'Unexpected driver load plan')
        self.run(['systemctl', 'is-enabled', 'egpu-postboot-verify.service'], check=False)
        require(self.run(['systemctl', 'is-active', 'egpu-postboot-verify.service'], check=False).strip() == 'inactive', 'Old verifier is active')
        enabled = self.run(['systemctl', 'is-enabled', 'egpu-postboot-verify.service'], check=False).strip()
        require(enabled in ('disabled', 'masked'), 'Old verifier can run automatically')
        self.fallback()
        core = HERE/'extracted/kernel/nvidia.ko'
        require(digest(core) == CORE_SHA, 'Proprietary core checksum mismatch')
        require(self.run(['modinfo', '-F', 'version', str(core)]).strip() == '615.71.09', 'Wrong module version')
        require(self.run(['modinfo', '-F', 'vermagic', str(core)]).split()[0] == KERNEL, 'Wrong module kernel')
        require(self.run(['modinfo', '-F', 'license', str(core)]).strip() == 'NVIDIA', 'Not the proprietary module')
        deps = self.run(['modinfo', '-F', 'depends', str(core)]).strip()
        require(deps == '', 'Unexpected core dependencies: '+deps)
        lockdown = Path('/sys/kernel/security/lockdown')
        if lockdown.exists():
            require('[none]' in self.read(lockdown), 'Kernel lockdown prevents this unsigned workspace module')
        PRIVATE.mkdir(mode=0o700)
        self.owned = True
        (PRIVATE/'runner.py').write_bytes(Path(__file__).read_bytes())
        (PRIVATE/'nvidia.ko').write_bytes(core.read_bytes())
        require(digest(PRIVATE/'nvidia.ko') == CORE_SHA, 'Private module copy mismatch')
        (PRIVATE/'packages-before.txt').write_text(self.run(['pacman', '-Q']))
        for p in [GATE, Path('/etc/modprobe.d/zz-nvidia-egpu.conf'), Path('/etc/udev/rules.d/99-usb4-tunnel-ports-awake.rules'), Path('/root/rollback-gpd-egpu.sh'), Path('/boot/limine.conf')]:
            target = PRIVATE/'baseline'/str(p).lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(p.read_bytes())
        wrapper = Path('/root/rollback-gpd-egpu-proprietary-615.sh')
        wrapper.write_text('#!/bin/bash\nset -euo pipefail\nexec /usr/bin/python3 /root/egpu-proprietary-615-trial/runner.py --undo\n')
        wrapper.chmod(0o700)
        self.run(['bash', '-n', str(wrapper)])
        self.checkpoint('baseline-and-undo-ready')
        for bdf in PORTS:
            self.pin(Path('/sys/bus/pci/devices')/bdf)
        self.log('Waiting up to 90 seconds for RTX4090. If absent, connect/power enclosure now; keep display outputs unused.')
        deadline = time.monotonic()+90
        gpu = None
        while time.monotonic() < deadline:
            found = self.devices()
            require(len(found) <= 1, 'Multiple NVIDIA display devices; ambiguous trial target')
            if found:
                gpu = found[0]
                break
            time.sleep(min(1, max(0, deadline-time.monotonic())))
        require(gpu is not None, 'GPU absent after 90 seconds; no recovery attempted')
        parent = Path('/sys/bus/pci/devices')/gpu.resolve().parent.name
        self.pci(parent.name)
        self.pci(gpu.name)
        require(self.read(gpu/'device') == '0x2684', 'Not RTX4090 AD102')
        require(self.read(parent/'vendor') == '0x8086' and self.read(parent/'device') == '0x5786', 'Not JHL9480 immediate parent')
        require(any(b in gpu.resolve().parts for b in PORTS), 'GPU outside expected USB4 root ports')
        require(not (gpu/'driver').exists(), 'GPU already bound; no rebinding allowed')
        self.state.update(gpu_bdf=gpu.name, parent_bdf=parent.name, realpath=str(gpu.resolve()))
        hda = [p for p in Path('/sys/bus/pci/devices').glob(gpu.name.rsplit('.', 1)[0]+'.*') if (p/'vendor').read_text().strip() == '0x10de' and (p/'class').read_text().strip() == '0x040300']
        self.run(['udevadm', 'settle', '--timeout=10'])
        for p in [gpu, *hda]:
            self.pin(p)
        self.state['journal_since'] = datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')
        self.start_follow()
        self.checkpoint('observing-driverless-60-seconds')
        time.sleep(60)
        self.check_link(gpu, parent, hda)
        self.check_errors()
        self.checkpoint('before-private-core-load')
        os.sync()
        self.run(['journalctl', '--sync'])
        self.run(['insmod', str(PRIVATE/'nvidia.ko'), 'NVreg_DynamicPowerManagement=0', 'NVreg_EnableGpuFirmware=0'], timeout=45)
        deadline = time.monotonic()+10
        while not (gpu/'driver').exists() and time.monotonic() < deadline:
            self.pci(parent.name)
            self.pci(gpu.name)
            time.sleep(0.25)
        require((gpu/'driver').exists() and (gpu/'driver').resolve().name == 'nvidia', 'Proprietary core did not bind within 10 seconds')
        self.run(['udevadm', 'settle', '--timeout=10'])
        live_params = self.read('/proc/driver/nvidia/params')
        parse_dpm(live_params)
        require(re.findall(r'^EnableGpuFirmware:\s*(\S+)\s*$', live_params, re.M) == ['0'], 'GSP-disable parameter did not win')
        self.check_link(gpu, parent, hda)
        self.check_errors()
        self.checkpoint('before-first-nvidia-smi')
        os.sync()
        self.run(['journalctl', '--sync'])
        self.run(['nvidia-smi', '-L'], timeout=30)
        query = self.run(['nvidia-smi', '-q'], timeout=30)
        require(re.findall(r'^\s*GSP Firmware Version\s*:\s*(.+)$', query, re.M) == ['N/A'], 'NVML did not confirm GSP disabled')
        self.run(['nvidia-smi'], timeout=30)
        self.checkpoint('observing-initialized-60-seconds')
        time.sleep(60)
        self.check_link(gpu, parent, hda)
        live_params = self.read('/proc/driver/nvidia/params')
        parse_dpm(live_params)
        require(re.findall(r'^EnableGpuFirmware:\s*(\S+)\s*$', live_params, re.M) == ['0'], 'GSP-disable parameter did not win')
        power = Path('/proc/driver/nvidia/gpus')/gpu.name/'power'
        if power.exists():
            text = self.read(power)
            match = re.search(r'Runtime D3 status:\s*(.+)', text)
            require(match is None or match[1].strip() in ('Disabled', 'Not supported', '?'), 'Runtime D3 unexpectedly enabled/supported')
        self.run(['nvidia-smi'], timeout=30)
        self.check_link(gpu, parent, hda)
        self.check_errors()
        require(digest('/boot/limine.conf') == self.state['menu_sha256'], 'Boot menu changed externally during trial')
        for path, hashes in self.state['boot_files_before'].items():
            require(digest(path) == hashes['sha256'], 'Boot image changed externally: '+path)
        self.result('PASS: proprietary615 non-GSP core NVML and 60-second idle test; GPU='+gpu.name+' parent='+parent.name+' live DPM=0. Compute/load stability not yet tested. Proprietary driver is volatile; no persistent installation.')

def undo():
    state = json.loads((PRIVATE/'attempt.json').read_text())
    require(not any(Path('/sys/module', name).exists() for name in MODULES), 'Driver still loaded: shut down normally and boot without eGPU before undo; no forced unload')
    same_boot = state['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if same_boot:
        for bdf, saved in state['power_before'].items():
            p = Path('/sys/bus/pci/devices')/bdf
            if not p.exists():
                continue
            require(str(p.resolve()) == saved['realpath'], 'Device topology changed; refuse live restore')
            with (p/'config').open('rb', buffering=0) as f:
                validate_config(f.read(64))
            require(saved['value'] in ('auto', 'on'), 'Invalid saved policy')
            (p/'power/control').write_text(saved['value']+'\n')
    # A new boot already discarded every volatile driver/policy change. Never replay old BDFs.
    (PRIVATE/'undo-completed.json').write_text(json.dumps({'time': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'same_boot': same_boot}))
    print('Trial undone; diagnostics retained. No packages/configuration/boot files were changed by this trial. Original full rollback remains separate.')

def main():
    require(os.geteuid() == 0, 'Run this staged script manually with sudo')
    if sys.argv[1:] == ['--undo']:
        undo()
        return
    require(not sys.argv[1:], 'No retry/continuation mode exists')
    trial = Trial()
    try:
        trial.execute()
    except (Exception, KeyboardInterrupt) as exc:
        trial.result('FAIL: '+str(exc)+'; no recovery, unloading or automatic retry attempted.')
        trial.run(['journalctl', '-k', '-b', '-n', '250', '--no-pager'], check=False)
        raise SystemExit(1)
    finally:
        trial.stop_follow()

if __name__ == '__main__':
    main()
