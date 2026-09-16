#!/usr/bin/env python3
"""One volatile Arch display trial on the already validated compute driver."""
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
STATE = Path('/var/lib/gpd-egpu-display')/Path('/proc/sys/kernel/random/boot_id').read_text().strip()
DISPLAY_BUILDS = {
 '7.2.4-arch1-2': ('display-payload', {'nvidia-modeset.ko':'58db7a3b74657de9545f4ea7a8de99a35c2a3b4148e024e57c0b25ba848da003','nvidia-drm.ko':'69c7e08562525d25578bf0020b85b5ca8aad3d26d7da8c1ab7c8ea831cb48630'}),
 '7.2.5-1-cachyos': ('display-payload-7.2.5-1-cachyos', {'nvidia-modeset.ko': '1d3694df2a7c16e19a83be9a8d3793727c712df15f1f07df102d5ba6002a95ea', 'nvidia-drm.ko': 'cb56a5bd3ea8ecf94bb3dfaad34623162f5362bd5243dbf7131a9596207efc8a'})
}

# Only load the reviewed registry reader from a root-owned directory.
import hashlib as _rh
import importlib.util as _ri
_rp = Path('/opt/gpd-egpu/update-support/registry.py')
if _rh.sha256(_rp.read_bytes()).hexdigest() != '524499d9ee094d98023cdd63d1461dc1ea0989612be929d9f458869d647125b3':
    raise RuntimeError('Registry reader changed')
_rs = _ri.spec_from_file_location('gpd_registry', _rp)
_rm = _ri.module_from_spec(_rs); _rs.loader.exec_module(_rm)
REGISTRY = _rm.read()

DISPLAY_BUILDS.update({k:(v['display_payload'], {n:v['modules'][n]['sha256'] for n in ('nvidia-modeset.ko','nvidia-drm.ko')}) for k,v in REGISTRY.items()})
PAYLOAD, FILES = DISPLAY_BUILDS.get(os.uname().release, ('unsupported', {}))

def load(path):
    spec = importlib.util.spec_from_file_location('display_guard', path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def main():
    if os.geteuid() != 0 or sys.argv[1:]:
        raise SystemExit('Run manually with sudo, no arguments')
    os.umask(0o077)
    # Compute loader takes the same lock itself. It only runs if display is absent.
    if not Path('/sys/module/nvidia_modeset').exists() and not Path('/sys/module/nvidia_drm').exists():
        import subprocess
        subprocess.run(['/usr/bin/python3','/opt/gpd-egpu/615.71.09/loader.py'],check=True,timeout=360)
    lock = open('/run/lock/gpd-egpu-loader.lock','a')
    fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
    source = Path('/opt/gpd-egpu/615.71.09/loader.py')
    if hashlib.sha256(source.read_bytes()).hexdigest() != 'b007d38f73b42387fe23e81d0228e6135ecdb194aaf570cbf2e40b184e51a868':
        raise SystemExit('Installed compute loader changed; stop for review')
    l = load(source); m = l.guard()
    m.PRIVATE = STATE
    m.LOGDIR = Path('/var/log/egpu-autoconfig/display-loader')/STATE.name
    t = m.Trial()
    try:
        m.require(os.uname().release in DISPLAY_BUILDS, 'Unsupported display kernel')
        previous = json.loads((STATE/'attempt.json').read_text()) if STATE.exists() else None
        m.require(previous is None or previous.get('stage') == 'completed', 'Display attempt failed/interrupted this boot; no retry')
        modeset = Path('/sys/module/nvidia_modeset').exists()
        drm = Path('/sys/module/nvidia_drm').exists()
        m.require(modeset == drm, 'Partial display state; no reload')
        if modeset:
            l.boot_check(t,m); l.live(t,m)
            m.validate_gate(m.GATE.read_text())
            gpu,parent,hda = l.find_gpu(t,m,False)
            t.check_link(gpu,parent,hda)
            for name,expected in [('nvidia_modeset','C86CA92D8E48780F19CB46E'),('nvidia_drm','E22EBDCD6BCC5889463CFBF')]:
                m.require(t.read('/sys/module/'+name+'/srcversion') == expected, 'Loaded display build changed')
            m.require(t.read('/sys/module/nvidia_drm/parameters/modeset') == 'Y', 'Modesetting disabled')
            m.require(t.read('/sys/module/nvidia_drm/parameters/fbdev') == 'N', 'Framebuffer policy changed')
            l.nvml(t,m)
            t.log('READY: existing Arch compute and display modules verified; no reload')
            return
        m.require(previous is None, 'Completed display modules disappeared; no reload')
        l.identity(t,m); l.live(t,m)
        m.require(t.read('/sys/module/nvidia_uvm/srcversion') == '064C13389A454AA4AAF638E', 'Expected UVM missing')
        gpu,parent,hda = l.find_gpu(t,m,False)
        t.check_link(gpu,parent,hda); l.nvml(t,m)
        for dep in ('video','drm_display_helper','drm_ttm_helper'):
            m.require(Path('/sys/module',dep).exists(), 'Shared dependency not loaded: '+dep)
        for name,expected in FILES.items():
            p = HERE/PAYLOAD/name
            m.require(m.digest(p) == expected, 'Module hash mismatch: '+name)
            m.require(t.run(['modinfo','-F','vermagic',str(p)]).split()[0] == l.KERNEL, 'Module kernel mismatch')
            m.require(t.run(['modinfo','-F','version',str(p)]).strip() == '615.71.09', 'Module version mismatch')
        STATE.mkdir(parents=True,mode=0o700)
        t.owned = True
        for name in FILES:
            (STATE/name).write_bytes((HERE/PAYLOAD/name).read_bytes())
            m.require(m.digest(STATE/name) == FILES[name], 'Private copy mismatch')
        (STATE/'runner.py').write_bytes(Path(__file__).read_bytes())
        # Plasma can save output layout on DRM hotplug. Preserve the pre-trial file.
        config = Path('/home/EGPU_USER/.config/kwinoutputconfig.json')
        t.state['plasma_output_config_existed'] = config.exists()
        if config.exists(): (STATE/'kwinoutputconfig.json.before').write_bytes(config.read_bytes())
        t.state['journal_since'] = datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')
        t.state['undo'] = 'Normal reboot unloads these volatile display modules; automatic gate stays unchanged. Saved Plasma layout is retained for review, never restored over a running compositor.'
        t.checkpoint('display-baseline-ready')
        t.start_follow()
        for name,args in [('nvidia-modeset.ko',[]),('nvidia-drm.ko',['modeset=1','fbdev=0'])]:
            t.check_link(gpu,parent,hda)
            t.checkpoint('before-'+name)
            os.sync()
            t.run(['insmod',str(STATE/name),*args],timeout=45)
            t.check_link(gpu,parent,hda); t.check_errors(); l.live(t,m)
        m.require(t.read('/sys/module/nvidia_drm/parameters/modeset') == 'Y', 'DRM modeset not enabled')
        m.require(t.read('/sys/module/nvidia_drm/parameters/fbdev') == 'N', 'Unexpected framebuffer takeover')
        t.checkpoint('display-immediate-check')
        t.check_link(gpu,parent,hda); t.check_errors(); l.live(t,m); l.nvml(t,m)
        connectors = {}
        for card in Path('/sys/class/drm').glob('card[0-9]*'):
            if '-' in card.name or not (card/'device').exists() or (card/'device').resolve() != gpu.resolve(): continue
            for p in Path('/sys/class/drm').glob(card.name+'-*'):
                if (p/'status').exists():
                    connectors[p.name] = {key:t.read(p/key) for key in ('status','enabled','modes') if (p/key).exists()}
        t.state['connectors'] = connectors
        m.require(connectors, 'NVIDIA DRM exposes no connectors')
        t.result('PASS: repeatable NVIDIA display modules loaded with modeset=1/fbdev=0; PCI/NVML healthy at immediate check. Connector evidence recorded; visible monitor output still requires confirmation.')
    except (Exception,KeyboardInterrupt) as e:
        t.result('FAIL: display trial: '+str(e)+'; no unload/recovery/retry')
        raise SystemExit(1)
    finally:
        t.stop_follow()

if __name__ == '__main__': main()
