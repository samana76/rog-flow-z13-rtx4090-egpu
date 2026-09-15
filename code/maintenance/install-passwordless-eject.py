#!/usr/bin/env python3
"""Authorize only the existing eject helper for the active local desktop user."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import time

RULE=Path('/etc/polkit-1/rules.d/00-gpd-egpu-eject.rules')
BACK=Path('/root/egpu-passwordless-eject-backup')
UNDO=Path('/root/rollback-gpd-egpu-passwordless-eject.sh')
HELPER=Path('/usr/local/libexec/gpd-egpu-eject')
HELPER_SHA='0e3a3bbe01e141d3b9014e11d93b889df0f2a2cc1885158dee738973c5c168b6'
POLICY='''// Allow only EGPU_USER's active local session to run the root-owned eject helper.
polkit.addRule(function(action, subject) {
    if (action.id === "org.freedesktop.policykit.exec" &&
        action.lookup("program") === "/usr/local/libexec/gpd-egpu-eject" &&
        action.lookup("user") === "root" &&
        subject.user === "EGPU_USER" &&
        subject.local === true && subject.active === true) {
        return polkit.Result.YES;
    }
});
'''
ROLLBACK='#!/bin/bash\nset -euo pipefail\nexec /usr/bin/python3 /root/egpu-passwordless-eject-backup/installer.py --undo\n'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok,message):
    if not ok:raise RuntimeError(message)
def root_owned(p):
    for item in (p,*p.parents):
        s=item.lstat()
        check(not stat.S_ISLNK(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022,
              'Path must be root-owned and not group/world writable: '+str(item))

def main():
    check(os.geteuid()==0,'One-time installation requires sudo')
    os.umask(0o077)
    if sys.argv[1:]==['--undo']:
        check(not RULE.is_symlink(),'Rule path became a symlink')
        if RULE.exists():
            check(digest(RULE)==hashlib.sha256(POLICY.encode()).hexdigest(),'Rule changed outside this task; refusing removal')
            RULE.unlink();os.sync()
        print('Password-free eject authorization removed. Polkit reloads rules automatically. GPU and app unchanged.');return
    check(not sys.argv[1:],'Invalid arguments')
    check(not RULE.exists() and not RULE.is_symlink() and not BACK.exists() and not UNDO.exists(),'Existing installation/backup; no overwrite')
    check(pwd.getpwnam('EGPU_USER').pw_uid==1000,'Unexpected desktop user identity')
    root_owned(HELPER);root_owned(RULE.parent)
    check(digest(HELPER)==HELPER_SHA,'Eject helper changed; review its privilege boundary before authorizing')
    check("check(not sys.argv[1:]" in HELPER.read_text(),'Expected no-arguments guard missing')
    # Find a real desktop process, not this sudo process, for an authorization-only check.
    subject=None
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():continue
        try:
            if proc.stat().st_uid==1000 and (proc/'exe').resolve()==Path('/usr/bin/kwin_wayland'):
                start=(proc/'stat').read_text().rsplit(')',1)[1].split()[19]
                subject=proc.name+','+start+',1000';break
        except FileNotFoundError:continue
    check(subject is not None,'No local KWin desktop process found; no changes')
    BACK.mkdir(mode=0o700)
    (BACK/'installer.py').write_bytes(Path(__file__).read_bytes())
    (BACK/'manifest.json').write_text(json.dumps({'created_rule':str(RULE),'rule_sha256':hashlib.sha256(POLICY.encode()).hexdigest(),
                                               'helper_sha256':HELPER_SHA,'previous_rule':'absent','scope':'active local EGPU_USER; exact eject executable; root target'},indent=2)+'\n')
    subprocess.run(['bash','-n'],input=ROLLBACK,text=True,check=True)
    UNDO.write_text(ROLLBACK);UNDO.chmod(0o700);os.sync()
    with RULE.open('x') as f:f.write(POLICY);f.flush();os.fsync(f.fileno())
    RULE.chmod(0o644);os.sync()
    # pkcheck tests authorization only. It NEVER executes the eject helper.
    command=['/usr/bin/pkcheck','--action-id','org.freedesktop.policykit.exec','--process',subject,
             '--detail','program',str(HELPER),'--detail','user','root']
    results=[]
    for _ in range(5):
        r=subprocess.run(command,capture_output=True,text=True,timeout=10)
        results.append({'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
        if r.returncode==0:break
        time.sleep(1)
    (BACK/'authorization-check.json').write_text(json.dumps({'command':command,'attempts':results},indent=2)+'\n')
    if r.returncode!=0:
        check(digest(RULE)==hashlib.sha256(POLICY.encode()).hexdigest(),'Rule changed during verification')
        RULE.unlink();os.sync()
        raise SystemExit('Authorization check failed; new rule removed. Existing permissions unchanged. Evidence: '+str(BACK))
    print('INSTALLED AND AUTHORIZATION CHECK PASSED: Disconnect GPD eGPU requires no password for EGPU_USER in the active local desktop session.')
    print('Eject helper was NOT executed. No GPU, boot, package, sudoers or other app changes.')
    print('Rollback: sudo '+str(UNDO))

if __name__=='__main__':main()
