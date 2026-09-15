#!/usr/bin/env python3
"""Install experimental GUI eject action, preserving rollback. No GPU actions."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
BACK=Path('/root/egpu-eject-ui-backup')
TARGETS={'eject-egpu.py':'/usr/local/libexec/gpd-egpu-eject',
         'eject-dialog.py':'/usr/local/libexec/gpd-egpu-eject-dialog'}
DESKTOP=Path('/usr/share/applications/gpd-egpu-disconnect.desktop')
UNDO=Path('/root/rollback-gpd-egpu-eject-ui.sh')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    if os.geteuid()!=0:raise SystemExit('One-time installation requires sudo')
    if sys.argv[1:]==['--undo']:
        data=json.loads((BACK/'created.json').read_text())
        for name,h in data.items():
            p=Path(name)
            if p.is_symlink() or (p.exists() and digest(p)!=h):raise SystemExit('Owned file changed: '+name)
        for name in data:
            p=Path(name)
            if p.exists():p.unlink();print('REMOVE',p)
        print('Eject UI removed; all diagnostics and prior loader state retained. No module/boot actions.');return
    if sys.argv[1:] or BACK.exists():raise SystemExit('Invalid arguments or existing backup')
    manifest=json.loads((HERE/'eject-bundle.json').read_text())
    files={}
    for name,dest in TARGETS.items():
        p=HERE/name
        if digest(p)!=manifest[name]:raise SystemExit('Payload changed: '+name)
        compile(p.read_text(),name,'exec');files[Path(dest)]=p.read_bytes()
    files[DESKTOP]=b'[Desktop Entry]\nType=Application\nName=Disconnect GPD eGPU (test)\nComment=Release display and driver before unplugging\nExec=/usr/bin/python3 /usr/local/libexec/gpd-egpu-eject-dialog\nIcon=media-eject\nTerminal=false\nCategories=System;\n'
    files[UNDO]=b'#!/bin/bash\nset -euo pipefail\nexec /usr/bin/python3 /root/egpu-eject-ui-backup/installer.py --undo\n'
    for p in files:
        if p.exists() or p.is_symlink():raise SystemExit('Existing destination: '+str(p))
    BACK.mkdir(mode=0o700)
    (BACK/'installer.py').write_bytes(Path(__file__).read_bytes())
    (BACK/'created.json').write_text(json.dumps({str(p):hashlib.sha256(data).hexdigest() for p,data in files.items()},indent=2))
    order=[UNDO]+[p for p in files if p!=UNDO]
    for p in order:
        p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write(files[p]);f.flush();os.fsync(f.fileno())
        p.chmod(0o700 if p==UNDO else 0o644 if p==DESKTOP else 0o755)
        print('CREATE',p,digest(p),flush=True)
    subprocess.run(['bash','-n',str(UNDO)],check=True)
    print('Installed application: Disconnect GPD eGPU (test). No GPU, service, boot or package changes. Standard graphical administrator authorization is required; no sudoers or polkit permissions changed.')
if __name__=='__main__':main()
