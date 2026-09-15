#!/usr/bin/env python3
"""Install clean-eject reconnect dispatch. Never starts/stops a driver or service."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BACK=Path('/root/egpu-clean-reconnect-backup')
AUTO=Path('/opt/gpd-egpu/auto/auto-start.py')
HELPER=Path('/opt/gpd-egpu/auto/restart-clean-cycle.py')
OWNER=Path('/root/egpu-auto-backup/files.json')
UNDO=Path('/root/rollback-gpd-egpu-clean-reconnect.sh')
OLD='02b52498f9a534d053b23c31806fba622cc71034e6afcc998f82281fcf4340ab'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok,s):
    if not ok:raise RuntimeError(s)
def main():
    check(os.geteuid()==0,'Run with sudo')
    active=subprocess.run(['systemctl','is-active','gpd-egpu-auto.service'],capture_output=True,text=True,timeout=10)
    check(active.stdout.strip()=='inactive','Auto loader must be idle; nothing stopped')
    if sys.argv[1:]==['--undo']:
        records=json.loads((BACK/'expected.json').read_text())
        for p,allowed in [(AUTO,(OLD,records['auto'])),(HELPER,(records['helper'],)),(OWNER,(records['owner_before'],records['owner_after']))]:
            check(not p.is_symlink() and (not p.exists() or sha(p) in allowed),'Changed file; stop: '+str(p))
        AUTO.write_bytes((BACK/'auto.before').read_bytes());AUTO.chmod(0o644)
        OWNER.write_bytes((BACK/'owner.before').read_bytes())
        if HELPER.exists():HELPER.unlink()
        print('Restored original first-activation automation. Drivers unchanged; all logs retained.');return
    check(not sys.argv[1:],'Invalid arguments')
    check(os.uname().release=='7.2.4-arch1-2','Exact tested Arch kernel required')
    check(not BACK.exists() and not UNDO.exists() and not HELPER.exists(),'Existing reconnect installation; no overwrite')
    check(sha(AUTO)==OLD,'Existing auto dispatcher changed')
    check(not Path('/var/lib/gpd-egpu-auto/initializing-or-failed.json').exists(),'Existing failure lockout; no changes')
    here=Path(__file__).resolve().parent
    bundle=json.loads((here/'clean-reconnect-bundle.json').read_text())
    for name,value in bundle.items():check(sha(here/name)==value,'Staged payload changed: '+name)
    owner=json.loads(OWNER.read_text());check(owner[str(AUTO)]==OLD,'Original rollback owner record changed')
    prior=OWNER.read_bytes();owner[str(AUTO)]=bundle['auto-clean-cycle.py']
    after=(json.dumps(owner,indent=2)+'\n').encode()
    BACK.mkdir(mode=0o700)
    (BACK/'auto.before').write_bytes(AUTO.read_bytes());(BACK/'owner.before').write_bytes(prior)
    (BACK/'installer.py').write_bytes(Path(__file__).read_bytes())
    records={'auto':bundle['auto-clean-cycle.py'],'helper':bundle['restart-clean-cycle.py'],
             'owner_before':hashlib.sha256(prior).hexdigest(),'owner_after':hashlib.sha256(after).hexdigest()}
    (BACK/'expected.json').write_text(json.dumps(records,indent=2)+'\n')
    body='#!/bin/bash\nset -euo pipefail\nexec /usr/bin/python3 /root/egpu-clean-reconnect-backup/installer.py --undo\n'
    subprocess.run(['bash','-n'],input=body,text=True,check=True)
    UNDO.write_text(body);UNDO.chmod(0o700);os.sync()
    # Stage the helper first; atomically replace the dispatcher only when ready.
    HELPER.write_bytes((here/'restart-clean-cycle.py').read_bytes());HELPER.chmod(0o644)
    temp=AUTO.with_name('auto-start.clean-cycle.tmp')
    with temp.open('xb') as f:
        f.write((here/'auto-clean-cycle.py').read_bytes());f.flush();os.fsync(f.fileno())
    temp.chmod(0o644);temp.replace(AUTO)
    OWNER.write_bytes(after);os.sync()
    check(sha(AUTO)==records['auto'] and sha(HELPER)==records['helper'],'Installed payload verification failed')
    print('INSTALLED: automatic restart on PCI reconnection after a successful disconnect-app operation. No driver/service start, package, boot or kernel changes. Physical reconnect remains to be tested.')
    print('Rollback: sudo '+str(UNDO)+' (undo this layer before the original automation rollback).')

if __name__=='__main__':main()
