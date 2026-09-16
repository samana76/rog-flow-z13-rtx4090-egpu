#!/usr/bin/python3
"""Install update safeguards only. Never upgrade, rebuild initramfs or load modules."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

HERE=Path(__file__).resolve().parent
BASE=Path('/opt/gpd-egpu/update-support')
BACK=Path('/root/gpd-egpu-update-support-backup')
ARCHIVE=HERE.parent/'update-preparation/NVIDIA-Linux-x86_64-615.71.09-no-compat32.run'
SOURCE='e5545862c291f3991a91ee40dd9c7a71cccc69247a193d5e5b891bfd964ac104'

def check(ok,message):
    if not ok:raise RuntimeError(message)

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def put(p,data,mode=0o600):
    p=Path(p);q=p.with_name(p.name+'.update-support-tmp')
    with q.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    q.chmod(mode);q.replace(p)

def install():
    check(os.geteuid()==0 and not sys.argv[1:],'Run with sudo, no arguments')
    os.umask(0o077)
    check(not Path('/var/lib/pacman/db.lck').exists(),'A package transaction is already running')
    seal=json.loads((HERE/'payload-seal.json').read_text())
    for name,h in seal.items():check(sha(HERE/'payload'/name)==h,'Staged file changed: '+name)
    check(sha(ARCHIVE)==SOURCE,'Vendor archive differs from reviewed source')
    changes=json.loads((HERE/'payload/changes.json').read_text())
    for row in changes:
        p=Path(row['path']);check(not p.is_symlink() and sha(p)==row['before'],'Installed helper changed: '+str(p))
    for hook in ('00-gpd-egpu-update-pre.hook','zz-gpd-egpu-update-post.hook'):
        check(not (Path('/etc/pacman.d/hooks')/hook).exists(),'Hook path already exists')
    check(not BASE.exists() and not BACK.exists(),'Installation/backup already exists; do not repeat')
    # Pure boot validation; no GPU calls, service changes, or package transaction.
    sys.path.insert(0,str(HERE/'payload'))
    import update
    update.boot_check(check_init=True)
    r=subprocess.run(['/usr/bin/pacman','-Q','nvidia-utils'],capture_output=True,text=True)
    check(r.returncode==0 and r.stdout.strip()=='nvidia-utils 615.71.09-1','NVIDIA userspace changed')
    baseline=json.loads((HERE/'payload/registry.json').read_text())
    for k,row in baseline['kernels'].items():
        for n,m in row['modules'].items():
            path=Path(row['payload'] if n in ('nvidia.ko','nvidia-uvm.ko') else row['display_payload'])/n
            check(sha(path)==m['sha256'],'Installed module changed: '+str(path))
            for field,expected in [('version',m['version']),('srcversion',m['srcversion'])]:
                r=subprocess.run(['/usr/bin/modinfo','-F',field,str(path)],capture_output=True,text=True)
                check(r.returncode==0 and r.stdout.strip()==expected,'Module metadata changed')
    BACK.mkdir(mode=0o700)
    for i,row in enumerate(changes):shutil.copy2(row['path'],BACK/(str(i)+'.before'))
    (BACK/'changes.json').write_text(json.dumps(changes,indent=2))
    (BACK/'registry-before.json').write_text(json.dumps(baseline,indent=2))
    shutil.copy2(HERE/'rollback.py',BACK/'rollback.py')
    (BACK/'rollback.sh').write_text('#!/bin/bash\nset -euo pipefail\nexec /usr/bin/python3 -E -s /root/gpd-egpu-update-support-backup/rollback.py\n')
    (BACK/'rollback.sh').chmod(0o700)
    subprocess.run(['/usr/bin/bash','-n',str(BACK/'rollback.sh')],check=True)
    BASE.mkdir(mode=0o700)
    newpaths=[]
    for name in ('registry.py','registry.json','update.py'):
        put(BASE/name,(HERE/'payload'/name).read_bytes());newpaths.append(str(BASE/name))
    shutil.copyfile(ARCHIVE,BASE/'vendor.run');(BASE/'vendor.run').chmod(0o600);newpaths.append(str(BASE/'vendor.run'))
    check(sha(BASE/'vendor.run')==SOURCE,'Vendor copy verification failed')
    lock=open('/run/lock/gpd-egpu-loader.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    r=subprocess.run(['/usr/bin/systemctl','is-active','gpd-egpu-auto.service'],capture_output=True,text=True)
    check(r.stdout.strip()=='inactive','Activation service is not idle; no changes to helpers made')
    changed=[]
    try:
        for row in changes:
            check(sha(row['path'])==row['before'],'Concurrent helper change')
            put(row['path'],(HERE/'payload'/row['source']).read_bytes(),row['mode']);changed.append(row)
        hashes={r['path']:r['after'] for r in changes}
        hashes.update({str(BASE/n):sha(BASE/n) for n in ('registry.py','update.py')})
        for n in ('00-gpd-egpu-update-pre.hook','zz-gpd-egpu-update-post.hook'):
            p=Path('/etc/pacman.d/hooks')/n
            put(p,(HERE/'payload'/n).read_bytes(),0o644);newpaths.append(str(p));hashes[str(p)]=sha(p)
        gate=Path('/etc/modprobe.d/zzz-gpd-egpu-controlled-load.conf');hashes[str(gate)]=sha(gate)
        put(BASE/'installed-hashes.json',(json.dumps(hashes,indent=2)+'\n').encode());newpaths.append(str(BASE/'installed-hashes.json'))
        for row in changes:check(sha(row['path'])==row['after'],'Installed helper verification failed')
        (BACK/'created.json').write_text(json.dumps({p:sha(p) for p in newpaths},indent=2))
        os.sync()
    except BaseException:
        for row in reversed(changed):
            i=changes.index(row);put(row['path'],(BACK/(str(i)+'.before')).read_bytes(),row['mode'])
        for p in newpaths:
            if p.startswith('/etc/pacman.d/hooks/') and Path(p).exists():Path(p).unlink()
        raise
    print('INSTALLED: automatic pre-update proprietary builds and post-update checks. Existing drivers untouched; no update or reboot performed.')
    print('Normal sensitive-update command: sudo pacman -Syu')
    print('New NVIDIA releases and transactions replacing both tested kernels are blocked for review.')
    print('Undo this integration before earlier rollbacks: sudo '+str(BACK/'rollback.sh'))

if __name__=='__main__':
    try:install()
    except Exception as e:raise SystemExit('STOP: '+str(e)+'; no driver load or reboot attempted')
