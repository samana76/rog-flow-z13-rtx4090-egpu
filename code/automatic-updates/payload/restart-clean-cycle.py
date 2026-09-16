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
 '/opt/gpd-egpu/615.71.09/loader.py':'b007d38f73b42387fe23e81d0228e6135ecdb194aaf570cbf2e40b184e51a868',
 '/opt/gpd-egpu/display-extension/display-start.py':'12158c548aa238800c0f8411816473ef7bb4969141f5b4292a4afc9a786899db',
 '/usr/local/sbin/gpd-egpu-start':'68c09c249104918c84ed27b7f5514f02c22737d0381ce54f28208bfd079e0245',
 '/usr/local/libexec/gpd-egpu-eject':'53b3974d377c556c194db65392e31c4f907aded94aa86b017717c0dbb311140f',
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

def restore_lact(eject_record, run, log):
    if eject_record.get('lact_paused') is not True:
        return 'not-requested'
    try:
        status = run(['systemctl','is-active','lactd.service'],check=False).strip()
        if status == 'active':
            return 'already-active'
        if status != 'inactive':
            log('LACT not restored: unexpected service state '+status+'; no retry')
            return 'not-restored:'+status
        run(['systemctl','start','lactd.service'],timeout=20)
        status = run(['systemctl','is-active','lactd.service'],check=False).strip()
        if status != 'active':
            raise RuntimeError('Service did not become active: '+status)
        log('LACT restored after successful clean-eject reconnect')
        return 'restored'
    except Exception as exc:
        log('WARNING: eGPU reconnect succeeded, but LACT restoration failed: '+str(exc)+'; no automatic retry')
        return 'restore-failed'

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
        check(os.uname().release in l.REGISTRY,'Unsupported restart kernel')
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
        if records[0].get('lact_paused') is True:
            checkpoint('before-lact-restore')
        record['lact_restore'] = restore_lact(records[0],t.run,t.log)
        checkpoint('completed')
        t.log('READY: original NVIDIA compute/display drivers restarted after clean eject. Disconnect app is available again. Keep cable connected until the app reports READY TO UNPLUG. Surprise unplug remains unsafe. LACT restoration result: ' + record['lact_restore'] + '.')
    except (Exception,KeyboardInterrupt) as e:
        t.log('FAIL: '+str(e)+'; no unload, recovery, record deletion or retry attempted. Evidence: '+str(base))
        raise SystemExit(1)
    finally:t.stop_follow()

if __name__=='__main__':main()
