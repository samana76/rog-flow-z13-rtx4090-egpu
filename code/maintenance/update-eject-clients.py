#!/usr/bin/env python3
"""Install the revised pre-release client handling; no eject/service actions."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BACK=Path('/root/egpu-eject-client-fix-backup')
TARGET=Path('/usr/local/libexec/gpd-egpu-eject')
MANIFEST=Path('/root/egpu-eject-ui-backup/created.json')
OLD='6628023226cfd90045a4635367633003f81059589b00a57f1079c0912cb25f7d'
NEW='0e3a3bbe01e141d3b9014e11d93b889df0f2a2cc1885158dee738973c5c168b6'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    if os.geteuid()!=0:raise SystemExit('Run this one-time update with sudo')
    if sys.argv[1:]==['--undo']:
        records=json.loads((BACK/'hashes.json').read_text())
        for n,p in [('helper',TARGET),('manifest',MANIFEST)]:
            if sha(p) not in (records[n]['before'],records[n]['after']):raise SystemExit('Changed file; stop: '+str(p))
        TARGET.write_bytes((BACK/'helper.before').read_bytes())
        MANIFEST.write_bytes((BACK/'manifest.before').read_bytes())
        print('Restored previous eject helper and owning manifest. No service or GPU action.');return
    if sys.argv[1:] or BACK.exists():raise SystemExit('Invalid arguments or prior backup exists')
    source=Path(__file__).resolve().parent/'eject-egpu.py'
    if sha(TARGET)!=OLD or sha(source)!=NEW:raise SystemExit('Unexpected helper hash; no changes')
    compile(source.read_text(),str(source),'exec')
    owner=json.loads(MANIFEST.read_text())
    if owner[str(TARGET)]!=OLD:raise SystemExit('Original ownership record changed')
    undo=Path('/root/rollback-gpd-egpu-eject-client-fix.sh')
    if undo.exists():raise SystemExit('Undo path exists')
    BACK.mkdir(mode=0o700)
    (BACK/'helper.before').write_bytes(TARGET.read_bytes())
    (BACK/'manifest.before').write_bytes(MANIFEST.read_bytes())
    (BACK/'installer.py').write_bytes(Path(__file__).read_bytes())
    owner[str(TARGET)]=NEW
    data=(json.dumps(owner,indent=2)+'\n').encode()
    (BACK/'hashes.json').write_text(json.dumps({'helper':{'before':OLD,'after':NEW},'manifest':{'before':sha(MANIFEST),'after':hashlib.sha256(data).hexdigest()}},indent=2))
    undo.write_text('#!/bin/bash\nset -euo pipefail\nexec /usr/bin/python3 /root/egpu-eject-client-fix-backup/installer.py --undo\n');undo.chmod(0o700)
    subprocess.run(['bash','-n',str(undo)],check=True)
    temp=TARGET.with_name(TARGET.name+'.client-fix-tmp')
    with temp.open('xb') as f:f.write(source.read_bytes());f.flush();os.fsync(f.fileno())
    temp.chmod(0o755);temp.replace(TARGET)
    MANIFEST.write_bytes(data);os.sync()
    print('UPDATED',TARGET,sha(TARGET))
    print('Session processes are permitted only before release; every client still blocks actual unloading. LACT pause is part of the next explicit GUI test, not this installation. Existing GUI entry unchanged.')
if __name__=='__main__':main()
