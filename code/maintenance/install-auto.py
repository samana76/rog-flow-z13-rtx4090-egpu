#!/usr/bin/env python3
"""Install first-connection automation; never start it or reboot during install."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
BACK=Path('/root/egpu-auto-backup')
def run(args):
    print(repr(args),flush=True);subprocess.run(args,check=True,timeout=120)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    if os.geteuid()!=0:raise SystemExit('Run manually with sudo')
    if sys.argv[1:]==['--undo']:
        records=json.loads((BACK/'files.json').read_text())
        for name,h in records.items():
            p=Path(name)
            if p.is_symlink() or (p.exists() and sha(p)!=h):raise SystemExit('Changed file; stop: '+name)
        # Disable future activation without killing a running kernel operation.
        result=subprocess.run(['systemctl','is-active','gpd-egpu-auto.service'],capture_output=True,text=True)
        if result.stdout.strip() in ('active','activating','deactivating'):raise SystemExit('Activation still running; wait for completion before rollback')
        run(['systemctl','disable','gpd-egpu-auto.service'])
        for name in records:
            p=Path(name)
            if p.exists():p.unlink()
        run(['systemctl','daemon-reload']);run(['udevadm','control','--reload-rules'])
        print('Automatic activation removed; manual display and compute setup retained. No modules unloaded.');return
    if sys.argv[1:]:raise SystemExit('Invalid arguments')
    if BACK.exists():raise SystemExit('Existing automation backup; no overwrite')
    if os.uname().release!='7.2.4-arch1-2':raise SystemExit('Install in tested Arch display boot')
    sources={'auto-start.py':'/opt/gpd-egpu/auto/auto-start.py',
             'gpd-egpu-auto.service':'/etc/systemd/system/gpd-egpu-auto.service',
             '99-gpd-egpu-auto.rules':'/etc/udev/rules.d/99-gpd-egpu-auto.rules'}
    expected=json.loads((HERE/'auto-bundle.json').read_text())
    for name in sources:
        if sha(HERE/name)!=expected[name]:raise SystemExit('Payload changed: '+name)
        p=Path(sources[name])
        if p.exists() or p.is_symlink():raise SystemExit('Existing destination: '+str(p))
    upgrade=HERE/'install-display-loader.py'
    if not Path('/opt/gpd-egpu/display-extension/display-start.py').exists():
        if sha(upgrade)!='98bdfc5ee62e551fa067fbfc5cd29177ee2cdd125c4e70932f6be086ab2674d3':raise SystemExit('Display installer changed')
        run(['/usr/bin/python3',str(upgrade)])
    # Require the dispatcher to include the successful display extension.
    if '/opt/gpd-egpu/display-extension/display-start.py' not in Path('/usr/local/sbin/gpd-egpu-start').read_text():raise SystemExit('Display dispatcher missing')
    BACK.mkdir(mode=0o700)
    (BACK/'installer.py').write_bytes(Path(__file__).read_bytes())
    records={dest:expected[src] for src,dest in sources.items()}
    undo=Path('/root/rollback-gpd-egpu-auto.sh')
    if undo.exists():raise SystemExit('Rollback path already exists')
    body=b'#!/bin/bash\nset -euo pipefail\nexec /usr/bin/python3 /root/egpu-auto-backup/installer.py --undo\n'
    records[str(undo)]=hashlib.sha256(body).hexdigest()
    (BACK/'files.json').write_text(json.dumps(records,indent=2))
    undo.write_bytes(body);undo.chmod(0o700)
    for src,dest in sources.items():
        p=Path(dest);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((HERE/src).read_bytes());p.chmod(0o644)
        print('CREATE',dest,expected[src],flush=True)
    run(['systemctl','daemon-reload'])
    run(['udevadm','control','--reload-rules'])
    run(['systemctl','enable','gpd-egpu-auto.service'])
    print('ENABLED for next boot/first connection; not started now. Unplug/reconnect remains untested. Rollback: /root/rollback-gpd-egpu-auto.sh')
if __name__=='__main__':main()
