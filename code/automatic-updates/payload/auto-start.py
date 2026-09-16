#!/usr/bin/env python3
"""Original first activation plus restart following a recorded clean eject."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode=True

# Only load the reviewed registry reader from a root-owned directory.
import hashlib as _rh
import importlib.util as _ri
_rp = Path('/opt/gpd-egpu/update-support/registry.py')
if _rh.sha256(_rp.read_bytes()).hexdigest() != '524499d9ee094d98023cdd63d1461dc1ea0989612be929d9f458869d647125b3':
    raise RuntimeError('Registry reader changed')
_rs = _ri.spec_from_file_location('gpd_registry', _rp)
_rm = _ri.module_from_spec(_rs); _rs.loader.exec_module(_rm)
REGISTRY = _rm.read()

STATE=Path('/var/lib/gpd-egpu-auto')

def action(completed,loaded,eject):
    if not completed:return 'first'
    if loaded:return 'skip'
    if eject and eject.get('stage')=='all-nvidia-modules-unloaded':return 'restart'
    return 'skip'

def main():
    if os.uname().release not in REGISTRY:return
    gpus=[]
    for p in Path('/sys/bus/pci/devices').iterdir():
        try:
            if (p/'vendor').read_text().strip()=='0x10de' and (p/'class').read_text().strip().startswith('0x03'):gpus.append(p.name)
        except FileNotFoundError:continue
    if not gpus:return
    STATE.mkdir(parents=True,exist_ok=True)
    marker=STATE/'initializing-or-failed.json'
    if marker.exists():raise SystemExit('Failure/interruption lockout exists; no automatic retry')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    completed=STATE/(boot+'.completed')
    directory=Path('/var/lib/gpd-egpu-eject')/boot
    eject=json.loads((directory/'state.json').read_text()) if (directory/'state.json').exists() else None
    selected=action(completed.exists(),any(Path('/sys/module',n).exists() for n in ('nvidia','nvidia_uvm','nvidia_drm','nvidia_modeset')),eject)
    if selected=='skip':
        print('No clean-eject restart required or authorized');return
    record={'boot':boot,'time':time.time(),'gpu':gpus,'action':'first'}
    command=['/usr/local/sbin/gpd-egpu-start']
    if selected=='restart':
        helper=Path('/opt/gpd-egpu/auto/restart-clean-cycle.py')
        spec=importlib.util.spec_from_file_location('clean_cycle',helper)
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        record.update(action='clean-eject-restart',cycle=m.cycle_id(directory))
        command=['/usr/bin/python3',str(helper),'--automatic']
    with marker.open('x') as f:
        json.dump(record,f);f.flush();os.fsync(f.fileno())
    os.sync()
    subprocess.run(command,check=True,timeout=540)
    completed.write_text('Activation completed. Use disconnect app before physical unplug.\n')
    os.sync();marker.unlink();os.sync()
    print('Automatic '+selected+' completed; surprise unplug remains unsafe')

if __name__=='__main__':main()
