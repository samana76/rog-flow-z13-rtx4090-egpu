#!/usr/bin/python3
"""Undo this integration only, preserving update evidence and older rollback layers."""
import fcntl,hashlib,json,os,subprocess
from pathlib import Path
BACK=Path('/root/gpd-egpu-update-support-backup')
BASE=Path('/opt/gpd-egpu/update-support')
def check(ok,msg):
    if not ok:raise RuntimeError(msg)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def main():
    check(os.geteuid()==0,'Root required')
    lock=open('/run/lock/gpd-egpu-loader.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    check(not Path('/var/lib/gpd-egpu-updates/pending.json').exists(),'Pending package update must be reviewed first')
    check(not Path('/var/lib/pacman/db.lck').exists(),'Package transaction in progress')
    r=subprocess.run(['systemctl','is-active','gpd-egpu-auto.service'],capture_output=True,text=True)
    check(r.stdout.strip()=='inactive','Activation service must be inactive')
    changes=json.loads((BACK/'changes.json').read_text());created=json.loads((BACK/'created.json').read_text())
    check(json.loads((BASE/'registry.json').read_text())==json.loads((BACK/'registry-before.json').read_text()),'Kernel registry advanced; cannot restore old fixed-version loaders. Review/revert kernel update first.')
    for i,row in enumerate(changes):
        check(sha(row['path'])==row['after'] and sha(BACK/(str(i)+'.before'))==row['before'],'Changed helper or backup; refusing overwrite')
    for p,h in created.items():check(sha(p)==h,'Changed support file; refusing delete: '+p)
    for i,row in enumerate(changes):
        p=Path(row['path']);temp=p.with_name(p.name+'.rollback-tmp')
        with temp.open('xb') as f:f.write((BACK/(str(i)+'.before')).read_bytes());f.flush();os.fsync(f.fileno())
        temp.chmod(row['mode']);temp.replace(p)
    for p in created:Path(p).unlink()
    cache=BASE/'__pycache__'
    if cache.exists():
        import shutil;shutil.rmtree(cache)
    BASE.rmdir();os.sync()
    print('Update integration removed; prior helpers restored. Backups and update evidence retained. No packages, boot files, modules or services changed by rollback.')
if __name__=='__main__':
    try:main()
    except Exception as e:raise SystemExit('ROLLBACK STOP: '+str(e))
