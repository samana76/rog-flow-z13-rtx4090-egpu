#!/usr/bin/env python3
"""Remove only diagnostic idle sleeps; preserve hashes, backups and rollback."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BACK=Path('/root/egpu-startup-delay-backup')
CORE=Path('/opt/gpd-egpu/615.71.09/loader.py')
DISPLAY=Path('/opt/gpd-egpu/display-extension/display-start.py')
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    if os.geteuid()!=0:raise SystemExit('Run with sudo')
    status=subprocess.run(['systemctl','is-active','gpd-egpu-auto.service'],capture_output=True,text=True).stdout.strip()
    if status in ('active','activating','deactivating'):raise SystemExit('Current activation still running; allow it to finish first. Nothing changed.')
    if sys.argv[1:]==['--undo']:
        manifest=json.loads((BACK/'manifest.json').read_text())
        for name,record in manifest.items():
            if sha(Path(name).read_bytes()) not in (record['after'],record['before']):raise SystemExit('Changed file: '+name)
        for name,record in manifest.items():Path(name).write_bytes((BACK/record['backup']).read_bytes())
        print('Restored previous startup scripts and rollback manifests; no driver or boot actions.');return
    if sys.argv[1:] or BACK.exists():raise SystemExit('Invalid arguments or existing backup; no overwrite')
    old=CORE.read_bytes();display=DISPLAY.read_bytes()
    if sha(old)!='7fe79003e7aba0466e2e9fb80dd5a02fdba15e916280698bd0c3f24ac477db85' or sha(display)!='b56f7b411c5b1723174bc489e10d10e43f6c7ae3c980294050fa3b5b4c8b478f':raise SystemExit('Unexpected installed scripts')
    core_text=old.decode();display_text=display.decode()
    assert core_text.count('            time.sleep(60)')==2
    assert display_text.count('        time.sleep(60)')==1
    core_text=core_text.replace('            time.sleep(60)\n','')
    core_text=core_text.replace('driverless-idle-60-seconds','driverless-immediate-check').replace('initialized-idle-60-seconds','initialized-immediate-check')
    core_text=core_text.replace('keep NVIDIA display outputs unused','display activation follows compute initialization')
    new=core_text.encode()
    display_text=display_text.replace('        time.sleep(60)\n','').replace('display-idle-60-seconds','display-immediate-check').replace('healthy after60seconds','healthy at immediate check')
    display_text=display_text.replace(sha(old),sha(new))
    updated={CORE:new,DISPLAY:display_text.encode()}
    for p,data in updated.items():compile(data,str(p),'exec')
    for p,target in [(Path('/root/egpu-manual-loader-install/files.json'),CORE),(Path('/root/egpu-display-loader-backup/created.json'),DISPLAY)]:
        values=json.loads(p.read_text())
        assert values[str(target)]==sha(target.read_bytes())
        values[str(target)]=sha(updated[target])
        updated[p]=(json.dumps(values,indent=2)+'\n').encode()
    BACK.mkdir(mode=0o700)
    records={}
    for n,(p,data) in enumerate(updated.items()):
        original=p.read_bytes();name=str(n)+'.before';(BACK/name).write_bytes(original)
        records[str(p)]={'before':sha(original),'after':sha(data),'backup':name}
    (BACK/'manifest.json').write_text(json.dumps(records,indent=2))
    (BACK/'runner.py').write_bytes(Path(__file__).read_bytes())
    undo=Path('/root/rollback-gpd-egpu-startup-delays.sh')
    if undo.exists():raise SystemExit('Rollback path exists')
    undo.write_text('#!/bin/bash\nset -euo pipefail\nexec /usr/bin/python3 /root/egpu-startup-delay-backup/runner.py --undo\n');undo.chmod(0o700)
    subprocess.run(['bash','-n',str(undo)],check=True)
    for p,data in updated.items():
        p.write_bytes(data);print('UPDATED',p,sha(data),flush=True)
    os.sync()
    print('Removed all three diagnostic 60-second sleeps. All immediate safety checks retained. No service restart, driver load, package or boot change. Effective on next activation.')
if __name__=='__main__':main()
