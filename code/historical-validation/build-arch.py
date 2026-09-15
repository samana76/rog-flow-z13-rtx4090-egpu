#!/usr/bin/env python3
"""Build the unpatched proprietary driver for stock Arch, without installing it."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

BASE = Path(__file__).resolve().parent

def main():
    out = BASE/'arch-kernel'
    if out.exists():
        raise SystemExit('Preserve existing Arch build; review before rebuilding')
    shutil.copytree(BASE/'extracted/kernel',out,symlinks=True)
    headers = BASE.parent/'patched-615-preparation/headers/usr/lib/modules/7.2.4-arch1-2/build'
    with (BASE/'build-arch.log').open('w') as log:
        def run(args):
            log.write(datetime.datetime.now(datetime.timezone.utc).isoformat()+' '+repr(args)+'\n');log.flush()
            subprocess.run(args,cwd=out,stdout=log,stderr=subprocess.STDOUT,check=True)
        flags = ['SYSSRC='+str(headers),'SYSOUT='+str(headers),'KERNEL_UNAME=7.2.4-arch1-2','CC=gcc','LD=ld']
        run(['make','clean',*flags])
        run(['make','-j8','modules',*flags])
        manifest = {'kernel':'7.2.4-arch1-2','driver':'615.71.09','flavor':'proprietary','runtime_tested':False,'files':{}}
        for module in sorted(out.glob('*.ko')):
            version = subprocess.check_output(['modinfo','-F','version',str(module)],text=True).strip()
            magic = subprocess.check_output(['modinfo','-F','vermagic',str(module)],text=True).strip()
            assert version == '615.71.09' and magic.split()[0] == '7.2.4-arch1-2'
            manifest['files'][str(module)] = hashlib.sha256(module.read_bytes()).hexdigest()
            log.write(str(module)+' '+version+' '+magic+'\n')
        assert len(manifest['files']) == 5
        assert subprocess.check_output(['modinfo','-F','license',str(out/'nvidia.ko')],text=True).strip() == 'NVIDIA'
        (BASE/'arch-build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print('PASS: proprietary615 Arch modules built; runtime is NOT tested. No installation/loading.')

if __name__ == '__main__':
    main()
