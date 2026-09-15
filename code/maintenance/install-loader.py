#!/usr/bin/env python3
"""Install only private on-demand loader files; no package or boot mutations."""
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
DEST = Path('/opt/gpd-egpu/615.71.09')
RECORD = Path('/root/egpu-manual-loader-install')
WRAPPER = Path('/usr/local/sbin/gpd-egpu-start')
UNDO = Path('/root/rollback-gpd-egpu-loader.sh')
LOG = None

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def note(message):
    line = datetime.datetime.now(datetime.timezone.utc).isoformat()+' '+str(message)
    print(line, flush=True)
    if LOG:
        LOG.write(line+'\n'); LOG.flush(); os.fsync(LOG.fileno())

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def precheck_undo(files):
    for name, expected in files.items():
        p = Path(name)
        require(not p.is_symlink(), 'Refusing symlink: '+name)
        require(not p.exists() or sha(p) == expected, 'Owned file changed; preserve for review: '+name)

def undo():
    files = json.loads((RECORD/'files.json').read_text())
    precheck_undo(files)
    for name in files:
        p = Path(name)
        if p.exists():
            note('REMOVE task-created file '+name)
            p.unlink()
    note('Loader files removed. Logs/records retained. No modules unloaded or live power policies changed; loaded modules and volatile pins last until reboot. Existing pre-loader rules/gate and original rollback untouched.')

def install():
    require(os.uname().release == '7.2.4-arch1-2', 'Install from the currently validated Arch boot')
    require(not RECORD.exists() and not DEST.exists() and not WRAPPER.exists() and not UNDO.exists(), 'Install paths already exist; preserve prior records')
    manifest = json.loads((HERE/'bundle.json').read_text())
    for name, expected in manifest.items():
        require(sha(HERE/name) == expected, 'Staged payload checksum mismatch: '+name)
        if name.endswith('.py'):
            compile((HERE/name).read_text(), name, 'exec')
    passed = Path('/root/egpu-arch-proprietary-615-bounded/attempt.json')
    record = json.loads(passed.read_text())
    require(record.get('stage') == 'completed' and record.get('result','').startswith('PASS: Arch'), 'Completed Arch bounded validation required')
    require(record['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'Boot changed; current validated state required')
    for module, expected in [('nvidia','329D97755EFA31D5314E8F0'), ('nvidia_uvm','064C13389A454AA4AAF638E')]:
        require(Path('/sys/module',module,'srcversion').read_text().strip() == expected, 'Expected loaded module missing/changed')
    spec = importlib.util.spec_from_file_location('loader', HERE/'loader.py')
    loader = importlib.util.module_from_spec(spec); spec.loader.exec_module(loader)
    loader.ROOT = HERE/'payload'/os.uname().release
    m = loader.guard()
    m.LOGDIR = Path('/var/log/egpu-autoconfig/loader-install-validation')
    t = m.Trial()
    loader.identity(t,m)
    loader.live(t,m)
    gpu,parent,hda = loader.find_gpu(t,m,False)
    t.check_link(gpu,parent,hda)
    t.state.update(record)
    t.check_errors()
    loader.nvml(t,m)
    RECORD.mkdir(mode=0o700)
    (RECORD/'successful-arch-attempt.json').write_bytes(passed.read_bytes())
    (RECORD/'installer.py').write_bytes(Path(__file__).read_bytes())
    files = {}
    payload = {}
    for name in manifest:
        if name.startswith('payload/'):
            payload[DEST/name.removeprefix('payload/')] = (HERE/name).read_bytes()
    payload[DEST/'loader.py'] = (HERE/'loader.py').read_bytes()
    payload[WRAPPER] = b'#!/bin/bash\nset -euo pipefail\nexec /usr/bin/python3 /opt/gpd-egpu/615.71.09/loader.py "$@"\n'
    payload[UNDO] = b'#!/bin/bash\nset -euo pipefail\nexec /usr/bin/python3 /root/egpu-manual-loader-install/installer.py --undo\n'
    for path, data in payload.items():
        require(not path.exists() and not path.is_symlink(), 'Refusing to overwrite '+str(path))
        files[str(path)] = hashlib.sha256(data).hexdigest()
    (RECORD/'files.json').write_text(json.dumps(files,indent=2)+'\n')
    # Establish rollback before any payload files; every prospective path is recorded.
    order = [UNDO]+[p for p in payload if p != UNDO]
    for path in order:
        note('CREATE '+str(path)+' SHA256 '+files[str(path)])
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as f:
            f.write(payload[path]); f.flush(); os.fsync(f.fileno())
        path.chmod(0o700 if path == UNDO else 0o755 if path == WRAPPER else 0o644)
    for p in (WRAPPER,UNDO):
        subprocess.run(['bash','-n',str(p)],check=True)
    note('INSTALLED: sudo gpd-egpu-start. No automatic startup. No package, boot, service, module-tree or power-policy changes by this installer. Rollback: sudo /root/rollback-gpd-egpu-loader.sh')

def main():
    global LOG
    require(os.geteuid() == 0, 'Run manually with sudo')
    require(sys.argv[1:] in ([],['--undo']), 'Unsupported argument')
    os.umask(0o077)
    directory = Path('/var/log/egpu-autoconfig/loader-install')
    directory.mkdir(parents=True,exist_ok=True)
    LOG = (directory/'operations.log').open('a',buffering=1)
    with open('/run/lock/gpd-egpu-loader.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        note('BEGIN '+repr(sys.argv)+' SCRIPT SHA256 '+sha(__file__))
        try:
            undo() if sys.argv[1:] else install()
        except Exception as exc:
            note('FAIL: '+str(exc)+'; no automatic retry or recovery')
            raise SystemExit(1)
        finally:
            note('END')

if __name__ == '__main__':
    main()
