#!/usr/bin/python3
"""Repair startup dispatch, then perform the missing guarded display stage once."""
import hashlib,json,os,shutil,stat,subprocess,sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
BACKUP=Path('/root/gpd-egpu-display-routing-fix')
MANIFEST=Path('/opt/gpd-egpu/update-support/installed-hashes.json')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(v,s):
    if not v:raise RuntimeError(s)
def write(p,data,mode):
    tmp=p.with_name(p.name+'.routing-new')
    with tmp.open('xb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    tmp.chmod(mode); os.replace(tmp,p)
def main():
    require(os.geteuid()==0 and not sys.argv[1:],'Run with sudo, no arguments')
    os.umask(0o077)
    require(not BACKUP.exists(),'Fix already attempted; inspect backup/status before proceeding')
    changes=json.loads((HERE/'changes.json').read_text())
    hashes=json.loads(MANIFEST.read_text())
    for p,h in hashes.items(): require(digest(p)==h,'Installed integrity mismatch: '+p)
    for c in changes:
        require(digest(c['path'])==c['before'],'Unexpected existing helper: '+c['path'])
        require(digest(HERE/c['source'])==c['after'],'Staged payload changed')
    require(os.uname().release=='7.2.6-arch2-1','This repair activation was prepared for Arch 7.2.6')
    for n,s in [('nvidia','329D97755EFA31D5314E8F0'),('nvidia_uvm','064C13389A454AA4AAF638E')]:
        require(Path('/sys/module',n,'srcversion').read_text().strip()==s,'Unexpected loaded '+n)
    require(not any(Path('/sys/module',n).exists() for n in ('nvidia_modeset','nvidia_drm','nouveau')),'Display state changed; review first')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    require(not (Path('/var/lib/gpd-egpu-display')/boot).exists(),'A display attempt already exists; no retry')
    require(not Path('/var/lib/gpd-egpu-auto/initializing-or-failed.json').exists(),'Automatic failure marker exists')
    core=json.loads((Path('/var/lib/gpd-egpu-loader')/boot/'attempt.json').read_text())
    require(core.get('stage')=='completed' and core.get('boot_id')==boot,'Core activation did not complete')
    lact_active=subprocess.run(['systemctl','is-active','--quiet','lactd.service']).returncode==0
    BACKUP.mkdir(mode=0o700)
    records=[]
    for i,c in enumerate(changes):
        p=Path(c['path']); shutil.copy2(p,BACKUP/str(i)); records.append(dict(c,backup=str(i),mode=stat.S_IMODE(p.stat().st_mode)))
    shutil.copy2(MANIFEST,BACKUP/'manifest.before')
    updated=dict(hashes)
    for c in changes:updated[c['path']]=c['after']
    manifest_data=(json.dumps(updated,indent=2)+'\n').encode()
    records.append({'path':str(MANIFEST),'backup':'manifest.before','before':digest(MANIFEST),'after':hashlib.sha256(manifest_data).hexdigest(),'mode':stat.S_IMODE(MANIFEST.stat().st_mode)})
    (BACKUP/'records.json').write_text(json.dumps(records,indent=2))
    shutil.copy2(HERE/'rollback.py',BACKUP/'rollback.py')
    (BACKUP/'rollback.sh').write_text('#!/bin/sh\nexec /usr/bin/python3 /root/gpd-egpu-display-routing-fix/rollback.py\n'); (BACKUP/'rollback.sh').chmod(0o700)
    for c in records[:-1]:write(Path(c['path']),(HERE/c['source']).read_bytes(),c['mode'])
    write(MANIFEST,manifest_data,records[-1]['mode'])
    (BACKUP/'status').write_text('routing-installed; before-display-activation\n')
    subprocess.run(['/usr/local/sbin/gpd-egpu-start'],check=True,timeout=420)
    (BACKUP/'status').write_text('display-activation-passed; before-LACT-refresh\n')
    if lact_active:subprocess.run(['systemctl','restart','lactd.service'],check=True,timeout=40)
    (BACKUP/'status').write_text('completed; visible output and LACT detection need confirmation\n')
    print('FIX INSTALLED: registered kernels now use full display startup. Display activation passed. LACT refreshed only if previously active. No reboot or compute-driver reload. Rollback: sudo /root/gpd-egpu-display-routing-fix/rollback.sh',flush=True)
if __name__=='__main__':
    try:main()
    except Exception as e:raise SystemExit('STOP: '+str(e)+'; no automatic retry or recovery')
