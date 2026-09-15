#!/usr/bin/env python3
"""One restart per recorded clean-eject cycle. No driver replacement."""
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode=True
EXPECTED={
 '/opt/gpd-egpu/615.71.09/loader.py':'0687bf1e166a5a514fdc0eb955a7a7c9a04b56ef40bd3bdffbf3fb17f002e096',
 '/opt/gpd-egpu/display-extension/display-start.py':'0c2993eecc822cba08f0d1fa6dc907c10a7618f904a62cbb8b8d6b9521bb65eb',
 '/usr/local/sbin/gpd-egpu-start':'a980026e599653b390bcea1782be008dd7de782e3173a75405f2e2a346976774',
 '/usr/local/libexec/gpd-egpu-eject':'0e3a3bbe01e141d3b9014e11d93b889df0f2a2cc1885158dee738973c5c168b6',
}

def check(value,message):
    if not value:raise RuntimeError(message)

def validate_records(boot,eject,core,display,loaded):
    check(not loaded,'NVIDIA modules remain loaded; no unload/reload attempted')
    check(eject.get('boot')==boot and eject.get('stage')=='all-nvidia-modules-unloaded',
          'No completed clean eject for this boot; no retry')
    for label,record in [('core',core),('display',display)]:
        check(record.get('boot_id')==boot and record.get('stage')=='completed',
              label+' loader did not previously complete this boot; no retry')

def archive(source,dest):
    check(source.is_dir() and not source.is_symlink(),'Unexpected record directory: '+str(source))
    check(not dest.exists(),'Archive destination already exists')
    source.rename(dest)
    for p in (source.parent,dest.parent):
        fd=os.open(p,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)

def cycle_id(eject):
    return hashlib.sha256((eject/'state.json').read_bytes()+b'\0'+(eject/'operations.log').read_bytes()).hexdigest()

def validate_marker(automatic, marker, boot, cycle):
    if automatic:
        check(marker is not None and marker.get('boot')==boot and marker.get('cycle')==cycle and marker.get('action')=='clean-eject-restart','Automatic invocation does not match its checkpoint')
    else:
        check(marker is None,'Automatic loader failure marker exists; no retry')

def main():
    check(os.geteuid()==0 and sys.argv[1:] in ([],['--automatic']),'Root execution required; invalid arguments')
    automatic=sys.argv[1:]==['--automatic']
    os.umask(0o077)
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    eject_source=Path('/var/lib/gpd-egpu-eject')/boot
    cycle=cycle_id(eject_source)
    base=Path('/var/lib/gpd-egpu-restart')/boot/cycle
    check(not base.exists(),'Restart already attempted for this eject cycle; inspect its log, no automatic retry')
    lock=open('/run/lock/gpd-egpu-loader.lock','a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for name,digest in EXPECTED.items():
        check(hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,'Working driver helper changed: '+name)
    spec=importlib.util.spec_from_file_location('working_loader',next(iter(EXPECTED)))
    l=importlib.util.module_from_spec(spec);spec.loader.exec_module(l)
    m=l.guard();m.LOGDIR=Path('/var/log/egpu-autoconfig/restart-after-eject')/boot
    t=m.Trial()
    try:
        t.log('SCRIPT SHA256 '+hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        check(os.uname().release=='7.2.4-arch1-2','Exact tested Arch kernel required')
        core=Path('/var/lib/gpd-egpu-loader')/boot
        display=Path('/var/lib/gpd-egpu-display')/boot
        eject=Path('/var/lib/gpd-egpu-eject')/boot
        records=[json.loads((p/f).read_text()) for p,f in [(eject,'state.json'),(core,'attempt.json'),(display,'attempt.json')]]
        validate_records(boot,*records,any(Path('/sys/module',n).exists() for n in ('nvidia','nvidia_uvm','nvidia_modeset','nvidia_drm','nouveau','nvidia_peermem')))
        l.identity(t,m)
        marker=Path('/var/lib/gpd-egpu-auto/initializing-or-failed.json')
        validate_marker(automatic,json.loads(marker.read_text()) if marker.exists() else None,boot,cycle)
        check((Path('/var/lib/gpd-egpu-auto')/(boot+'.completed')).is_file(),
              'Automatic first-activation completion record missing; review concurrency before restarting')
        check(t.run(['systemctl','is-active','gpd-egpu-auto.service'],check=False).strip()in (('activating',) if automatic else ('inactive',)),'Unexpected automatic loader state')
        check(not Path('/run/gpd-egpu-display-trial.active').exists(),'Experimental candidate trial remains active')
        gpu,parent,hda=l.find_gpu(t,m,False)
        check(not (gpu/'driver').exists(),'GPU is already bound; no takeover')
        for p in (parent,gpu,*hda):t.pci(p.name)
        panels=[p for p in Path('/sys/class/drm').glob('card*-eDP-*')
                if (p/'enabled').read_text().strip()=='enabled'
                and (p.parent/p.name.split('-')[0]/'device/vendor').read_text().strip()=='0x1002']
        check(panels,'Internal AMD panel must be enabled')
        base.mkdir(parents=True,mode=0o700)
        record={'boot':boot,'stage':'prepared','gpu':gpu.name,'parent':parent.name,
                'undo':'No driver/configuration/package/boot changes. Normal reboot clears restarted modules and uses normal automatic loading. Original and new per-boot histories are retained.',
                'source_hashes':EXPECTED,'archived':[]}
        def checkpoint(stage):
            record['stage']=stage
            tmp=base/'state.json.tmp'
            with tmp.open('w') as f:json.dump(record,f,indent=2);f.flush();os.fsync(f.fileno())
            tmp.replace(base/'state.json');os.sync();t.log('CHECKPOINT '+stage)
        (base/'runner.py').write_bytes(Path(__file__).read_bytes())
        config=Path('/home/EGPU_USER/.config/kwinoutputconfig.json')
        if config.exists():(base/'kwinoutputconfig.before').write_bytes(config.read_bytes())
        checkpoint('before-archive')
        for label,p in [('core',core),('display',display)]:
            record['archive_intent']=[str(p),str(base/(label+'-before'))];checkpoint('archiving-'+label)
            archive(p,base/(label+'-before'));record['archived'].append(label)
        checkpoint('before-working-loader')
        # The unchanged auto completion marker prevents udev from restarting it.
        # Release the shared lock for the existing loader, which acquires it.
        fcntl.flock(lock,fcntl.LOCK_UN)
        try:
            t.run(['/usr/local/sbin/gpd-egpu-start'],timeout=540)
        except BaseException:
            checkpoint('failed-no-retry');raise
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        l.live(t,m)
        for module,expected in [('nvidia_modeset','C86CA92D8E48780F19CB46E'),('nvidia_drm','E22EBDCD6BCC5889463CFBF')]:
            check(t.read('/sys/module/'+module+'/srcversion')==expected,'Unexpected restarted display module')
        gpu,parent,hda=l.find_gpu(t,m,False);t.check_link(gpu,parent,hda);l.nvml(t,m)
        for p in (core,display):check(json.loads((p/'attempt.json').read_text())['stage']=='completed','New loader record incomplete')
        check(json.loads((eject/'state.json').read_text())==records[0],'Eject record changed concurrently')
        checkpoint('before-retiring-completed-eject')
        archive(eject,base/'eject-before')
        checkpoint('completed')
        t.log('READY: original NVIDIA compute/display drivers restarted after clean eject. Disconnect app is available again. Keep cable connected until the app reports READY TO UNPLUG. Surprise unplug remains unsafe. LACT state unchanged.')
    except (Exception,KeyboardInterrupt) as e:
        t.log('FAIL: '+str(e)+'; no unload, recovery, record deletion or retry attempted. Evidence: '+str(base))
        raise SystemExit(1)
    finally:t.stop_follow()

if __name__=='__main__':main()
