#!/usr/bin/env python3
"""Add reversible Arch display dispatch; retain original compute payload."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
BACK=Path('/root/egpu-display-loader-backup')
DEST=Path('/opt/gpd-egpu/display-extension')
COMMAND=Path('/usr/local/sbin/gpd-egpu-start')
UNDO=Path('/root/rollback-gpd-egpu-display-loader.sh')
OLD='f5a59a9fa95a05860e49cbd8f967d066acdaa96253b6503943be6b7fbcba1909'
HASHES={'display-start.py':'b56f7b411c5b1723174bc489e10d10e43f6c7ae3c980294050fa3b5b4c8b478f',
        'display-payload/nvidia-modeset.ko':'58db7a3b74657de9545f4ea7a8de99a35c2a3b4148e024e57c0b25ba848da003',
        'display-payload/nvidia-drm.ko':'69c7e08562525d25578bf0020b85b5ca8aad3d26d7da8c1ab7c8ea831cb48630'}
WRAPPER=b'''#!/bin/bash
set -euo pipefail
case "$(uname -r)" in
  7.2.4-arch1-2) exec /usr/bin/python3 /opt/gpd-egpu/display-extension/display-start.py "$@" ;;
  *) exec /usr/bin/python3 /opt/gpd-egpu/615.71.09/loader.py "$@" ;;
esac
'''
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,msg):
    if not ok: raise RuntimeError(msg)
def note(msg): print(datetime.datetime.now(datetime.timezone.utc).isoformat()+' '+msg,flush=True)
def write(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name(p.name+'.egpu-tmp')
    with temp.open('xb') as f: f.write(data);f.flush();os.fsync(f.fileno())
    temp.chmod(0o700 if str(p).startswith('/root/') else 0o755 if p==COMMAND else 0o644)
    temp.replace(p)
    note('WRITE '+str(p)+' SHA256 '+sha(p))
def main():
    check(os.geteuid()==0,'Run with sudo')
    check(sys.argv[1:] in ([],['--undo']),'Invalid arguments')
    os.umask(0o077)
    with open('/run/lock/gpd-egpu-loader.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if sys.argv[1:]:
            records=json.loads((BACK/'created.json').read_text())
            check(not COMMAND.is_symlink() and sha(COMMAND) in (OLD,hashlib.sha256(WRAPPER).hexdigest()),'Command changed; stop')
            for name,h in records.items():
                p=Path(name);check(not p.is_symlink() and (not p.exists() or sha(p)==h),'Changed owned file: '+name)
            check(sha(BACK/'gpd-egpu-start.before')==OLD,'Backup changed')
            write(COMMAND,(BACK/'gpd-egpu-start.before').read_bytes())
            for name in records:
                p=Path(name)
                if p.exists(): p.unlink();note('REMOVE '+name)
            note('Restored compute-only command. Loaded display modules remain until reboot. Existing core rollback now applies; diagnostics retained.')
            return
        check(os.uname().release=='7.2.4-arch1-2','Install from successful Arch display boot')
        check(not BACK.exists() and not DEST.exists() and not UNDO.exists(),'Prior installation/backup exists')
        check(sha(COMMAND)==OLD,'Compute command changed')
        trial=json.loads(Path('/root/egpu-arch-display-trial/attempt.json').read_text())
        check(trial.get('stage')=='completed' and trial.get('result','').startswith('PASS:'),'Completed display trial required')
        check(trial['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'Boot changed')
        for name,h in HASHES.items(): check(sha(HERE/name)==h,'Payload changed: '+name)
        check(Path('/sys/module/nvidia_drm/parameters/modeset').read_text().strip()=='Y','Display not active')
        for name,expected in [('nvidia_modeset','C86CA92D8E48780F19CB46E'),('nvidia_drm','E22EBDCD6BCC5889463CFBF')]:
            check(Path('/sys/module',name,'srcversion').read_text().strip()==expected,'Display build changed')
        BACK.mkdir(mode=0o700)
        (BACK/'installer.py').write_bytes(Path(__file__).read_bytes())
        (BACK/'gpd-egpu-start.before').write_bytes(COMMAND.read_bytes())
        (BACK/'successful-display.json').write_text(json.dumps(trial,indent=2))
        undo=b'#!/bin/bash\nset -euo pipefail\nexec /usr/bin/python3 /root/egpu-display-loader-backup/installer.py --undo\n'
        records={str(DEST/name):h for name,h in HASHES.items()}
        records[str(UNDO)]=hashlib.sha256(undo).hexdigest()
        (BACK/'created.json').write_text(json.dumps(records,indent=2))
        write(UNDO,undo)
        for name in HASHES: write(DEST/name,(HERE/name).read_bytes())
        write(COMMAND,WRAPPER)
        subprocess.run(['bash','-n',str(COMMAND)],check=True)
        subprocess.run(['bash','-n',str(UNDO)],check=True)
        note('INSTALLED: gpd-egpu-start now includes Arch display. No driver load, boot/package/service changes. Undo display extension before the original compute-loader rollback.')

if __name__=='__main__':
    logdir=Path('/var/log/egpu-autoconfig/display-loader-install')
    if os.geteuid()!=0: raise SystemExit('Run manually with sudo')
    logdir.mkdir(parents=True,exist_ok=True)
    class Tee:
        def __init__(self): self.log=(logdir/'operations.log').open('a',buffering=1);self.terminal=sys.stdout
        def write(self,s): self.log.write(s);self.terminal.write(s)
        def flush(self): self.log.flush();self.terminal.flush();os.fsync(self.log.fileno())
    sys.stdout=Tee()
    try: main()
    except Exception as e: note('FAIL: '+str(e)+'; no automatic retry');raise SystemExit(1)
