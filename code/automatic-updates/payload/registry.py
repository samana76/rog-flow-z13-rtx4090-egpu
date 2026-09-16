"""Root-owned registry of exact private NVIDIA builds; no hardware operations."""
import json
import os
from pathlib import Path
import re
import stat

BASE = Path('/opt/gpd-egpu/update-support')
DRIVER = '615.71.09'
MODULES = ('nvidia.ko', 'nvidia-uvm.ko', 'nvidia-modeset.ko', 'nvidia-drm.ko')
SOURCES = dict(zip(MODULES, ('329D97755EFA31D5314E8F0','064C13389A454AA4AAF638E','C86CA92D8E48780F19CB46E','E22EBDCD6BCC5889463CFBF')))

def validate(data):
    if data.get('schema') != 1 or data.get('driver') != DRIVER:
        raise RuntimeError('Unsupported eGPU registry schema/driver')
    records = data['kernels']
    for kernel, r in records.items():
        if not re.fullmatch(r'[A-Za-z0-9_.+-]+', kernel):
            raise RuntimeError('Invalid kernel identifier')
        if r['package'] not in ('linux','linux-cachyos') or not re.fullmatch(r'[A-Za-z0-9_.+:-]+',r['package_version']):
            raise RuntimeError('Invalid kernel package identity')
        if r['payload'] != '/opt/gpd-egpu/615.71.09/'+kernel:
            raise RuntimeError('Invalid core payload path')
        display = r['display_payload']
        if display not in (r['payload'], '/opt/gpd-egpu/display-extension/display-payload', '/opt/gpd-egpu/display-extension/display-payload-7.2.5-1-cachyos'):
            raise RuntimeError('Invalid display payload path')
        if set(r['modules']) != set(MODULES):
            raise RuntimeError('Incomplete four-module build')
        for name, m in r['modules'].items():
            if not re.fullmatch('[0-9a-f]{64}',m['sha256']) or m['srcversion'] != SOURCES[name]:
                raise RuntimeError('Unreviewed module source identity')
            if m['version'] != DRIVER or m['vermagic'].split()[0] != kernel:
                raise RuntimeError('Module/kernel version mismatch')
    return records

def read(path=BASE/'registry.json'):
    p=Path(path)
    for item in (p, *p.parents):
        s=item.lstat()
        if stat.S_ISLNK(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise RuntimeError('Untrusted registry ownership/path: '+str(item))
    return validate(json.loads(p.read_text()))
